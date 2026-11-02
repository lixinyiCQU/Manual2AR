"""Plate semantics -> module-one segmentation/tracking -> independent display gates."""
from pathlib import Path
from dataclasses import dataclass,field
from time import monotonic,perf_counter
from types import SimpleNamespace
import base64,hashlib,io,json,threading,uuid
import cv2
import numpy as np
from PIL import Image
from fastapi import HTTPException
from pydantic import ValidationError
from manual2ar_contracts.perception import GuidanceTarget
from manual2ar_perception.segmentation import mask_context
from manual2ar.integrations.vlm.audit import AuditedQwen,context as audit_context
from .tracker import InspectionTracker
from manual2ar_contracts.gpu import encode_labels
from .contracts import Observation
from .logging import InspectionLog,dump,now
from .rules import VERSION
from .presentation import public_result
from .scene_watch import PlateSceneWatch
from .plate_scope import update_scope,scope_decision
from .visualization import save_overlay
from .normalization import normalize_observation
from manual2ar.integrations.vlm.client import VisionError

from manual2ar.resources import ResourceStore

class InspectionCancelled(RuntimeError):pass

def plate_point_conflicts(obs):
    if not obs.plate.found or obs.plate.target_point_0_1000 is None:return []
    x,y=obs.plate.target_point_0_1000
    return [a.bbox_0_1000 for a in obs.anomalies if a.found and a.on_plate=='yes'
            and a.bbox_0_1000[0]<=x<=a.bbox_0_1000[2] and a.bbox_0_1000[1]<=y<=a.bbox_0_1000[3]]

@dataclass
class Run:
    id:str
    provider:str
    source:str
    tracker:object
    log:object
    lock:object=field(default_factory=threading.Lock)
    sessions:dict=field(default_factory=dict)
    objects:list=field(default_factory=list)
    last_frame:int=0
    check_id:str=''
    decision:dict=field(default_factory=lambda:{'status':'not_checked','message':'尚未检查。'})
    last_active:float=field(default_factory=monotonic)
    last_sample:float=0
    samples:int=0
    closed:bool=False
    scene_watch:object=None
    scene_changed:bool=False
    current_plate_usable:bool=False
    removed_ids:set=field(default_factory=set)
    resolution_signature:object=None

