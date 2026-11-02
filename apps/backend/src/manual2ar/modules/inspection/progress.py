"""Bounded staged inspection jobs; one serial worker per camera/static run.

Blocking provider calls are cooperatively cancelled at stage boundaries. A late
provider reply is cleaned up and never becomes a result of a superseding job.
"""
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass,field
from threading import Event,Lock,Thread
from time import perf_counter
import uuid
from fastapi import HTTPException
from .service import InspectionCancelled

TERMINAL={'completed','failed','cancelled'}

@dataclass
class Job:
    id:str
    run_id:str
    check_id:str
    frame:object
    frame_id:int
    sha:str
    events:list=field(default_factory=list)
    cancelled:object=field(default_factory=Event)

@dataclass
class Lane:
    run:object
    current:object=None
    pending:object=None
    running:bool=False
    closed:bool=False
    highest_frame:int=0

class InspectionJobs:
    def __init__(self,service):
        self.service=service;self.lock=Lock();self.jobs=OrderedDict();self.lanes={};self.tombstones=OrderedDict();self.stopped=False

    def _event(self,job,phase,result=None,error=None):
        # Called with self.lock held. Snapshots must not share mutable rows with
        # the ongoing segmenter, which updates tracking_ready/quality in place.
        value={'job_id':job.id,'run_id':job.run_id,'check_id':job.check_id,
            'client_frame_id':job.frame_id,'source_sha256':job.sha,'revision':len(job.events)+1,
            'phase':phase,'finished':phase in TERMINAL,'cancelled':phase=='cancelled',
            'result':deepcopy(result),'error':error}
        job.events.append(value)
        lane=self.lanes.get(job.run_id)
        if lane:
            lane.run.log.event('inspection.progress',{'job_id':job.id,'check_id':job.check_id,'phase':phase,'revision':value['revision']})
        return value

    def _cancel(self,job):
        if job is None:return
        if job.events and job.events[-1]['phase'] in ('completed','failed'):return
        job.cancelled.set()
        if not job.events or job.events[-1]['phase'] not in TERMINAL:self._event(job,'cancelled')

    def _trim(self):
        for key,job in list(self.jobs.items()):
            if len(self.jobs)<=64:break
            if job.events and job.events[-1]['finished'] and job.frame is None:self.jobs.pop(key,None)

    def submit(self,identity,frame):
        run=self.service.get(identity);self.service.image(frame)
        with self.lock:
            if self.stopped:raise HTTPException(503,'检查服务正在关闭。')
            existing=self.jobs.get(frame.request_id)
            if existing:
                if existing.run_id!=identity or existing.frame_id!=frame.client_frame_id or existing.sha!=frame.source_sha256:raise HTTPException(409,'检查请求标识不匹配。')
                return self._read(existing,0)
            lane=self.lanes.setdefault(identity,Lane(run,highest_frame=run.last_frame))
            if lane.closed or run.closed:raise HTTPException(404,'检查会话已结束。')
            if frame.client_frame_id<=max(lane.highest_frame,run.last_frame):raise HTTPException(409,'旧图像不能覆盖新的检查结果。')
            lane.highest_frame=frame.client_frame_id
            self._cancel(lane.current);self._cancel(lane.pending)
            if lane.pending:lane.pending.frame=None
            job=Job(frame.request_id,identity,'check_'+uuid.uuid4().hex[:16],frame,frame.client_frame_id,frame.source_sha256)
            self.jobs[job.id]=job
            if (identity,job.id) in self.tombstones:
                job.frame=None;self._cancel(job)
            else:
                self._event(job,'queued');lane.pending=job
                if not lane.running:
                    lane.running=True;Thread(target=self._work,args=(identity,lane),daemon=True,name='plate-inspection').start()
            self._trim();return self._read(job,0)

    def _read(self,job,after):
        # Deliver stages in order even if the GPU completed before the first
        # poll. Cancellation always takes precedence over queued old stages.
        if job.cancelled.is_set():return deepcopy(job.events[-1])
        for event in job.events:
            if event['revision']>after:return deepcopy(event)
        value=deepcopy(job.events[-1]);value['result']=None;return value

    def get(self,identity,job_id,after=0):
        with self.lock:
            job=self.jobs.get(job_id)
            if not job or job.run_id!=identity:raise HTTPException(404,'检查任务不存在。')
            return self._read(job,after)

    def cancel(self,identity,job_id):
        with self.lock:
            job=self.jobs.get(job_id)
            if job and job.run_id==identity:
                self._cancel(job)
                lane=self.lanes.get(identity)
                if lane and lane.pending is job:lane.pending=None;job.frame=None
            elif not job:
                # A cancellation can overtake its POST on the network.
                self.tombstones[(identity,job_id)]=True
                while len(self.tombstones)>128:self.tombstones.popitem(last=False)

    def busy(self,identity):
        with self.lock:
            lane=self.lanes.get(identity)
            return bool(lane and (lane.current is not None or lane.pending is not None))

    def _work(self,identity,lane):
        while True:
            with self.lock:
                job=lane.pending;lane.pending=None
                if job is None or lane.closed:
                    lane.running=False;lane.current=None
                    if lane.closed:self.lanes.pop(identity,None)
                    return
                lane.current=job;self._event(job,'recognizing')
            def cancelled():return job.cancelled.is_set() or lane.closed or self.stopped
            def publish(value):
                with self.lock:
                    if cancelled():raise InspectionCancelled()
                    self._event(job,'segmenting',value)
            started=perf_counter();failed=False
            try:
                result=self.service.inspect(identity,job.frame,progress=publish,cancelled=cancelled,check_id=job.check_id)
                with self.lock:
                    if not cancelled():self._event(job,'completed',result)
            except InspectionCancelled:
                pass
            except Exception as error:
                failed=True
                lane.run.log.event('inspection.job_error',{'job_id':job.id,'error_type':type(error).__name__})
                with self.lock:
                    if not cancelled():
                        last=next((e['result'] for e in reversed(job.events) if e['result'] is not None),None)
                        self._event(job,'failed',last,error='inspection_failed')
            finally:
                if cancelled() or (failed and lane.run.check_id==job.check_id):
                    with lane.run.lock:
                        lane.run.tracker.shutdown();lane.run.sessions={};lane.run.objects=[]
                    if cancelled():
                        with self.lock:self._cancel(job)
                lane.run.log.event('inspection.job_finished',{'job_id':job.id,'cancelled':cancelled(),'failed':failed,'elapsed_ms':round((perf_counter()-started)*1000,2)})
                with self.lock:job.frame=None;lane.current=None;self._trim()

    def close_run(self,identity):
        with self.lock:
            lane=self.lanes.get(identity)
            if lane:
                lane.closed=True;self._cancel(lane.current);self._cancel(lane.pending)
                if lane.pending:lane.pending.frame=None;lane.pending=None
                if not lane.running:self.lanes.pop(identity,None)
        with self.service.registry_lock:
            run=self.service.runs.pop(identity,None)
            if run:run.closed=True
        if run:
            def cleanup():
                with run.lock:
                    run.tracker.shutdown();run.sessions={};run.objects=[];run.log.event('run.closed',{})
            Thread(target=cleanup,daemon=True,name='plate-inspection-cleanup').start()

    def shutdown(self):
        self.stopped=True
        for identity in list(self.service.runs):self.close_run(identity)
