"""Instance-scoped VLM grounding and mask initialization, preserving the V1 algorithm."""
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
import base64,hashlib,io,json,threading,uuid
import cv2
from fastapi import HTTPException
from pydantic import BaseModel,Field,model_validator
from PIL import Image,ImageOps
from manual2ar_contracts.perception import ComponentBox,GuidanceTarget
from manual2ar.integrations.vlm.audit import AuditedVision,context
from manual2ar_perception.segmentation import mask_context
from manual2ar.infrastructure.diagnostics import RunLog,dump,metadata,draw_boxes,save_masks
from manual2ar.resources import ResourceStore

class ImageRequest(BaseModel):
    image_base64: str = Field(min_length=32,max_length=16000000)

class LocateRequest(ImageRequest):
    component_ids: list[str] = Field(default_factory=list,max_length=8)
    @model_validator(mode='after')
    def validate_ids(self):
        if len(set(self.component_ids)) != len(self.component_ids):
            raise ValueError('Use unique ids from the component catalog')
        return self

class Candidate(BaseModel):
    component_id: str
    found: bool
    bbox_0_1000: list[int] | None = None
    target_point_0_1000: list[int] | None = None
    confidence: float = Field(ge=0,le=1)
    visible_evidence: str = ''
    @model_validator(mode='after')
    def geometry(self):
        if self.found:
            ComponentBox(component_id=self.component_id,bbox_0_1000=self.bbox_0_1000)
            p = self.target_point_0_1000
            if not p or len(p)!=2 or any(v<0 or v>1000 for v in p): raise ValueError('Invalid foreground point')
            b = self.bbox_0_1000
            if not (b[0]<=p[0]<=b[2] and b[1]<=p[1]<=b[3]): raise ValueError('Point outside object box')
        return self

class Batch(BaseModel):
    components: list[Candidate] = Field(max_length=8)

class FrontendEvent(BaseModel):
    event: str = Field(pattern=r'^(frontend.render|frontend.select|camera.ready|camera.stop|frontend.save|frontend.clear)$')
    data: dict = Field(default_factory=dict)

class Capture(ImageRequest):
    pass