class InspectionService:
    def __init__(self,config,client=None,tracker_factory=None,log_root=None):
        self.config=config;self.runs={};self.registry_lock=threading.RLock();self.vlm_slot=threading.BoundedSemaphore(1)
        self.tracker_factory=tracker_factory or (lambda provider:InspectionTracker(provider,config))
        self.log_root=Path(log_root or Path(config['runtime_dir'])/'inspection')
        if client is None:
            client=AuditedQwen(config['vlm'])
        self.client=client
    def begin(self,request):
        if request.task_id!='plate_surface':raise HTTPException(409,'该任务尚未开放。')
        with self.registry_lock:
            for key,r in list(self.runs.items()):
                if monotonic()-r.last_active>self.config['inspection']['idle_minutes']*60 and r.lock.acquire(False):
                    try:r.closed=True;r.tracker.shutdown();self.runs.pop(key,None)
                    finally:r.lock.release()
            if len(self.runs)>=self.config['inspection']['max_runs']:raise HTTPException(429,'请先关闭较早的检查会话。')
            identity=uuid.uuid4().hex;log=InspectionLog(self.log_root/identity)
            r=Run(identity,request.provider,request.source,self.tracker_factory(request.provider),log);r.scene_watch=PlateSceneWatch(self.config['inspection']);self.runs[identity]=r
            from .manage import public
            dump(log.path/'session.json',{'run_id':identity,'task_id':request.task_id,'provider':request.provider,'source':request.source,'created_at':now(),'public_config':public(self.config)})
            log.event('run.started',{'run_id':identity,'provider':request.provider,'source':request.source})
            return {'run_id':identity,'provider':request.provider,'source':request.source}
    def get(self,identity):
        with self.registry_lock:r=self.runs.get(identity)
        if r is None or r.closed:raise HTTPException(404,'检查会话已结束，请重新进入任务。')
        r.last_active=monotonic();return r
    def acquire(self,r):
        if not r.lock.acquire(False):raise HTTPException(409,'本次请求仍在处理，请稍后重试。')
        if r.closed:r.lock.release();raise HTTPException(404,'会话已结束。')
    def image(self,frame):
        try:
            data=base64.b64decode(frame.image_base64,validate=True)
            if len(data)>2000000 or hashlib.sha256(data).hexdigest()!=frame.source_sha256:raise ValueError()
            with Image.open(io.BytesIO(data)) as image:
                if image.format!='JPEG' or min(image.size)<16 or max(image.size)>1280:raise ValueError()
                image.verify()
            return data
        except Exception:raise HTTPException(422,'图像格式、大小或帧校验失败，请重新拍摄。') from None
    def _accept_frame(self,r,frame):
        if frame.client_frame_id<=r.last_frame:raise HTTPException(409,'旧图像不能覆盖新的检查结果。')
        r.last_frame=frame.client_frame_id
    def _reset(self,r):
        r.tracker.shutdown();r.sessions={};r.objects=[];r.scene_watch.reset()
        r.scene_changed=False;r.current_plate_usable=False;r.removed_ids.clear();r.resolution_signature=None
        r.tracker=self.tracker_factory(r.provider)
    def _reply(self,r,frame,objects,label_map=None,decision=None,**extra):
        decision=r.decision if decision is None else decision
        return {'run_id':r.id,'check_id':r.check_id,'client_frame_id':frame.client_frame_id,'source_sha256':frame.source_sha256,
                'decision':decision,'public_result':{**public_result(decision,objects,extra.get('scene_candidates',[])),**({'visual_state':extra['tracking_state']} if extra.get('stage')=='tracking' else {})},'objects':objects,'label_map':label_map,'active_tracks':len(r.sessions),**extra}
    def _mask(self,tracked,identity,tracker):
        shared=getattr(tracker.engine,'shared_masks',{})
        if identity in shared:return np.asarray(shared[identity],bool)
        if not tracked.overlay_png_base64:return None
        png=cv2.imdecode(np.frombuffer(base64.b64decode(tracked.overlay_png_base64),np.uint8),cv2.IMREAD_UNCHANGED)
        if png is None:return None
        mask=png[:,:,3]>0 if png.ndim==3 and png.shape[2]==4 else png>0
        roi=getattr(tracked,'mask_roi_xywh',[])
        if roi:
            x,y,w,h=roi;canvas=np.zeros((tracked.mask_frame_height,tracked.mask_frame_width),bool);canvas[y:y+h,x:x+w]=mask;return canvas
        return mask
    def _wire(self,rows,masks):
        # One ID texture, colored in the Unity shader. Anomaly labels paint over
        # plate labels; overlapping target masks never erase semantic findings.
        selected={};occupied=None
        for row in reversed(rows):
            key=row['id'];mask=masks.get(key)
            if not row['tracking_ready'] or mask is None:continue
            if occupied is None:occupied=np.zeros(mask.shape,bool)
            selected[key]=mask&~occupied;occupied|=mask
        labels=encode_labels(selected) if selected else None
        if labels:
            h,w=next(iter(selected.values())).shape;labels.update(width=w,height=h)
        return labels
    def inspect(self,identity,frame,progress=None,cancelled=None,check_id=None):
        r=self.get(identity);self.acquire(r);slot=False
        def checkpoint():
            if r.closed or (cancelled is not None and cancelled()):raise InspectionCancelled()
        try:
            checkpoint()
            if progress is None:
                if not self.vlm_slot.acquire(False):raise HTTPException(429,'另一项AI检查正在运行，请稍后重试。')
            else:
                while not self.vlm_slot.acquire(timeout=.1):checkpoint()
            slot=True;checkpoint();image=self.image(frame);self._accept_frame(r,frame);previous_check=r.check_id;reinspection=bool(previous_check);checkpoint()
            check=check_id or 'check_'+uuid.uuid4().hex[:16];r.check_id=check;folder=r.log.path/check;folder.mkdir();(folder/'input.jpg').write_bytes(image)
            prompt=ResourceStore.configured(self.config).path('task.plate_surface.prompt').read_text();(folder/'prompt.txt').write_text(prompt);dump(folder/'schema.json',Observation.model_json_schema())
            dump(folder/'request.json',{'ruleset':VERSION,'thresholds':self.config['inspection'],'frame_id':frame.client_frame_id,'source_sha256':frame.source_sha256,'image_count':1,'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'model':self.config['vlm']['model']})
            r.log.event('vlm.start',{'check_id':check,'frame_id':frame.client_frame_id,'source_sha256':frame.source_sha256})
            started=perf_counter();obs=None;usable_semantics=None;correction=''
            token=audit_context.set({'attempt':0,'folder':folder,'log':r.log})
            try:
                for attempt in range(2):
                    checkpoint()
                    raw=self.client.chat_structured(prompt=prompt+(correction or '严格使用Schema，修正上一条格式错误，重新判断当前图像。' if attempt else ''),schema=Observation.model_json_schema(),images_base64=[base64.b64encode(image).decode()],max_tokens=3000)
                    checkpoint()
                    text=json.dumps(raw,ensure_ascii=False);key=self.config['vlm']['api_key']
                    if key:text=text.replace(key,'[REDACTED]')
                    (folder/f'vlm_raw_{attempt+1}.json').write_text(text)
                    try:
                        normalized,repairs=normalize_observation(raw)
                        if repairs:
                            dump(folder/f'normalization_{attempt+1}.json',repairs)
                            r.log.event('vlm.normalized',{'check_id':check,'repairs':repairs})
                        obs=Observation.model_validate(normalized)
                        conflicts=plate_point_conflicts(obs)
                        if conflicts:
                            dump(folder/f'prompt_conflict_{attempt+1}.json',{'plate_point':obs.plate.target_point_0_1000,'overlapping_anomaly_boxes':conflicts})
                            if attempt==0:
                                usable_semantics=obs;correction='上一结果的打印板前景点落在异物框内：'+json.dumps(conflicts)+'。请重新观察同一张照片，将plate.target_point_0_1000放在明确裸露的打印板材质上，避开全部异物框；打印板框仍包含整块板。返回完整JSON。';continue
                        break
                    except ValidationError as error:
                        fields=[{'field':list(e['loc']),'type':e['type']} for e in error.errors(include_input=False,include_context=False)]
                        dump(folder/f'format_error_{attempt+1}.json',fields)
                        correction='上一回复未通过字段或几何校验：'+json.dumps(fields,ensure_ascii=False)+'。字段名称必须逐字使用bbox_0_1000和target_point_0_1000；只根据当前照片返回完整JSON，不要猜测未知坐标。'
                        r.log.event('vlm.validation_error',{'check_id':check,'attempt':attempt+1,'fields':fields})
                if obs is None:raise VisionError('Invalid VLM response after schema validation',code='invalid_response')
            except InspectionCancelled:raise
            except Exception as error:
                if usable_semantics is not None:
                    obs=usable_semantics;r.log.event('vlm.prompt_repair_failed',{'check_id':check,'error_type':type(error).__name__,'semantic_observation_preserved':True})
                else:
                    self._reset(r);r.objects=[]
                    code=getattr(error,'code','invalid_response')
                    r.decision={'status':'service_unavailable','message':'本次检查未完成，请重试。','scope':'本次照片','checked_at':now(),'reasons':[type(error).__name__],'failure_code':code}
                    dump(folder/'decision.json',r.decision);r.log.event('vlm.error',{'check_id':check,'error_type':type(error).__name__,'failure_code':code})
                    return self._reply(r,frame,[],vlm_ms=round((perf_counter()-started)*1000,2),elapsed_ms=round((perf_counter()-started)*1000,2),stage='inspection',tracking_state='unavailable')
            finally:audit_context.reset(token)
            checkpoint();self.vlm_slot.release();slot=False
            vlm_ms=round((perf_counter()-started)*1000,2);dump(folder/'observation.json',obs.model_dump())
            r.log.event('vlm.complete',{'check_id':check,'elapsed_ms':vlm_ms,'candidates':len(obs.anomalies)})
            limits=self.config['inspection'];candidates=[];rows=[];unresolved=[];anomalies=[]
            def add(key,kind,region,label):
                row={'id':key,'kind':kind,'label':label,'found':region.found,'semantic_status':'located' if kind=='plate' else 'detected','confidence':region.confidence,'evidence':region.evidence,'bbox_0_1000':region.bbox_0_1000,'target_point_0_1000':region.target_point_0_1000,'tracking_ready':False,'segmentation_status':'not_started','reasons':[]}
                rows.append(row)
                if region.found and region.target_point_0_1000 is not None:
                    candidates.append(SimpleNamespace(component_id=key,found=True,confidence=region.confidence,bbox_0_1000=region.bbox_0_1000,target_point_0_1000=region.target_point_0_1000))
                else:row['segmentation_status']='not_located';row['reasons']=['vlm_point_unavailable' if region.found else 'vlm_not_found']
            add('build_plate','plate',obs.plate,'打印板')
            if plate_point_conflicts(obs):
                candidates.clear();rows[0].update(segmentation_status='prompt_ambiguous',reasons=['plate_point_overlaps_anomaly_box'])
                r.log.event('grounding.plate_point_rejected',{'check_id':check,'semantic_plate_found':obs.plate.found})
            for i,a in enumerate(obs.anomalies,1):
                if a.on_plate=='no':continue
                key=f'{a.kind}_{i}';add(key,a.kind,a,a.description)
                if not a.found or a.on_plate!='yes':
                    rows[-1]['semantic_status']='candidate';unresolved.append(a.description)
                else:anomalies.append(key)
            skip_segmentation=reinspection and not anomalies and not unresolved
            if not skip_segmentation:self._reset(r)
            if progress is not None and not skip_segmentation:
                # Early semantic feedback is not a completed clean verdict.
                # The same photograph and IDs are retained for the mask stage.
                r.decision={'status':'anomaly_detected' if anomalies and obs.plate.found else 'inspection_pending',
                    'message':'目标已定位，正在生成高亮。','scope':'本次检查照片，定位框待细化','checked_at':now(),
                    'semantic_anomaly_ids':anomalies,'unresolved':unresolved,'coverage':obs.coverage,
                    'clear_checks':{'plate_found':obs.plate.found,'plate_self_confidence_sufficient':obs.plate.confidence>=limits['clear_plate_confidence_min']}}
                early=self._reply(r,frame,rows,stage='localization',tracking_state='initializing',vlm_ms=vlm_ms,elapsed_ms=round((perf_counter()-started)*1000,2))
                early['public_result'].update(status='localizing',visual_state='initializing')
                for key in ('foreign_object_state','residue_state'):
                    if early['public_result'][key]!='fail':early['public_result'][key]='unknown'
                dump(folder/'localization.json',early);checkpoint();progress(early);checkpoint()
            masks={};reuse_ms=0
            if skip_segmentation:
                reuse_started=perf_counter();r.removed_ids.clear();r.scene_changed=False;r.resolution_signature=None;r.scene_watch.reset()
                for session,key in list(r.sessions.items()):
                    if key!='build_plate':r.tracker.close(session);r.sessions.pop(session,None)
                if r.source=='camera' and r.sessions and obs.plate.found:
                    try:
                        output=r.tracker.update_many(list(r.sessions),image);checkpoint()
                        for session,key in list(r.sessions.items()):
                            t=output[session];mask=self._mask(t,key,r.tracker)
                            valid=t.status=='tracking' and t.mask_quality_passed and t.quality>=limits['minimum_tracking_quality'] and not t.requires_redetection and mask is not None and mask.any() and not mask.all()
                            if valid:
                                h,w=mask.shape;a,b,c,d=obs.plate.bbox_0_1000
                                containment=float(mask[b*h//1000:d*h//1000,a*w//1000:c*w//1000].sum())/int(mask.sum())
                                valid=containment>=limits['mask_prompt_containment_min']
                            if valid:masks[key]=mask;rows[0].update(tracking_ready=True,segmentation_status='reused_tracking',bbox_0_1000=t.bbox_0_1000)
                            else:r.tracker.close(session);r.sessions.pop(session,None)
                    except InspectionCancelled:raise
                    except Exception as error:r.log.event('inspection.plate_reuse_error',{'check_id':check,'error_type':type(error).__name__})
                checkpoint()
                if not masks:self._reset(r);rows[0].update(segmentation_status='skipped_clean_recheck',tracking_ready=False)
                reuse_ms=round((perf_counter()-reuse_started)*1000,2)
                r.log.event('segmentation.skipped',{'check_id':check,'previous_check_id':previous_check,'reason':'reinspection_without_anomaly_or_candidate','plate_tracking_reused':bool(masks),'tracking_update_ms':reuse_ms})
            else:
                preparation=None;seg_started=perf_counter()
                try:r.tracker.prepare(image,candidates,folder,r.log,0)
                except Exception as error:preparation=type(error).__name__
                checkpoint()
                masks={};plate_envelope=None
                if obs.plate.polygon_0_1000:
                    with Image.open(io.BytesIO(image)) as im:w,h=im.size
                    polygon=np.array([[round(x/1000*w),round(y/1000*h)] for x,y in obs.plate.polygon_0_1000],np.int32)
                    if cv2.isContourConvex(polygon) and cv2.contourArea(polygon)>w*h*.005:
                        plate_envelope=np.zeros((h,w),np.uint8);cv2.fillPoly(plate_envelope,[polygon],1)
                for c in candidates:
                    checkpoint()
                    row=next(x for x in rows if x['id']==c.component_id);session=None
                    if preparation:
                        row.update(segmentation_status='service_error',reasons=[preparation])
                        r.log.event('segmentation.result',{'check_id':check,**row,'thresholds':limits})
                        continue
                    target=GuidanceTarget(expected_component_id='intro_'+c.component_id,target_point_0_1000=c.target_point_0_1000,
                        expected_area_ratio_min=0,expected_area_ratio_max=1)
                    mask_token=mask_context.set(folder)
                    try:
                        session,t=r.tracker.start(image,'intro_'+c.component_id,c.bbox_0_1000,target)
                        checkpoint()
                        mask=self._mask(t,c.component_id,r.tracker)
                        ready=t.status=='tracking' and t.mask_quality_passed and mask is not None
                        reasons=list(t.mask_quality_reasons);metrics={'area_ratio':t.mask_area_ratio,'quality':t.quality,'initial_prompt_containment':t.prompt_containment}
                        if row['kind']!='plate' and mask is not None and plate_envelope is not None:
                            containment=float(np.count_nonzero(mask&plate_envelope.astype(bool)))/max(1,int(mask.sum()));metrics['containment_in_plate_envelope']=containment
                            metrics['containment_scope']='diagnostic only; overhanging objects can be on the plate'
                        row.update(tracking_ready=bool(ready),segmentation_status='accepted' if ready else 'rejected',reasons=reasons,metrics=metrics)
                        if ready:
                            masks[c.component_id]=mask;r.sessions[session]=c.component_id
                            cv2.imwrite(str(folder/(c.component_id+'_mask.png')),mask.astype(np.uint8)*255)
                        else:r.tracker.close(session)
                    except InspectionCancelled:raise
                    except Exception as error:
                        if session:r.tracker.close(session)
                        row.update(segmentation_status='error',reasons=[type(error).__name__])
                    finally:mask_context.reset(mask_token)
                    r.log.event('segmentation.result',{'check_id':check,**row,'thresholds':limits})
            segmentation_ms=0 if skip_segmentation else round((perf_counter()-seg_started)*1000,2)
            checkpoint()
            plate_row=rows[0]
            clear_checks={
                'plate_found':obs.plate.found,
                'plate_self_confidence_sufficient':obs.plate.confidence>=limits['clear_plate_confidence_min'],
                'scene_self_confidence_sufficient':obs.confidence>=limits['clear_scene_confidence_min'],
                'full_surface_visible':obs.coverage=='full' and not obs.view_issues,
                'vlm_surface_clear':obs.surface_assessment=='clear',
                'no_confirmed_or_uncertain_anomaly':not anomalies and not unresolved,
                'plate_boundary_mask_usable':plate_row['tracking_ready'],
                'plate_localization_usable':plate_row['tracking_ready'] or (skip_segmentation and obs.plate.found),
            }
            if anomalies and obs.plate.found:
                status='anomaly_detected';message='发现板面异物或残料，请处理后重新检查。'
            elif not all(v for k,v in clear_checks.items() if k!='plate_boundary_mask_usable'):
                status='insufficient_evidence';message='当前画面或定位证据不足，暂不能判断板面状态。'
            else:status='no_visible_anomaly';message='本次照片未见明显异物或残料。'
            confirmable=(obs.view_issues==['toolhead_upper_left'] and obs.coverage in ('partial','full')
                and obs.visible_surface_assessment=='clear' and not anomalies and not unresolved
                and obs.surface_assessment in ('clear','uncertain')
                and all(clear_checks[k] for k in ('plate_found','plate_self_confidence_sufficient','scene_self_confidence_sufficient','plate_localization_usable')))
            r.decision={'status':status,'ruleset':VERSION,'message':message,'scope':'仅本次照片的可见表面，不表示可开始打印','checked_at':now(),'limitations':obs.limitations,'next_action':obs.next_action,'unresolved':unresolved,'semantic_anomaly_ids':anomalies,'coverage':obs.coverage,'clear_checks':clear_checks,'confidence_scope':'VLM self-report; not calibrated detection probability',
                'view_issues':obs.view_issues,'occlusion_confirmation_eligible':confirmable,'occlusion_confirmed':False,'inspection_source_sha256':frame.source_sha256,'segmentation_skipped':skip_segmentation}
            r.current_plate_usable=clear_checks['plate_localization_usable']
            r.objects=rows;labels=self._wire(rows,masks);r.scene_watch.prime(masks,rows)
            # Color visualization for evidence only; the frontend uses the compact ID texture.
            save_overlay(folder/'overlay.jpg',image,rows,masks);dump(folder/'objects.json',rows);dump(folder/'decision.json',r.decision)
            r.log.event('inspection.decision',{'check_id':check,**r.decision,'vlm_ms':vlm_ms,'segmentation_ms':segmentation_ms,'tracking_reuse_ms':reuse_ms,'segmentation_skipped':skip_segmentation,'elapsed_ms':round((perf_counter()-started)*1000,2)})
            reply=self._reply(r,frame,rows,labels,stage='inspection',vlm_ms=vlm_ms,segmentation_ms=segmentation_ms,segmentation_skipped=skip_segmentation,tracking_reuse_ms=reuse_ms,elapsed_ms=round((perf_counter()-started)*1000,2),tracking_state='tracking' if r.sessions else 'not_required' if skip_segmentation else 'unavailable')
            if skip_segmentation and not masks:reply['public_result']['visual_state']='not_required'
            return reply
        finally:
            if slot:self.vlm_slot.release()
            r.lock.release()
    def track(self,identity,frame):
        r=self.get(identity);self.acquire(r)
        try:
            if r.source!='camera':raise HTTPException(409,'静态图像不执行运动跟踪。')
            if frame.check_id!=r.check_id or not r.check_id:raise HTTPException(409,'检查版本已变化，请重新检查。')
            image=self.image(frame);self._accept_frame(r,frame);started=perf_counter();sessions=list(r.sessions);rows=[];masks={}
            try:output=r.tracker.update_many(sessions,image) if sessions else {}
            except Exception as error:
                r.log.event('tracking.error',{'check_id':r.check_id,'error_type':type(error).__name__})
                for session in sessions:r.tracker.close(session)
                r.sessions={};sessions=[];output={}
            for session in sessions:
                key=r.sessions[session];t=output[session];row=dict(next(x for x in r.objects if x['id']==key));mask=self._mask(t,key,r.tracker)
                ready=t.status=='tracking' and t.mask_quality_passed and t.quality>=self.config['inspection']['minimum_tracking_quality'] and mask is not None and not t.requires_redetection
                row.update(tracking_ready=bool(ready),tracking_state=t.tracking_state,retained_for_recovery=t.retained_for_recovery,reasons=list(t.mask_quality_reasons),bbox_0_1000=t.bbox_0_1000)
                row['tracking_metrics']={'mask_area_ratio':t.mask_area_ratio,'tracking_quality':t.quality,'prompt_or_motion_containment':t.prompt_containment,'motion_diagnostics':getattr(t,'motion_diagnostics',{}),'quality_scope':'engine motion/appearance or mask validity; not semantic confidence'}
                if ready and (not mask.any() or mask.all()):
                    ready=False;row['tracking_ready']=False;row['reasons'].append('current_mask_has_no_boundary_evidence')
                if ready:masks[key]=mask
                elif not t.retained_for_recovery:r.tracker.close(session);r.sessions.pop(session,None)
                rows.append(row)
            # Preserve non-trackable findings as semantics, without reusing their old masks/boxes on new frames.
            current={x['id'] for x in rows}
            rows.extend({**o,'tracking_ready':False,'tracking_state':'lost','retained_for_recovery':False,'bbox_0_1000':None} for o in r.objects if o['id'] not in current)
            scope_changed=update_scope(rows,masks,r.removed_ids)
            recovering=any(o.get('retained_for_recovery') and o['id'] not in r.removed_ids for o in rows)
            state='needs_reinspection' if not r.sessions else 'recovering' if not masks and recovering else 'partial' if len(masks)<sum(key not in r.removed_ids for key in r.sessions.values()) else 'tracking'
            proposals=r.scene_watch.update(masks)
            r.current_plate_usable='build_plate' in masks
            if proposals and not r.scene_changed:
                r.scene_changed=True;r.log.event('inspection.scene_changed',{'check_id':r.check_id,'client_frame_id':frame.client_frame_id,'source_sha256':frame.source_sha256,'proposals':proposals})
            decision=scope_decision(r.decision,r.removed_ids,r.current_plate_usable)
            reply=self._reply(r,frame,rows,self._wire(rows,masks),decision=decision,stage='tracking',tracking_state=state,scene_candidates=proposals,elapsed_ms=round((perf_counter()-started)*1000,2))
            if not r.current_plate_usable:
                was_pending=reply['public_result']['requires_occlusion_confirmation']
                reply['public_result']['requires_occlusion_confirmation']=False
                if was_pending:reply['public_result'].update(status='recheck_required',recheck_reason='position_unavailable',foreign_object_state='unknown',residue_state='unknown')
            if r.scene_changed or (r.decision.get('occlusion_confirmed') and not r.current_plate_usable):
                reply['public_result']['requires_occlusion_confirmation']=False
                if not proposals and (r.decision.get('occlusion_confirmed') or reply['public_result']['status'] in ('no_visible_anomaly','known_anomalies_removed')):
                    reply['public_result'].update(status='recheck_required',recheck_reason='scene_changed',foreign_object_state='unknown',residue_state='unknown',occlusion_confirmed=False)
            # Only a positive current-frame out-of-plate box proves removal;
            # tracking loss cannot create that evidence. Keep the VLM snapshot.
            signature=(tuple(sorted(r.removed_ids)),reply['public_result']['status'],reply['public_result']['foreign_object_state'],reply['public_result']['residue_state'])
            if scope_changed or proposals or (r.resolution_signature is not None and signature!=r.resolution_signature):
                r.resolution_signature=signature
                proof={'at':now(),'check_id':r.check_id,'client_frame_id':frame.client_frame_id,'source_sha256':frame.source_sha256,'removed_anomaly_ids':sorted(r.removed_ids),'decision':decision,'objects':rows,'public_result':reply['public_result'],'scene_candidates':proposals}
                dump(r.log.path/r.check_id/'resolution.json',proof)
                (r.log.path/r.check_id/'resolution_input.jpg').write_bytes(image)
                save_overlay(r.log.path/r.check_id/'resolution_overlay.jpg',image,rows,masks)
                r.log.event('inspection.plate_scope_changed',proof)
            r.log.event('tracking.frame',{'client_frame_id':frame.client_frame_id,'source_sha256':frame.source_sha256,'check_id':r.check_id,'tracking_state':reply['tracking_state'],'scene_candidates':proposals,'elapsed_ms':reply['elapsed_ms'],'public_result':reply['public_result'],'objects':rows,'engine_metrics':getattr(r.tracker.local,'last_batch_metrics',{})})
            if monotonic()-r.last_sample>=self.config['inspection']['tracking_sample_seconds'] and r.samples<self.config['inspection']['max_tracking_samples']:
                r.last_sample=monotonic();r.samples+=1;folder=r.log.path/'tracking'/f'{r.samples:05d}';folder.mkdir(parents=True);(folder/'input.jpg').write_bytes(image);dump(folder/'reply.json',reply)
            return reply
        finally:r.lock.release()
    def confirm_occlusion(self,identity,request):
        r=self.get(identity);self.acquire(r)
        try:
            d=r.decision
            if request.check_id!=r.check_id or request.inspection_source_sha256!=d.get('inspection_source_sha256'):raise HTTPException(409,'检查照片已更新，请重新确认。')
            if not d.get('occlusion_confirmation_eligible') or r.scene_changed or not r.current_plate_usable:raise HTTPException(409,'当前检查不满足人工确认条件，请重新检查。')
            d.update(status='no_visible_anomaly',occlusion_confirmed=True,
                scope='可见板面视觉检查与用户对打印头左上角遮挡区域的人工确认，仅对应本次检查。',
                manual_confirmation={'at':now(),'type':'toolhead_upper_left','inspection_source_sha256':request.inspection_source_sha256})
            dump(r.log.path/r.check_id/'decision.json',d);r.log.event('inspection.occlusion_confirmed',{'check_id':r.check_id,**d['manual_confirmation']})
            return {'check_id':r.check_id,'inspection_source_sha256':request.inspection_source_sha256,'decision':d,'public_result':public_result(d,r.objects)}
        finally:r.lock.release()
    def close(self,identity):
        r=self.get(identity);self.acquire(r)
        try:r.closed=True;r.tracker.shutdown();r.log.event('run.closed',{});self.runs.pop(identity,None)
        finally:r.lock.release()
