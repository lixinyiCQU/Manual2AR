"""Session orchestration for desktop AR. Persistent metric authoring is explicit.

No inferred factory geometry and no writes to procedure progress. Frame results
refer to exactly one submitted JPEG; the client displays that matching image.
"""
import base64
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import io
import json
from pathlib import Path
import threading
import time
import uuid
import cv2
import numpy as np
from fastapi import HTTPException
from PIL import Image
from manual2ar.resources import ResourceStore
from manual2ar_perception.spatial import detect_pose, guide_lines, project, triangulate
from .printing import MARKER_ID, MARKER_LENGTH, PATTERN, SQUARE
from .visuals import compose


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


@dataclass
class Session:
    identity: str
    camera: str
    rig: str
    mode: str
    reuse: bool
    calibration: dict | None
    targets: dict
    context: dict = field(default_factory=dict)
    automatic_views:dict=field(default_factory=dict)
    automatic_candidate:dict|None=None
    locating:bool=False
    orientations:dict=field(default_factory=dict)
    u7_checks:dict=field(default_factory=dict)
    machine_frame:dict|None=None
    machine_candidates:dict=field(default_factory=dict)
    motion_parameters:dict=field(default_factory=dict)
    lock: object = field(default_factory=threading.RLock)
    frames: OrderedDict = field(default_factory=OrderedDict)
    samples: list = field(default_factory=list)
    candidates: dict = field(default_factory=dict)
    pinned: list = field(default_factory=list)
    event_ids: OrderedDict = field(default_factory=OrderedDict)
    authorized:set=field(default_factory=set)
    invalidated:dict=field(default_factory=dict)
    last: int = 0
    touched: float = field(default_factory=time.monotonic)
    size: tuple | None = None
    closed: bool = False


