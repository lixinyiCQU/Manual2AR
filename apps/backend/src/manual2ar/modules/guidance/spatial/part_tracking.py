"""Photo -> semantic parts -> GPU masks, with local CPU failover; independent of metric anchors."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass,field
import base64
import copy
import hashlib
import json
from pathlib import Path
import threading
import time
import uuid
import cv2
import numpy as np
from fastapi import HTTPException
from manual2ar.integrations.perception.client import CutieClient
from manual2ar.integrations.perception.cpu_client import CpuMaskClient
from .u7_vision import identify
from .vision_context import write,failure


@dataclass
class Job:
    identity:str
    session_id:str
    folder:Path
    raw:bytes
    frame_id:int
    sha:str
    lock:object=field(default_factory=threading.RLock)
    io_lock:object=field(default_factory=threading.RLock)
    cancelled:bool=False
    phase:str='recognizing'
    client:object=None
    result:dict=field(default_factory=dict)
    observations:list=field(default_factory=list)
    remote_frame:int=0
    last_frame:int=0
    shape:tuple=()
    action_id:str='holder.slide'
    provider:str='sam31_cutie'
    targets:list=field(default_factory=list)
    last_raw:bytes=b''
    last_masks:dict=field(default_factory=dict)
    future:object=None


class PartTracking:
    def __init__(self,config,vlm,references,event,client_factory=CutieClient,recognize=None):
        self.config=config;self.vlm=vlm;self.references=references;self.event=event;self.client_factory=client_factory
        self.recognize=recognize or identify;self.review=None
        self.gpu_retry_at=0.0
        self.jobs={};self.retained={};self.lock=threading.RLock();self.pool=ThreadPoolExecutor(max_workers=4,thread_name_prefix='u7-parts')

    def begin(self,session,frame):
        with self.lock:
            current=self.jobs.get(session)
            if current and current.phase=='tracking':
                retained=self.retained.get(session)
                if retained and retained is not current:self.cancel(session,retained.identity)
                self.retained[session]=current
            elif current and current is not self.retained.get(session):
                self.cancel(session,current.identity)
        identity=uuid.uuid4().hex;folder=Path(self.config['runtime_dir'])/'guidance-spatial/runs'/session/('parts-'+identity);folder.mkdir(parents=True,exist_ok=True)
        job=Job(identity,session,folder,frame['raw'],frame['client_frame_id'],frame['sha256'],action_id=frame.get('action_id','holder.slide'))
        with self.lock:
            self.jobs[session]=job
            job.future=self.pool.submit(self._initialize,job)
        return self.status(session,identity)

    def _initialize(self,job):
        started=time.perf_counter();client=None
        try:
            with job.lock:
                if job.cancelled:return
            self.event(job,'parts.recognition_started',{})
            with job.lock:
                if job.cancelled:return
            answer=self.recognize(self.vlm,self.config,job.raw,self.references['base'],self.references['holder'],job.folder,action_id=job.action_id)
            if job.action_id=='holder.base':
                for part in answer.parts:
                    if part.component_id!='spool_holder_base':part.status='unseen';part.bbox_0_1000=[];part.foreground_point_0_1000=[]
            with job.lock:
                if job.cancelled:return
                job.observations=answer.parts;job.advice=answer.next_action
                job.result={'parts':[p.model_dump() for p in answer.parts],'next_action':answer.next_action,'overlay_png_base64':''};job.phase='located'
            self.event(job,'parts.recognition_finished',{'elapsed_ms':round((time.perf_counter()-started)*1000),'parts':[{'id':p.component_id,'status':p.status} for p in answer.parts]})
            targets=[{'component_id':p.component_id,'bbox_0_1000':p.bbox_0_1000,'target_point_0_1000':p.foreground_point_0_1000} for p in answer.parts if p.status=='found']
            if not targets:
                with job.lock:job.phase='not_found'
                return
            self.event(job,'parts.segmentation_started',{'objects':len(targets)})
            job.targets=targets
            client,masks,metrics=self._start_masks(job)
            image=cv2.imdecode(np.frombuffer(job.raw,np.uint8),cv2.IMREAD_COLOR);job.shape=image.shape[:2]
            h,w=job.shape
            for target in targets:
                mask=masks.get(target['component_id'])
                if mask is None or mask.shape!=(h,w):continue
                x,y,r,b=np.asarray(target['bbox_0_1000'])*[w,h,w,h]/1000
                px,py=np.asarray(target['target_point_0_1000'])*[w,h]/1000
                count=int(mask.sum());overlap=int(mask[max(0,int(y)):min(h,int(b)+1),max(0,int(x)):min(w,int(r)+1)].sum())
                near=mask[max(0,int(py)-3):min(h,int(py)+4),max(0,int(px)-3):min(w,int(px)+4)]
                if not count or overlap/max(count,1)<.55 or not near.any():
                    masks[target['component_id']]=np.zeros((h,w),bool)
                    self.event(job,'parts.initial_mask_rejected',{'component_id':target['component_id'],'box_containment':round(overlap/max(count,1),3)})
            if self.review:
                revised=self.review(job.raw,job.observations,masks,job.folder)
                updated=[{'component_id':p.component_id,'bbox_0_1000':p.bbox_0_1000,'target_point_0_1000':p.foreground_point_0_1000} for p in revised if p.status=='found']
                if updated!=job.targets:
                    self.event(job,'parts.mask_corrected',{'objects_before':len(job.targets),'objects_after':len(updated),'attempt':1})
                    self.pool.submit(self._close,job,client);client=None
                    job.observations=revised;job.targets=updated
                    if not updated:
                        with job.lock:job.result={'parts':[p.model_dump() for p in revised],'next_action':'掩膜语义检查未通过，请重新取景。','overlay_png_base64':''};job.phase='not_found'
                        return
                    client,masks,metrics=self._start_masks(job)
                    # Corrected initialization still must agree with the new ROI and foreground.
                    for target in updated:
                        mask=masks.get(target['component_id'])
                        if mask is None or mask.shape!=(h,w):raise ValueError('Corrected mask shape mismatch')
                        x,y,r,b=np.asarray(target['bbox_0_1000'])*[w,h,w,h]/1000
                        px,py=np.asarray(target['target_point_0_1000'])*[w,h]/1000
                        count=int(mask.sum());overlap=int(mask[max(0,int(y)):min(h,int(b)+1),max(0,int(x)):min(w,int(r)+1)].sum())
                        if not count or overlap/count<.55 or not mask[max(0,int(py)-3):min(h,int(py)+4),max(0,int(px)-3):min(w,int(px)+4)].any():
                            masks[target['component_id']]=np.zeros((h,w),bool)
            for name,mask in masks.items():cv2.imwrite(str(job.folder/(name+'_initial_mask.png')),mask.astype(np.uint8)*255)
            with job.lock:
                if job.cancelled:return
                job.client=client;client=None;job.result=self._render(job,masks);job.phase='tracking';job.last_frame=job.frame_id;job.last_raw=job.raw;job.last_masks={k:v.copy() for k,v in masks.items()}
            self.event(job,'parts.segmentation_finished',{'elapsed_ms':round((time.perf_counter()-started)*1000),'provider':job.provider,'metrics':metrics.get('metrics',{})})
        except Exception as error:
            details=failure(job.folder,error)
            with job.lock:
                if job.cancelled:return
                job.phase='segmentation_unavailable' if job.result else 'failed'
                job.result.update(next_action='分割暂不可用，已保留识别框，请重新识别。' if job.result else '识别暂不可用，请重新拍摄。')
            self.event(job,'parts.failed',details)
        finally:
            if client:
                try:client.close()
                except Exception:pass

    def _start_masks(self,job):
        client=None
        try:
            with job.lock:
                if job.cancelled:raise HTTPException(409,'部件识别已取消。')
            with self.lock:cooling_down=time.monotonic()<self.gpu_retry_at
            if cooling_down:raise ConnectionError('GPU retry cooldown')
            connection=json.loads(Path(self.config['gpu_connection_file']).read_text())
            client=self.client_factory(connection,timeout=2);client.health()
            with job.lock:
                if job.cancelled:raise HTTPException(409,'部件识别已取消。')
            client.http.timeout=self.config['localization']['initialization_timeout_seconds']
            masks,metrics=client.start(job.raw,job.targets)
            client.http.timeout=self.config['localization']['tracking_timeout_seconds'];job.provider='sam31_cutie'
            return client,masks,metrics
        except Exception as error:
            if client:self.pool.submit(self._close,job,client)
            with job.lock:
                if job.cancelled:raise HTTPException(409,'部件识别已取消。')
            return self._cpu_fallback(job,error,job.raw)

    def _cpu_fallback(self,job,error,raw,masks=None):
        with self.lock:
            now=time.monotonic()
            if now>=self.gpu_retry_at:self.gpu_retry_at=now+60
        self.event(job,'parts.provider_fallback',{'from':'sam31_cutie','to':'opencv','reason':type(error).__name__,'stage':'tracking' if masks is not None else 'initialization'})
        client=CpuMaskClient(self.config.get('cpu_tracking'))
        try:result,metrics=client.start(raw,job.targets,masks)
        except Exception:
            client.close();raise
        job.provider='opencv'
        return client,result,metrics

    def _job(self,session,identity):
        with self.lock:
            job=next((j for j in (self.jobs.get(session),self.retained.get(session)) if j and j.identity==identity),None)
        if not job or job.cancelled:raise HTTPException(409,'部件识别已结束，请重新拍摄。')
        return job

    def status(self,session,identity):
        job=self._job(session,identity)
        with job.lock:
            return {'job_id':job.identity,'session_id':session,'phase':job.phase,'client_frame_id':job.frame_id,'source_sha256':job.sha,'guidance':job.result.get('next_action',''),**copy.deepcopy(job.result)}

    def track(self,session,identity,frame):
        job=self._job(session,identity)
        with job.io_lock:
            with job.lock:
                if job.phase!='tracking' or not job.client:raise HTTPException(409,'部件分割尚未就绪。')
                if frame['client_frame_id']<=job.last_frame:raise HTTPException(409,'跟踪画面顺序已改变。')
                client=job.client;job.remote_frame+=1;index=job.remote_frame
            try:
                try:
                    masks,metrics=client.step(frame['raw'],index)
                except Exception as error:
                    if job.provider=='opencv':raise
                    local,_,_=self._cpu_fallback(job,error,job.last_raw,job.last_masks)
                    with job.lock:
                        if job.cancelled:
                            local.close();raise HTTPException(409,'部件识别已结束。')
                        job.client=local
                    self.pool.submit(self._close,job,client)
                    masks,metrics=local.step(frame['raw'],index)
                with job.lock:
                    if job.cancelled:raise HTTPException(409,'部件识别已结束。')
                    result=self._render(job,masks);job.last_frame=frame['client_frame_id'];job.last_raw=frame['raw'];job.last_masks={k:v.copy() for k,v in masks.items()}
                self.event(job,'parts.tracked',{'client_frame_id':frame['client_frame_id'],'source_sha256':frame['sha256'],'provider':job.provider,'metrics':metrics.get('metrics',{})})
                return {'job_id':identity,'session_id':session,'phase':'tracking','client_frame_id':frame['client_frame_id'],'source_sha256':frame['sha256'],**result}
            except HTTPException:raise
            except Exception as error:
                self.event(job,'parts.tracking_failed',{'error_type':type(error).__name__})
                return {'job_id':identity,'session_id':session,'phase':'tracking_lost','client_frame_id':frame['client_frame_id'],'source_sha256':frame['sha256'],'parts':[],'overlay_png_base64':'','next_action':'部件跟踪中断，请重新识别。'}

    def _render(self,job,masks):
        height,width=job.shape;overlay=np.zeros((height,width,4),np.uint8);parts=[]
        for obs in job.observations:
            value=obs.model_dump();mask=masks.get(obs.component_id)
            if mask is None or mask.shape!=(height,width) or not .00008<=float(mask.mean())<=.45:
                value.update(status='lost',bbox_0_1000=[],proxy=None);parts.append(value);continue
            mask=mask.astype(bool);x,y,w,h=cv2.boundingRect(mask.astype(np.uint8));box=[round(x/width*1000),round(y/height*1000),round((x+w)/width*1000),round((y+h)/height*1000)]
            overlay[mask]=(225,205,30,90) if obs.component_id=='spool_holder_base' else (70,200,255,90)
            proxy=None
            if obs.component_id=='external_spool_holder':
                yy,xx=np.nonzero(mask);cov=np.cov(np.stack([xx,yy]));_,vectors=np.linalg.eigh(cov);axis=vectors[:,-1]
                reference=np.array(obs.axis_end_0_1000)-np.array(obs.axis_start_0_1000) if obs.axis_start_0_1000 else np.array([1.,0.])
                if np.dot(axis,reference)<0:axis=-axis
                proxy={'asset_id':'part.spool_holder_proxy','coordinate_space':'image_proxy','bbox_0_1000':box,'angle_degrees':float(np.degrees(np.arctan2(axis[1],axis[0]))),'illustrative_only':True}
            value.update(status='found',bbox_0_1000=box,proxy=proxy);parts.append(value)
        encoded=cv2.imencode('.png',overlay,[cv2.IMWRITE_PNG_COMPRESSION,1])[1].tobytes()
        missing=[('底座' if p['component_id']=='spool_holder_base' else '料盘支架') for p in parts if p['status']!='found' and (job.action_id!='holder.base' or p['component_id']=='spool_holder_base')]
        message=('、'.join(missing)+'暂不可见，请调整画面或重新识别。') if missing else ('底座高亮 · 跟踪中' if job.action_id=='holder.base' else '两部件高亮与支架示意 · 跟踪中')
        if job.provider=='opencv':message+=' · 本机 CPU'
        return {'guidance':getattr(job,'advice',''),'parts':parts,'overlay_png_base64':base64.b64encode(encoded).decode(),'next_action':message,'width':width,'height':height,'provider':job.provider,'fallback_used':job.provider=='opencv'}

    def cancel(self,session,expected_identity=None):
        with self.lock:
            removed={}
            for registry in (self.jobs,self.retained):
                job=registry.get(session)
                if job and (expected_identity is None or job.identity==expected_identity):
                    registry.pop(session);removed[job.identity]=job
            for job in removed.values():
                with job.lock:
                    job.cancelled=True;client=job.client;job.client=None
                    if job.future:job.future.cancel()
                if client:self.pool.submit(self._close,job,client)

    @staticmethod
    def _close(job,client):
        with job.io_lock:
            try:client.close()
            except Exception:pass

    def shutdown(self):
        for session in set(self.jobs)|set(self.retained):self.cancel(session)
        self.pool.shutdown(wait=False,cancel_futures=False)