def create_pipeline(config,client=None):
    from .manage import public
    resources=ResourceStore.configured(config)
    catalog=resources.json('device.components')
    by_id={c['id']:c for c in catalog}
    vision=client or AuditedVision(config['vlm'])
    runs={}
    registry_lock=threading.RLock()
    locate_slot=threading.BoundedSemaphore(1)
    class Run:
        def __init__(self, log_root=None, tracker_instance=None):
            self.tracker = tracker_instance
            self.log = RunLog(log_root if log_root is not None else Path(config['runtime_dir'])/'learning',{'logging':config['logging'],'public':public(config)},
                [resources.path('device.components'),resources.path('task.component_recognition.prompt'),Path(__file__)])
            self.closed = False
            self.sessions = {}
            self.lock = threading.RLock()
            self.last_sample = 0.
            self.frame = 0
            self.check = None

    def get_run(run):
        with registry_lock: value = runs.get(run)
        if value is None: raise HTTPException(404,'Run is closed or unknown; start a new run')
        return value

    def close_sessions(value):
        for session in list(value.sessions):
            try: value.tracker.close(session)
            except Exception: value.log.event('session.close_error',{'error':'provider close failed'})
        value.sessions.clear()

    def image_bytes(request):
        try:
            data = base64.b64decode(request.image_base64,validate=True)
            with Image.open(io.BytesIO(data)) as source:
                if source.width*source.height > 25000000: raise ValueError('Image too large')
                image = source.convert('RGB')
                image.thumbnail((1280,1280))
                buf = io.BytesIO(); image.save(buf,format='JPEG',quality=92)
                return buf.getvalue()
        except Exception: raise HTTPException(400,'Invalid or oversized image')

    def good(t, minimum=.5):
        return t.status=='tracking' and t.mask_quality_passed and not t.requires_redetection and t.quality>=minimum and bool(t.overlay_png_base64)

    def wire(payload):
        # Unity's inherited DTO cannot deserialize nested polygon arrays. This UI renders PNG masks.
        return {**payload,'results':[{**row,'tracked':row['tracked'].model_dump(exclude={'polygon_0_1000'})
            if row.get('tracked') else None} for row in payload['results']]}

    def end(run:str):
        with registry_lock: value = runs.pop(run,None)
        if value:
            with value.lock:
                value.closed=True
                close_sessions(value); value.log.event('run.stop',{}); value.log.report()

    def clear(run:str):
        value=get_run(run)
        with value.lock:
            close_sessions(value); value.log.event('frontend.clear',{})

    def locate(run:str,request:LocateRequest):
        if not request.component_ids: request.component_ids=list(by_id)
        if any(i not in by_id for i in request.component_ids): raise HTTPException(422,'Unknown component identity')
        value=get_run(run)
        active_tracker=value.tracker
        image=image_bytes(request)
        if not locate_slot.acquire(blocking=False): raise HTTPException(429,'Another localization is running')
        try:
            with value.lock:
                if value.closed: raise HTTPException(409,'Run closed')
                close_sessions(value)
                check='locate_'+uuid.uuid4().hex[:12]
                value.check=check
                folder=value.log.path/check; folder.mkdir()
                (folder/'input.jpg').write_bytes(image)
                original=base64.b64decode(request.image_base64)
                (folder/('source.png' if original.startswith(b'\x89PNG') else 'source.jpg')).write_bytes(original)
                prompt=resources.path('task.component_recognition.prompt').read_text()+'\nCOMPONENT DEFINITIONS:\n'+json.dumps([by_id[i] for i in request.component_ids],ensure_ascii=False)
                (folder/'prompt.txt').write_text(prompt,encoding='utf-8')
                schema=Batch.model_json_schema()
                schema['$defs']['Candidate']['properties']['component_id']['enum']=request.component_ids
                dump(folder/'schema.json',schema)
                value.log.event('vlm.start',{'check_id':check,'sha256':hashlib.sha256(image).hexdigest(),'requested':request.component_ids})
                started=perf_counter()
                token=context.set({'attempt':0,'folder':folder,'log':value.log})
                try:
                    raw=vision.chat_structured(prompt=prompt,schema=schema,images_base64=[base64.b64encode(image).decode()],max_tokens=3600)
                    dump(folder/'vlm_raw.json',raw)
                    records=raw.get('components')
                    if not isinstance(records,list) or len(records)>8: raise ValueError('Invalid component list')
                    ids=[c.get('component_id') for c in records]
                    if len(ids)!=len(set(ids)) or any(i not in request.component_ids for i in ids): raise ValueError('Duplicate or unexpected component id')
                    candidates=[]; invalid={}
                    for record in records:
                        try: candidates.append(Candidate.model_validate(record))
                        except Exception: invalid[record['component_id']]='Invalid VLM geometry or fields'
                except Exception as error:
                    # Vendor exception bodies may include sensitive text; store only class.
                    value.log.event('vlm.error',{'check_id':check,'error_type':type(error).__name__,'elapsed_ms':round((perf_counter()-started)*1000,1)})
                    dump(folder/'summary.json',{'stage':'vlm','error_type':type(error).__name__})
                    value.log.report()
                    raise HTTPException(502,'VLM failed or returned invalid geometry; see run log')
                finally:
                    context.reset(token)
                vlm_ms=round((perf_counter()-started)*1000,1)
                if value.closed:raise HTTPException(409,'会话已结束。')
                value.log.event('vlm.complete',{'check_id':check,'elapsed_ms':vlm_ms,'returned':len(candidates)})
                cv2.imwrite(str(folder/'boxes.jpg'),draw_boxes(image,candidates))
                preparation_error=None
                if hasattr(active_tracker,'prepare'):
                    try:
                        active_tracker.prepare(image,candidates,folder,value.log,config['minimum_confidence'])
                    except Exception as error:
                        preparation_error=type(error).__name__
                        value.log.event('segmentation.prepare_error',{'check_id':check,'error_type':preparation_error})
                if preparation_error and getattr(value,'automatic_provider',False) and active_tracker.provider=='sam31_cutie':
                    from manual2ar.integrations.perception.provider import LearningTracker
                    active_tracker.shutdown()
                    active_tracker=LearningTracker('opencv',config);value.tracker=active_tracker
                    value.provider_fallback=True
                    value.log.event('provider.fallback',{'stage':'initialize','from':'sam31_cutie','to':'opencv','reason':preparation_error})
                    active_tracker.prepare(image,candidates,folder,value.log,config['minimum_confidence'])
                    preparation_error=None
                found={c.component_id:c for c in candidates}; rows=[]
                if value.closed:
                    active_tracker.shutdown()
                    raise HTTPException(409,'会话已结束。')
                for identity in request.component_ids:
                    c=found.get(identity); spec=by_id[identity]
                    row={'component_id':identity,'english_label':spec['label'],'found':bool(c and c.found),
                         'candidate':c.model_dump() if c else None,'tracking_ready':False,'session_id':None,'tracked':None,'error':None}
                    if not c or not c.found:
                        row['stage']='vlm_invalid_geometry' if identity in invalid else 'vlm_not_located'
                        row['error']=invalid.get(identity) or (c.visible_evidence if c else 'VLM omitted component')
                    elif c.confidence<config['minimum_confidence']:
                        row['stage']='vlm_low_confidence'; row['error']='confidence below threshold'
                    elif preparation_error:
                        row['stage']='segmentation_error'; row['error']='Segmentation service: '+preparation_error
                    else:
                        t0=perf_counter(); session=None
                        target=GuidanceTarget(expected_component_id='intro_'+identity,target_point_0_1000=c.target_point_0_1000,
                            expected_area_ratio_min=spec['min_area'],expected_area_ratio_max=spec['max_area'])
                        mask_token=mask_context.set(folder)
                        try:
                            session,t=active_tracker.start(image,'intro_'+identity,c.bbox_0_1000,target)
                            row['tracked']=t; row['tracking_ready']=good(t)
                            row['stage']='accepted' if row['tracking_ready'] else 'segmentation_rejected'
                            if row['tracking_ready']:
                                row['session_id']=session; value.sessions[session]=identity
                            else:
                                active_tracker.close(session); row['error']=';'.join(t.mask_quality_reasons) or 'initial mask quality failed'
                        except Exception as error:
                            if session:
                                try: active_tracker.close(session)
                                except Exception: pass
                            row['stage']='segmentation_error'; row['error']=type(error).__name__
                        finally:
                            mask_context.reset(mask_token)
                        row['segmentation_ms']=round((perf_counter()-t0)*1000,1)
                    audit={k:v for k,v in row.items() if k!='tracked'}
                    audit['thresholds']={'confidence_min':config['minimum_confidence'],'area_min':spec['min_area'],'area_max':spec['max_area'],'quality_min':.5}
                    audit['mask']=metadata(row['tracked']) if row['tracked'] else None
                    value.log.event('segmentation.result',{'check_id':check,**audit})
                    dump(folder/(identity+'.json'),audit)
                    rows.append(row)
                # Detect nearly identical masks assigned to different component identities.
                overlap_rows=[]
                for index,a in enumerate(rows):
                    if not a['tracking_ready']: continue
                    for b in rows[index+1:]:
                        if not b['tracking_ready']: continue
                        def binary(row):
                            import numpy as np
                            mask=cv2.imdecode(np.frombuffer(base64.b64decode(row['tracked'].overlay_png_base64),np.uint8),cv2.IMREAD_UNCHANGED)
                            if mask is None: return None
                            return mask[:,:,3]>0 if mask.ndim==3 and mask.shape[2]==4 else (mask.max(axis=2)>0 if mask.ndim==3 else mask>0)
                        ma,mb=binary(a),binary(b)
                        if ma is None or mb is None or ma.shape!=mb.shape: continue
                        iou=float((ma&mb).sum()/max(1,(ma|mb).sum()))
                        overlap_rows.append({'first':a['component_id'],'second':b['component_id'],'mask_iou':round(iou,4)})
                        if iou>config['maximum_mask_iou']:
                            loser=min((a,b),key=lambda row:row['candidate']['confidence'])
                            active_tracker.close(loser['session_id']); value.sessions.pop(loser['session_id'],None)
                            loser.update(tracking_ready=False,session_id=None,stage='segmentation_duplicate',error='Mask duplicates another component')
                            value.log.event('segmentation.duplicate',{'check_id':check,'component_id':loser['component_id'],'mask_iou':iou})
                            if loser is a: break
                dump(folder/'mask_overlap.json',{'maximum_mask_iou':config['maximum_mask_iou'],'pairs':overlap_rows})
                save_masks(folder,image,rows)
                payload={'run_id':run,'check_id':check,'frame_id':0,'results':rows,'provider':vision.provider,'model':vision.model,'vlm_ms':vlm_ms,
                         'elapsed_ms':round((perf_counter()-started)*1000,1)}
                dump(folder/'summary.json',{**{k:v for k,v in payload.items() if k!='results'},'results':[
                    {k:(metadata(v) if k=='tracked' and v else v) for k,v in row.items()} for row in rows]})
                value.log.report()
                return wire(payload)
        finally: locate_slot.release()
    return SimpleNamespace(**locals(),ImageRequest=ImageRequest,LocateRequest=LocateRequest)
