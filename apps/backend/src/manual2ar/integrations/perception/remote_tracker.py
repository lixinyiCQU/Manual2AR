"""Map one multi-object cloud memory into existing module-one component sessions."""
from pathlib import Path
import base64
import json
from time import monotonic,perf_counter
import cv2
import numpy as np
from manual2ar_perception.cpu_tracker import CpuLearningTracker,CpuTracked
from .client import CutieClient
from manual2ar.infrastructure.diagnostics import dump


class CutieTracker:
    provider_name='sam31-cutie-stream-v2'

    def __init__(self,config):
        self.config=config;self.local=CpuLearningTracker(config['cpu_tracking'])
        self.client=None;self.bindings={};self.pending=set();self.index=0;self.log=None;self.shared_masks={}

    def _event(self,event,data):
        if self.log:self.log.event(event,data)

    def shutdown(self):
        if self.client:
            try:self.client.close()
            except Exception as error:self._event('learning.cutie_cleanup_error',{'error_type':type(error).__name__})
        self.client=None
        for identity in list(self.bindings):self.local.close(identity)
        self.bindings.clear();self.pending.clear();self.shared_masks={}

    def prepare(self,image,candidates,folder,log,minimum_confidence):
        self.shutdown();self.log=log;self.index=0
        self.local.external_masks={}
        targets=[dict(component_id=c.component_id,bbox_0_1000=c.bbox_0_1000,
            target_point_0_1000=c.target_point_0_1000) for c in candidates if c.found and c.confidence>=minimum_confidence]
        if not targets:return
        config=self.config['cutie_tracking'];started=perf_counter();phase='connect';dest=folder/'cutie';dest.mkdir(exist_ok=True)
        try:
            connection=json.loads(Path(config['connection_file']).read_text())
            self.client=CutieClient(connection,timeout=config['initialization_timeout_seconds'])
            health=self.client.health();dump(dest/'health.json',health)
            probes=self.client.probe();dump(dest/'network_probe.json',probes);self._event('performance.network_probe',dict(samples=probes))
            phase='initialize'
            masks,value=self.client.start(image,targets)
            self.local.external_masks={key:mask.astype(np.uint8)*255 for key,mask in masks.items()}
            self.client.http.timeout=config['request_timeout_seconds']
            self.pending={t['component_id'] for t in targets}
            dump(dest/'initialization.json',{k:v for k,v in value.items() if k!='label_map'})
            for identity,mask in masks.items():cv2.imwrite(str(dest/(identity+'_mask.png')),mask.astype(np.uint8)*255)
            self._event('learning.segmenter',dict(check_id=folder.name,first_mask='sam3.1',tracking=self.provider_name,
                elapsed_ms=round((perf_counter()-started)*1000,2),**value['metrics'],http_roundtrip_ms=value['http_roundtrip_ms']))
        except Exception as error:
            failure=dict(check_id=folder.name,phase=phase,error_type=type(error).__name__,
                http_status=getattr(getattr(error,'response',None),'status_code',None),elapsed_ms=round((perf_counter()-started)*1000,2))
            dump(dest/'provider_error.json',failure);self._event('learning.segmenter_error',failure)
            self.shutdown();raise

    def start(self,image,component_id,box,guidance_target=None):
        identity=component_id.removeprefix('intro_')
        try:
            if not self.client or identity not in self.pending:raise ValueError('No initialized cloud mask for this component')
            session,tracked=self.local.start(image,component_id,box,guidance_target)
            tracked=CpuTracked.model_validate({**tracked.model_dump(), 'provider':self.provider_name,
                'tracking_state':'tracking' if tracked.mask_quality_passed else 'lost'})
            if tracked.mask_quality_passed:
                self.bindings[session]=dict(identity=identity,contract=guidance_target,last=tracked,
                    failed_since=None,failed_frames=0,recovered=0)
            return session,tracked
        finally:
            self.pending.discard(identity)
            if not self.pending and not self.bindings and self.client:self.shutdown()

    def close(self,session):
        self.bindings.pop(session,None);closed=self.local.close(session)
        if not self.bindings and not self.pending and self.client:self.shutdown()
        return closed

    def update(self,session,image):return self.update_many([session],image)[session]

    def _describe(self,state,mask,now,reason=None):
        prior=state['last'];settings=self.config['cutie_tracking'];h,w=mask.shape;area=float(mask.mean());contract=state['contract']
        if reason is None and (not area or (contract and not contract.expected_area_ratio_min<=area<=contract.expected_area_ratio_max)):
            reason='current_mask_area_rejected'
        if reason:
            if state['failed_since'] is None:state['failed_since']=now
            state['failed_frames']+=1
            retained=reason=='current_mask_area_rejected' and now-state['failed_since']<settings['recovery_seconds'] and state['failed_frames']<=settings['recovery_max_frames']
            return prior.model_copy(update=dict(status='lost',quality=0,overlay_png_base64='',mask_quality_passed=False,
                mask_area_ratio=area,requires_redetection=True,tracking_state='recovering' if retained else 'lost',
                retained_for_recovery=retained,frame_index=self.index,mask_quality_reasons=[reason]))
        if state['failed_since'] is not None:
            if now-state['failed_since']>=settings['recovery_seconds'] or state['failed_frames']>settings['recovery_max_frames']:
                return self._describe(state,mask,now,'recovery_deadline_exceeded')
            state['recovered']+=1
        state['failed_since']=None;state['failed_frames']=0
        binary=mask.astype(np.uint8);moments=cv2.moments(binary,True);x,y,bw,bh=cv2.boundingRect(binary)
        encoded=''
        if not self.config.get('performance',{}).get('compact_masks',True):
            overlay=np.zeros((bh,bw,4),np.uint8);overlay[mask[y:y+bh,x:x+bw]]=[233,215,22,130]
            ok,png=cv2.imencode('.png',overlay,[cv2.IMWRITE_PNG_COMPRESSION,1])
            if not ok:raise ValueError('Overlay encoding failed')
            encoded=base64.b64encode(png).decode()
        tracked=prior.model_copy(update=dict(status='tracking',quality=1.,mask_quality_passed=True,
            overlay_png_base64=encoded,requires_redetection=False,mask_quality_reasons=[],
            mask_area_ratio=area,prompt_containment=prior.prompt_containment,
            bbox_0_1000=[round(x/w*1000),round(y/h*1000),round((x+bw)/w*1000),round((y+bh)/h*1000)],
            centroid_0_1000=[round(moments['m10']/moments['m00']/w*1000),round(moments['m01']/moments['m00']/h*1000)],
            mask_roi_xywh=[x,y,bw,bh],mask_frame_width=w,mask_frame_height=h,tracking_state='tracking',
            retained_for_recovery=False,frame_index=self.index,relocalization_count=state['recovered'],
            motion_diagnostics={'quality_scope':'binary mask area gate; not Cutie semantic confidence',
                'initial_box_containment_applied':False,'initial_prompt_containment':prior.prompt_containment}))
        state['last']=tracked
        return tracked

    def update_many(self,sessions,image,**kwargs):
        if not sessions:return {}
        started=perf_counter();self.index+=1
        try:
            if not self.client:raise ValueError('Cloud memory no longer available')
            masks,value=self.client.step(image,self.index);self.shared_masks=masks
            now=monotonic();output={s:self._describe(self.bindings[s],masks[self.bindings[s]['identity']],now) for s in sessions}
            batch=dict(provider=self.provider_name,objects=len(sessions),remote_frame_id=self.index,
                http_roundtrip_ms=value['http_roundtrip_ms'],**value['metrics'])
            self._event('learning.cutie_frame',dict(frame_id=self.index,source_sha256=value['source_sha256'],
                targets_sha256=value['targets_sha256'],**batch))
        except Exception as error:
            self.shared_masks={}
            reason='cloud_'+type(error).__name__;now=monotonic();output={}
            for session in sessions:
                state=self.bindings[session];h,w=state['last'].mask_frame_height,state['last'].mask_frame_width
                if not h or not w:
                    h,w=self.local._states[session].mask.shape
                output[session]=self._describe(state,np.zeros((h,w),bool),now,reason)
            batch=dict(provider=self.provider_name,objects=len(sessions),remote_frame_id=self.index,error_type=type(error).__name__,
                http_status=getattr(getattr(error,'response',None),'status_code',None),requires_redetection=True)
            self._event('learning.cutie_error',batch)
        self.local.last_batch_metrics={**batch,'total_ms':round((perf_counter()-started)*1000,2)}
        return output