class SpatialService:
    def __init__(self, config, registry, client, experience=None):
        self.experience = experience
        self.config, self.registry, self.client = config, registry, client
        self.store = ResourceStore.configured(config)
        from manual2ar.visuals.library import VisualAssetLibrary
        self.asset_library=VisualAssetLibrary(self.store.path('visual.guidance.catalog'))
        self.plan = experience.catalog() if experience else self.store.json('task.unboxing.spatial')
        self.actions = {a['action_id']: a for a in self.plan['actions']}
        from .display import DisplayCatalog
        self.displays=DisplayCatalog(self.store.path('task.unboxing.spatial').parent/'display.json',self.asset_library,self.actions)
        self.root = Path(config['runtime_dir']) / 'guidance-spatial'
        self.sessions = {}; self.lock = threading.RLock();self.profile_lock=threading.RLock();self.rig_validity={}
        reference_root=self.store.path("task.unboxing.spatial").parent/"vision"
        manifest=json.loads((reference_root/"references.json").read_text())["references"]
        self.references={}
        for key,value in manifest.items():
            raw=(reference_root/value["file"]).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=value["sha256"]:raise ValueError("U7 reference hash mismatch")
            self.references[key]=raw
        from .part_tracking import PartTracking
        self.part_tracking=PartTracking(config,client,self.references,self.part_event)
        from .machine import MachineGuidance
        self.machine=MachineGuidance(self)
        from .automatic import AutomaticGuidance
        self.automatic=AutomaticGuidance(self)

    def catalog(self):
        return {**self.plan, 'visual_revision':'mesh-loop-v2', 'marker_id': MARKER_ID, 'marker_length_m': MARKER_LENGTH,
                'asset_library':self.asset_library.descriptor(),'display_profiles':self.displays.bundle(),'required_client_revision':'machine-workframe-v1',
                'print_url': '/api/guidance/spatial/print.pdf', 'calibration_minimum_views': 12,
                'automatic_configuration':True,
                'profile_note': '标记与打印机必须保持刚性固定；移动标记或打印机可动部件后请重新设置作用点。'}

    def capabilities(self):
        return {'schema_version':'manual2ar-spatial-capabilities-v1',
                'capture_contract':'manual2ar-capture-v1','visual_contract':'manual2ar-spatial-visual-v1',
                'active_providers':['desktop_rgb','synthetic'],'reserved_providers':['arkit'],
                'native_ar_available':False,'depth_required':False,
                'asset_presentation_contract':'manual2ar-visual-presentation-v1',
                'machine_frame_contract':'manual2ar-machine-frame-v1',
                'motion_contract':'manual2ar-teaching-motion-v1',
                'machine_control_available':False,
                'placement_method':'printed_reference_and_vlm_two_view_or_manual_authoring',
                'render_identity':'client_frame_id + source_sha256; upright_unmirrored pixels',
                'coordinate_convention':self.plan['coordinate_convention']}

    def profile(self, name, identity):return self.root / 'profiles' / name / (identity + '.json')

    @staticmethod
    def store_profile(path,value):atomic_json(path,value)

    def begin(self, command):
        if command.mode=="camera" and command.visual_client_revision!="machine-workframe-v1":raise HTTPException(409,"当前前端是旧版本，请使用资产库演示目录中的启动教学系统.cmd。")
        context = self.experience.context(command.tutorial_run_id) if command.tutorial_run_id and self.experience else {}
        with self.lock:expired=[k for k,s in self.sessions.items() if time.monotonic()-s.touched>1200]
        for identity in expired:self.close(identity)
        with self.lock:
            if len(self.sessions) >= 4:raise HTTPException(429, '请先关闭未使用的空间指导页面。')
            identity = uuid.uuid4().hex
            def read(path):return json.loads(path.read_text()) if path.is_file() else None
            calibration = read(self.profile('cameras', command.camera_id))
            targets = read(self.profile('rigs', command.rig_id)) or {}
            if command.mode == 'replay':
                from .simulation import calibration as replay_calibration, targets as replay_targets
                calibration, targets = replay_calibration(), replay_targets(self.actions)
            session = Session(identity, command.camera_id, command.rig_id, command.mode,
                              command.reuse_targets or command.mode == 'replay', calibration, targets)
            session.orientations=read(self.profile('orientations',command.rig_id)) or {}
            machine=self.machine.load(command.rig_id) if command.mode!='replay' else None
            session.saved_machine=machine
            session.machine_frame=machine if session.reuse else None
            from manual2ar_contracts.machine_frame import MotionParameters
            session.motion_parameters={k:MotionParameters.model_validate(v).model_dump() for k,v in (read(self.profile('motions',command.rig_id)) or {}).items()}
            session.context = context
            session.authorized=set(targets) if session.reuse else set()
            if command.mode!='replay':
                with self.profile_lock:
                    if command.rig_id not in self.rig_validity:self.rig_validity[command.rig_id]=read(self.profile('rig-validity',command.rig_id)) or {}
                    session.invalidated=self.rig_validity[command.rig_id]
            self.sessions[identity] = session
            self.event(session, 'session.begin', {'mode': command.mode, 'reuse_targets': session.reuse,'client_visual_revision':command.visual_client_revision})
            return {'session_id': identity, 'calibrated': calibration is not None, 'mode': command.mode,
                    'has_saved_targets': bool(targets) or bool(machine),'has_saved_machine_frame':bool(machine),'u7_sequence':self.u7_progress(session), 'target_reuse_confirmed': session.reuse, 'tutorial_context': context}

    def reuse_saved(self,identity):
        with self.session(identity) as session:
            frame=session.frames.get(session.last)
            if session.mode!='camera' or not session.calibration or not frame or not frame['pose'] or time.monotonic()-frame['at']>5:
                raise HTTPException(409,'请让固定定位标记清晰入镜，再确认开始。')
            if not session.targets:raise HTTPException(409,'没有作用点缓存，请先配置空间锚点。')
            session.authorized=set(session.targets);session.reuse=True
            session.machine_frame=self.machine.load(session.rig)
            self.event(session,'preflight.confirmed',{'client_frame_id':session.last,'source_sha256':frame['sha256'],'machine_frame_id':(session.machine_frame or {}).get('frame_id','')})
            return {'status':'ready','machine_frame':session.machine_frame}

    @contextmanager
    def session(self, identity):
        with self.lock:
            s = self.sessions.get(identity)
            if s is None:raise HTTPException(404, '空间指导已关闭，请重新打开。')
        with s.lock:
            if s.closed:raise HTTPException(409, '空间指导已关闭。')
            if s.context:self.experience.context(s.context['tutorial_run_id'])
            s.touched = time.monotonic()
            yield s

    def event(self, s, name, data):
        folder=self.root/'runs'/s.identity;folder.mkdir(parents=True,exist_ok=True)
        with (folder/'events.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps({'event':name,'time':time.time(),'visual_revision':'mesh-loop-v2',**s.context,**data},ensure_ascii=False)+'\n')

    def close(self, identity):
        self.part_tracking.cancel(identity)
        with self.lock:s=self.sessions.pop(identity,None)
        if s:
            with s.lock:
                s.closed=True;s.frames.clear();s.samples.clear();s.candidates.clear();s.machine_candidates.clear()
                self.event(s,'session.close',{})

    def action(self, identity):
        if identity not in self.actions:raise HTTPException(422,'请选择当前目录支持的开箱指导动作。')
        return self.actions[identity]

    def target(self,action_id,target_id):
        action=self.action(action_id)
        instance=next((t for t in action['target_instances'] if t['id']==target_id),None)
        if instance is None:raise HTTPException(422,'当前动作没有这个操作位置。')
        # Preserve every previously authored V1 primary target without rewriting its file.
        key=action_id if target_id=='main' else action_id+'::'+target_id
        return action,instance,key

    def frame(self, identity, request):
        action,instance,key=self.target(request.action_id,request.target_id);started=time.perf_counter()
        try:
            raw=base64.b64decode(request.image_base64,validate=True)
            if hashlib.sha256(raw).hexdigest()!=request.source_sha256:raise HTTPException(409,'图像校验失败，请重新取景。')
            with Image.open(io.BytesIO(raw)) as image:
                if image.format!='JPEG' or not 160<=image.width<=1280 or not 160<=image.height<=1280:
                    raise ValueError('JPEG sides must be between 160 and 1280')
                image.load();pixels=np.asarray(image.convert('RGB'))[:,:,::-1].copy()
        except HTTPException:raise
        except Exception:raise HTTPException(422,'图像无效，请使用摄像头原始拍摄画面。') from None
        h,w=pixels.shape[:2]
        with self.session(identity) as s:
            self.require_u7(s,action['action_id'])
            snapshot=request.snapshot
            if snapshot:
                if snapshot.provider_id!=('synthetic' if s.mode=='replay' else 'desktop_rgb'):
                    raise HTTPException(422,'当前服务支持 Windows 有标记指导；原生 AR 提供方尚未启用。')
                if (snapshot.client_frame_id,snapshot.source_sha256,snapshot.width,snapshot.height)!=(request.client_frame_id,request.source_sha256,w,h):
                    raise HTTPException(409,'空间快照与拍摄图像不匹配，已拒绝显示。')
            if request.client_frame_id<=s.last:raise HTTPException(409,'过期帧已丢弃。')
            if s.size and s.size!=(w,h):raise HTTPException(409,'画幅已变化，请重新启动空间指导并标定当前画幅。')
            s.size=(w,h);s.last=request.client_frame_id
            target=s.targets.get(key) if key in s.authorized and key not in s.invalidated else None
            if action['action_id']=='holder.slide' and not target and key not in s.targets:
                target=self.automatic.slide_reference(s)
            motion=self.machine.motion(s,action)
            result={'session_id':identity,'action_id':action['action_id'],'client_frame_id':s.last,
                    'target_id':request.target_id,'target_label':instance['label'],
                    'source_sha256':request.source_sha256,'width':w,'height':h,'lines':[],
                    'state':'camera_calibration_required','sample_count':len(s.samples),'pose':None,
                    'placement_method':(target or {}).get('placement_method','manual_two_view' if target else ''),'placement_note':(target or {}).get('placement_note',''),
                    'target_ready':False,'target_configured':bool(target) or (key in s.invalidated and key in s.targets),
                    'requires_relocation':key in s.invalidated,'calibrated':False,'visual':None,'companion_visuals':[],
                    'machine_frame':s.machine_frame,'motion_parameters':motion,'machine_axes':[],'u7_sequence':self.u7_progress(s)}
            if request.calibration_sample:
                self.add_sample(s,pixels);result['sample_count']=len(s.samples)
            calibration=s.calibration
            pose=None
            if calibration:
                if calibration['width']!=w or calibration['height']!=h:
                    result['state']='calibration_resolution_mismatch'
                else:
                    result['calibrated']=True
                    result['orientation']=s.orientations.get(key,{'rotation_degrees':[0,0,0],'rotation_sign':1})
                    matrix,distortion=np.array(calibration['matrix']),np.array(calibration['distortion'])
                    pose,status=detect_pose(pixels,matrix,distortion)
                    result['state']=status
                    if pose:
                        from .orientation import axes
                        result['reference_axes']=axes(np.zeros(3),np.eye(3),pose['transform'],matrix,distortion,.035)
                        if s.machine_frame:
                            transform=np.array(s.machine_frame['marker_from_machine']).reshape(4,4)
                            try:result['machine_axes']=axes(transform[:3,3],transform[:3,:3],pose['transform'],matrix,distortion,.05)
                            except ValueError:pass
                        result['pose']={'matrix':pose['transform'].flatten().tolist(),
                            'reprojection_px':pose['reprojection_px'],
                            'corners':[{'x':float(p[0]),'y':float(p[1])} for p in pose['corners']]}
                        if target and target.get('marker_length_m')==MARKER_LENGTH and target.get('marker_id')==MARKER_ID:
                            try:
                                from .machine import effective_points
                                points,_=effective_points(target['points_m'],action,s.machine_frame,motion)
                                lines=np.asarray(guide_lines(points,action['kind']))
                                projected=project(lines.reshape(-1,3),pose['transform'],matrix,distortion).reshape(-1,2,2)
                                if np.any(projected[:,:,0]<0) or np.any(projected[:,:,0]>w) or np.any(projected[:,:,1]<0) or np.any(projected[:,:,1]>h):
                                    result['state']='target_outside_view'
                                else:
                                    result['lines']=[{'a':{'x':float(a[0]),'y':float(a[1])},'b':{'x':float(b[0]),'y':float(b[1])}} for a,b in projected]
                                    result['visual']=compose(action,instance['label'],points,pose['transform'],matrix,distortion,self.asset_library,s.orientations.get(key),s.machine_frame,motion)
                                    if action['action_id'] in self.displays.profiles:
                                        result['visual']['display']=self.displays.at(action['action_id'],points[1]);result['visual']['text_labels']=[]
                                    result['target_ready']=True
                                    result['companion_visuals']=[]
                                    if action['action_id']=='holder.base':
                                        for other in action['target_instances']:
                                            _,_,other_key=self.target(action['action_id'],other['id'])
                                            saved=s.targets.get(other_key)
                                            if other_key==key or other_key not in s.authorized or other_key in s.invalidated or not saved:continue
                                            if saved.get('marker_id')!=MARKER_ID or saved.get('marker_length_m')!=MARKER_LENGTH:continue
                                            try:
                                                second,_=effective_points(saved['points_m'],action,s.machine_frame,motion)
                                                xy=project(second,pose['transform'],matrix,distortion)
                                                if np.any(xy[:,0]<0) or np.any(xy[:,0]>w) or np.any(xy[:,1]<0) or np.any(xy[:,1]>h):continue
                                                result['companion_visuals'].append(compose(action,other['label'],second,pose['transform'],matrix,distortion,self.asset_library,s.orientations.get(other_key),s.machine_frame,motion))
                                            except ValueError:continue
                            except ValueError:result['state']='target_outside_view'
                        else:result['state']='relocation_required' if key in s.invalidated else 'target_setup_required'
            for companion in result.get('companion_visuals',[]):
                if action['action_id'] in self.displays.profiles:companion['text_labels']=[]
            s.frames[s.last]={'raw':raw,'pose':pose,'size':(w,h),'sha256':request.source_sha256,'at':time.monotonic(),'action_id':action['action_id'],'target_id':request.target_id,'target_epoch':s.invalidated.get(key,''),'snapshot':snapshot.model_dump() if snapshot else None,'number':s.last}
            while len(s.frames)>80:
                oldest=next(k for k in s.frames if k not in s.pinned)
                del s.frames[oldest]
            # No unbounded per-frame images on disk; retain only explicit authoring/check evidence.
            result['processing_ms']=round((time.perf_counter()-started)*1000,2)
            cached=s.targets.get(key) if key not in s.invalidated else None
            if action['action_id']=='holder.slide' and not cached and key not in s.targets:
                cached=self.automatic.slide_reference(s,authorized=False)
            preview=None
            if pose and cached and cached.get('marker_id')==MARKER_ID and cached.get('marker_length_m')==MARKER_LENGTH:
                try:
                    xy=project([cached['points_m'][1]],pose['transform'],matrix,distortion)[0]
                    if 0<=xy[0]<w and 0<=xy[1]<h:preview={'x':float(xy[0]),'y':float(xy[1])}
                except ValueError:pass
            result['preflight']={'has_cached_target':bool(cached),'has_cached_machine':bool(s.machine_frame or getattr(s,'saved_machine',None)),
                'marker_visible':pose is not None,'can_start':bool(preview),'anchor':preview}
            self.event(s,'frame', {**{k:result[k] for k in ['client_frame_id','source_sha256','action_id','target_id','state','processing_ms']},
                'pose':result['pose'],'capture_snapshot':snapshot.model_dump() if snapshot else None,'target_anchor':result['visual']['anchor'] if result['visual'] else None,
                'asset_id':(result['visual'].get('asset') or {}).get('asset_id') if result['visual'] else None,
                'presentation_id':(result['visual'].get('presentation') or {}).get('presentation_id') if result['visual'] else None,
                'machine_frame_id':s.machine_frame['frame_id'] if s.machine_frame else None,
                'motion_parameters':motion,'placement_method':result['placement_method'],
                'catalog_sha256':self.asset_library.sha256})
            return result

    def pin(self,identity,frame_id):
        with self.session(identity) as s:
            if frame_id not in s.frames:raise HTTPException(409,'取景帧已过期，请重新取景。')
            s.pinned=[v for v in s.pinned if v!=frame_id][-1:]+[frame_id]
            return {'status':'pinned','client_frame_id':frame_id}

    def add_sample(self,s,pixels):
        if s.mode!='camera':raise HTTPException(409,'合成回放不能保存实机标定。')
        if len(s.samples)>=30:raise HTTPException(409,'已采集 30 张；请计算标定或重新开始采集。')
        gray=cv2.cvtColor(pixels,cv2.COLOR_BGR2GRAY)
        ok,corners=cv2.findChessboardCornersSB(gray,PATTERN)
        if not ok:raise HTTPException(422,'未看到完整棋盘，请让全部 9×6 内角点入镜。')
        corners=corners.reshape(-1,2).astype(np.float32)
        if s.samples and min(np.sqrt(np.mean((v-corners)**2)) for v in s.samples)<12:
            raise HTTPException(422,'此视角与已有样本太相似，请改变棋盘的位置、角度或距离。')
        s.samples.append(corners)

    def calibrate(self,identity):
        with self.session(identity) as s:
            if s.mode!='camera' or len(s.samples)<12:raise HTTPException(422,'至少采集 12 个不同角度的完整棋盘画面。')
            objects=np.zeros((PATTERN[0]*PATTERN[1],3),np.float32)
            objects[:,:2]=np.mgrid[:PATTERN[0],:PATTERN[1]].T.reshape(-1,2)*SQUARE
            allpoints=np.concatenate(s.samples);w,h=s.size
            if np.ptp(allpoints[:,0])<w*.65 or np.ptp(allpoints[:,1])<h*.65:
                raise HTTPException(422,'样本覆盖不足；请在画面四角、近处和远处补拍棋盘。')
            rms,matrix,distortion,rv,tv=cv2.calibrateCamera([objects]*len(s.samples),s.samples,s.size,None,None)
            per_view=[float(np.sqrt(np.mean(np.sum((cv2.projectPoints(objects,r,t,matrix,distortion)[0].reshape(-1,2)-p)**2,axis=1)))) for p,r,t in zip(s.samples,rv,tv)]
            if not np.isfinite(rms) or rms>1.2 or max(per_view)>2 or not .3*w<matrix[0,0]<4*w or not .3*h<matrix[1,1]<5*h or not 0<matrix[0,2]<w or not 0<matrix[1,2]<h:
                raise HTTPException(422,'标定误差较大，请重新采集清晰且有倾斜角度的棋盘。')
            s.calibration={'schema_version':'manual2ar-camera-calibration-v1','width':w,'height':h,
                'matrix':matrix.tolist(),'distortion':distortion.flatten().tolist(),'rms_px':float(rms),
                'views':len(s.samples),'per_view_rms_px':per_view,'square_m':SQUARE}
            atomic_json(self.profile('cameras',s.camera),s.calibration)
            s.frames.clear();self.event(s,'calibration.saved',s.calibration)
            return {'status':'calibrated','rms_px':rms,'views':len(s.samples)}

    def author(self,identity,request):
        _,instance,key=self.target(request.action_id,request.target_id)
        with self.session(identity) as s:
            self.require_u7(s,request.action_id)
            if s.mode!='camera' or not s.calibration:raise HTTPException(409,'请先为真实摄像头完成标定。')
            first,second=s.frames.get(request.first_frame),s.frames.get(request.second_frame)
            if first is None or second is None or not first['pose'] or not second['pose']:
                raise HTTPException(409,'两张取景都必须清楚看到标记；请重新设置作用点。')
            if any(f['action_id']!=request.action_id for f in (first,second)):
                raise HTTPException(409,'设置画面属于其他动作，请重新为当前动作取景。')
            if any(f.get('target_id','main')!=request.target_id for f in (first,second)):
                raise HTTPException(409,'设置画面属于其他操作位置，请重新取景。')
            if any(f.get('target_epoch','')!=s.invalidated.get(key,'') for f in (first,second)):
                raise HTTPException(409,'部件移动前的设置画面已失效，请重新拍摄两个视角。')
            if max(time.monotonic()-x['at'] for x in [first,second])>300:
                raise HTTPException(409,'设置画面已过期，请重新取景。')
            p=[[v.x,v.y] for v in request.first_points];q=[[v.x,v.y] for v in request.second_points]
            for points,frame in [(p,first),(q,second)]:
                if any(x>=frame['size'][0] or y>=frame['size'][1] for x,y in points):raise HTTPException(422,'作用点超出画面。')
            try:
                points,quality=triangulate(p,first['pose']['transform'],q,second['pose']['transform'],np.array(s.calibration['matrix']),np.array(s.calibration['distortion']))
            except ValueError as error:raise HTTPException(422,str(error)) from None
            candidate=uuid.uuid4().hex
            value={'schema_version':'manual2ar-spatial-target-v1','action_id':request.action_id,
                   'target_epoch':s.invalidated.get(key,''),
                   'target_id':request.target_id,'target_label':instance['label'],
                   'points_m':points,'quality':quality,'marker_id':MARKER_ID,'marker_length_m':MARKER_LENGTH,
                   'source_frame_sha256':[first['sha256'],second['sha256']], 'official_snapshot':self.plan['snapshot_id']}
            s.candidates.clear();s.candidates[candidate]=value
            folder=self.root/'runs'/s.identity/candidate;folder.mkdir(parents=True,exist_ok=True)
            (folder/'view-1.jpg').write_bytes(first['raw']);(folder/'view-2.jpg').write_bytes(second['raw'])
            atomic_json(folder/'authoring.json',{'first_pixels':p,'second_pixels':q,**value})
            self.event(s,'target.candidate',{'candidate_id':candidate,**value})
            return {'candidate_id':candidate,'action_id':request.action_id,'target_id':request.target_id,**quality,
                    'message':'位置已重建；确认两张图选择的是同一对真实起终点，且标记未移动，再保存。'}

    def save(self,identity,request):
        with self.session(identity) as s:
            target=s.candidates.pop(request.candidate_id,None)
            if not target:raise HTTPException(409,'位置候选已失效，请重新设置。')
            _,_,key=self.target(target['action_id'],target.get('target_id','main'))
            if target.get('target_epoch','')!=s.invalidated.get(key,''):raise HTTPException(409,'部件位置在设置期间发生变化，请重新取景设置。')
            # Merge under global lock so separate camera sessions cannot overwrite other actions.
            with self.profile_lock:
                path=self.profile('rigs',s.rig)
                latest=json.loads(path.read_text()) if path.is_file() else {}
                latest[key]=target;atomic_json(path,latest);s.targets=latest;s.reuse=True;s.authorized.add(key)
                if key in s.invalidated:
                    del s.invalidated[key];atomic_json(self.profile('rig-validity',s.rig),s.invalidated)
            self.event(s,'target.confirmed',target)
            return {'status':'saved','action_id':target['action_id'],'target_id':target.get('target_id','main')}

    def interaction(self,identity,request):
        action,_,_=self.target(request.action_id,request.target_id)
        with self.session(identity) as s:
            self.require_u7(s,request.action_id)
            if request.event_id in s.event_ids:return {'status':'recorded','duplicate':True}
            if request.client_frame_id:
                frame=s.frames.get(request.client_frame_id)
                if not frame or frame['sha256']!=request.source_sha256 or frame['action_id']!=request.action_id or frame.get('target_id','main')!=request.target_id:
                    raise HTTPException(409,'交互对应的取景已过期或属于其他位置。')
            if self.experience:
                self.experience.record(s.context,s.identity,s.mode,action,request.target_id,request.name)
            self.event(s,'interaction.'+request.name,{**request.model_dump(),'operation_verified':False})
            if request.name=='user_marked' and action.get('invalidates_actions'):
                with self.profile_lock:
                    for action_id in action['invalidates_actions']:
                        affected=self.action(action_id)
                        for instance in affected['target_instances']:
                            _,_,key=self.target(action_id,instance['id']);s.invalidated[key]=uuid.uuid4().hex
                    if s.mode!='replay':atomic_json(self.profile('rig-validity',s.rig),s.invalidated)
                self.event(s,'targets.require_relocation',{'cause_action':action['action_id'],'invalidated_actions':action['invalidates_actions'],'source':'user_marked_not_visual_detection'})
            s.event_ids[request.event_id]=True
            while len(s.event_ids)>256:s.event_ids.popitem(last=False)
            return {'status':'recorded','duplicate':False,'operation_verified':False,'relocation_required':bool(request.name=='user_marked' and action.get('invalidates_actions'))}

    def vision_anchors(self,s,frame,action,target_id,chapter=False):
        """Project only explicitly authorized positions using the requested frame pose."""
        if not frame['pose'] or not s.calibration:return []
        result=[];matrix=np.array(s.calibration['matrix']);distortion=np.array(s.calibration['distortion'])
        actions=[a for a in self.actions.values() if a['chapter_id']==action['chapter_id']] if chapter else [action]
        for unit in actions:
            for instance in unit['target_instances']:
                if not chapter and instance['id']!=target_id:continue
                _,_,key=self.target(unit['action_id'],instance['id']);target=s.targets.get(key)
                if key not in s.authorized or key in s.invalidated or not target or target.get('marker_id')!=MARKER_ID or target.get('marker_length_m')!=MARKER_LENGTH:continue
                points=target['points_m'] if unit['kind']=='slide' else [target['points_m'][-1]]
                try:pixels=project(points,frame['pose']['transform'],matrix,distortion)
                except ValueError:continue
                w,h=frame['size']
                for point in pixels:
                    if 0<=point[0]<w and 0<=point[1]<h:
                        result.append({'action_id':unit['action_id'],'target_id':instance['id'],'label':instance['label'],
                            'point_0_1000':[round(float(point[0])/w*1000),round(float(point[1])/h*1000)]})
        return result

    def verify(self,identity,request):
        if self.action(request.action_id)["chapter_id"]=="U7":return self.verify_u7(identity,request)
        action,_,_=self.target(request.action_id,request.target_id)
        if action.get('verification_mode')=='manual':raise HTTPException(409,'本章由用户对照官方说明人工确认，视觉不能判断螺丝松紧；本次未调用 VLM。')
        with self.session(identity) as s:
            if s.mode=='replay':raise HTTPException(409,'合成回放不能作为真实安装核验。')
            frame=s.frames.get(request.client_frame_id)
            if not frame or time.monotonic()-frame['at']>60:raise HTTPException(409,'请重新拍摄当前画面。')
            if frame['action_id']!=action['action_id']:raise HTTPException(409,'照片属于其他动作，请重新拍摄。')
            if frame.get('target_id','main')!=request.target_id:raise HTTPException(409,'照片属于其他位置，请重新拍摄。')
            raw,sha=frame['raw'],frame['sha256'];anchors=self.vision_anchors(s,frame,action,request.target_id,chapter=True)
        if not self.config['vlm']['api_key'].strip():raise HTTPException(503,'请在 configs/app.local.json 填写 vlm.api_key。')
        # Reuse the immutable V1 chapter-specific prompt and result contract.
        from ..verification import bound_prompt,result_contract
        _,task=self.registry.resolve(self.plan['task_id'],self.plan['variant_id'])
        state=next(v for v in task.document.states if v.state_id==action['chapter_id']);node=state.observation_nodes[0]
        prompt,binding=task.prompt(state,node);prompt=bound_prompt(prompt,task.document.task.task_id,state,node)
        contract=result_contract(state.state_id,node.inspection_id)
        folder=self.root/'runs'/identity/('check-'+uuid.uuid4().hex);folder.mkdir(parents=True,exist_ok=True)
        from .vision_context import prepare,failure
        images,context,meta=prepare(raw,anchors,folder);prompt+=context
        if action['chapter_id']=='U7':
            prompt+='\n消歧约束：目标是固定在打印机 Z 立柱上的白色／浅灰色外挂料盘支架及小底座，排除桌面旁堆叠料卷、蓝色支架和其他装置。只检查底座可见贴合及支架可见接合；连接区域看不清时返回 uncertain，不能仅凭外观完整判定通过。不能判断或要求用照片确认螺丝扭矩。'
        (folder/'input.jpg').write_bytes(raw);(folder/'prompt.txt').write_text(prompt,encoding='utf-8')
        started=time.perf_counter();self.event(s,'vision.started',{'kind':'chapter_advice','action_id':action['action_id'],'client_frame_id':request.client_frame_id,'source_sha256':sha,'image_count':meta['image_count'],'artifact':folder.name})
        try:
            raw_reply=self.client.chat_structured(prompt=prompt,schema=contract.model_json_schema(),images_base64=images,max_tokens=self.config['verification']['max_tokens'])
            atomic_json(folder/'model_reply.json',raw_reply);reply=contract.model_validate(raw_reply)
            if reply.confidence<self.config['verification']['minimum_confidence']:
                reply=reply.model_copy(update={'status':'uncertain','next_action':'请补拍清晰的安装区域，或对照官方参考图自行确认。'})
        except Exception as error:
            details=failure(folder,error);self.event(s,'vision.failed',{'kind':'chapter_advice','artifact':folder.name,'elapsed_ms':round((time.perf_counter()-started)*1000),**details})
            raise HTTPException(502,'AI 拍照参考暂不可用，可继续查看其他动作或稍后重试。') from None
        atomic_json(folder/'result.json',{'source_sha256':sha,'official_prompt_sha256':binding['sha256'],
            'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),**reply.model_dump()})
        with self.session(identity) as current:
            self.event(current,'vision.finished',{'kind':'chapter_advice','artifact':folder.name,'status':reply.status,'source_sha256':sha,'elapsed_ms':round((time.perf_counter()-started)*1000)})
            if self.experience:self.experience.record(current.context,identity,current.mode,action,request.target_id,'chapter_advice',{'advice_status':reply.status,'source_sha256':sha})
        return {'action_id':action['action_id'],'target_id':request.target_id,'chapter_id':state.state_id,'source_sha256':sha,
                'client_frame_id':request.client_frame_id,'advisory_only':True,**reply.model_dump()}

    def locate(self,identity,request):
        if self.action(request.action_id)["chapter_id"]=="U7":
            frame=self.photo_frame(identity,request)
            return self.part_tracking.begin(identity,frame)
        action,instance,_=self.target(request.action_id,request.target_id)
        with self.session(identity) as s:
            if s.mode=='replay':raise HTTPException(409,'模拟场景不调用现场部件识别。')
            if s.locating:raise HTTPException(409,'正在寻找当前部件，请稍候。')
            frame=s.frames.get(request.client_frame_id)
            if not frame or time.monotonic()-frame['at']>60 or frame['action_id']!=request.action_id or frame.get('target_id','main')!=request.target_id:
                raise HTTPException(409,'请重新拍摄当前动作和操作位置。')
            raw,sha=frame['raw'],frame['sha256'];anchors=self.vision_anchors(s,frame,action,request.target_id);s.locating=True
        try:
            if not self.config['vlm']['api_key'].strip():raise HTTPException(503,'请在 configs/app.local.json 填写 vlm.api_key。')
            from .localization import locate
            from .vision_context import failure
            folder=self.root/'runs'/identity/('locate-'+uuid.uuid4().hex);folder.mkdir(parents=True,exist_ok=True)
            started=time.perf_counter();self.event(s,'vision.started',{'kind':'location','artifact':folder.name,'action_id':action['action_id'],'client_frame_id':request.client_frame_id,'source_sha256':sha,'has_authored_context':bool(anchors)})
            try:result=locate(self.client,self.config,raw,action,instance,folder,anchors)
            except Exception as error:
                details=failure(folder,error);self.event(s,'vision.failed',{'kind':'location','artifact':folder.name,'elapsed_ms':round((time.perf_counter()-started)*1000),**details})
                raise HTTPException(502,'暂时无法找到这个位置，请靠近安装区域或换角度再拍。') from None
            with self.session(identity) as current:
                latest=current.frames.get(current.last)
                if not latest or (latest['action_id'],latest.get('target_id','main'))!=(request.action_id,request.target_id):
                    raise HTTPException(409,'指导动作已切换，旧定位已丢弃。')
                self.event(current,'vision.finished',{'kind':'location','artifact':folder.name,'status':result['status'],'source_sha256':sha,'elapsed_ms':round((time.perf_counter()-started)*1000)})
                if self.experience:self.experience.record(current.context,identity,current.mode,action,request.target_id,'location_preview',{'source_sha256':sha,'localization_status':result['status']})
            return {**result,'session_id':identity,'source_sha256':sha,'client_frame_id':request.client_frame_id}
        finally:
            with s.lock:s.locating=False

    def photo_frame(self,identity,request):
        with self.session(identity) as session:
            if session.mode=='replay':raise HTTPException(409,'合成回放不能调用现场视觉检查。')
            self.require_u7(session,request.action_id)
            frame=session.frames.get(request.client_frame_id)
            if not frame or time.monotonic()-frame['at']>60 or frame['action_id']!=request.action_id or frame.get('target_id','main')!=request.target_id:raise HTTPException(409,'请重新拍摄当前步骤。')
            return {**frame,'client_frame_id':request.client_frame_id}

    def part_event(self,job,name,data):
        with self.lock:session=self.sessions.get(job.session_id)
        if session and not session.closed:self.event(session,name,{'job_id':job.identity,**data})

    def verify_u7(self,identity,request):
        frame=self.photo_frame(identity,request)
        if not self.config['vlm']['api_key'].strip():raise HTTPException(503,'请在配置文件填写 API Key。')
        folder=self.root/'runs'/identity/('installation-'+uuid.uuid4().hex);folder.mkdir(parents=True)
        from .u7_vision import installation
        from .vision_context import failure
        started=time.perf_counter()
        from .u7_vision import base_installation
        from .. import u7_sequence as sequence
        with self.session(identity) as current:token=self.u7_progress(current,lambda owner:sequence.start(owner,request.action_id))
        try:answer=base_installation(self.client,self.config,frame['raw'],self.references['base'],folder) if request.action_id=='holder.base' else installation(self.client,self.config,frame['raw'],self.references['installation'],folder)
        except Exception as error:
            failure(folder,error)
            with self.session(identity) as current:self.u7_progress(current,lambda owner:sequence.finish(owner,request.action_id,token,{'status':'uncertain','evidence':'视觉服务暂不可用，请重新检查。'}))
            raise HTTPException(502,'安装参考暂不可用，请稍后重新拍摄。') from None
        with self.session(identity) as session:
            progress=self.u7_progress(session,lambda owner:sequence.finish(owner,request.action_id,token,{**answer,'source_sha256':frame['sha256'],'frame_id':request.client_frame_id}))
            self.event(session,'installation.checked',{'client_frame_id':request.client_frame_id,'source_sha256':frame['sha256'],'status':answer['status'],'scope':'visible_final_installation','elapsed_ms':round((time.perf_counter()-started)*1000)})
        return {**answer,'action_id':request.action_id,'target_id':request.target_id,'source_sha256':frame['sha256'],'client_frame_id':request.client_frame_id,'u7_sequence':progress,'advisory_only':request.action_id!='holder.base','scope':'visible_base_installation' if request.action_id=='holder.base' else 'visible_final_installation'}

    def orient(self,identity,request):
        from .orientation import rotation
        try:rotation(request.rotation_degrees)
        except ValueError as error:raise HTTPException(422,str(error)) from None
        _,_,key=self.target(request.action_id,request.target_id)
        with self.session(identity) as session:
            self.require_u7(session,request.action_id)
            if key not in session.authorized or key in session.invalidated:raise HTTPException(409,'请先确认当前作用点，再调整 XYZ 姿态。')
            value={'rotation_degrees':request.rotation_degrees,'rotation_sign':request.rotation_sign}
            with self.profile_lock:
                path=self.profile('orientations',session.rig);saved=json.loads(path.read_text()) if path.is_file() else {};saved[key]=value
                if session.mode!='replay':atomic_json(path,saved)
                session.orientations[key]=value
            self.event(session,'orientation.saved',{'action_id':request.action_id,'target_id':request.target_id,**value})
            return value

    def u7_progress(self,session,callback=None):
        from .. import u7_sequence as sequence
        if session.context and self.experience:
            value=self.experience.u7_progress(session.context,callback)
            return {**value,'enforced':False,'message':'合成回放仅展示动作，不解锁实机安装。'} if callback is None and session.mode=='replay' else value
        return callback(session) if callback else sequence.state(session,enforced=session.mode!='replay')

    def require_u7(self,session,action_id):
        from ..u7_sequence import MESSAGE
        if session.mode!='replay' and action_id=='holder.slide' and not self.u7_progress(session)['base_approved']:raise HTTPException(409,MESSAGE)
