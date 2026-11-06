"""Explicit printed reference and VLM-assisted two-view configuration. Never marks a task passed."""
import hashlib
import json
import shutil
import time
import uuid
import cv2
import numpy as np
from fastapi import HTTPException
from manual2ar_contracts.machine_frame import MachineFrame
from manual2ar_contracts.automatic_guidance import GuidanceRecipe
from manual2ar_perception.spatial import triangulate,project
from .printing import MARKER_ID, MARKER_LENGTH

PROFILE='a1-mini-flat-board-v1'
PROFILE_GROUPS=('rigs','machines','motions','orientations','rig-validity')


class AutomaticGuidance:
    def __init__(self,service):
        self.service=service
        document=json.loads((service.store.path('task.unboxing.spatial').parent/'automatic.json').read_text())
        self.recipes=[GuidanceRecipe.model_validate(r) for r in document['recipes']]
        for recipe in self.recipes:
            if recipe.action_id not in service.actions or recipe.presentation_id not in service.asset_library.presentations:
                raise ValueError('Automatic recipe refers to an unknown action or presentation')

    def slide_reference(self,session,authorized=True):
        from .placement import slide_illustration
        if 'holder.slide' in session.invalidated:return None
        targets={k:v for k,v in session.targets.items() if k not in session.invalidated and (not authorized or k in session.authorized)}
        machine=session.machine_frame if authorized else session.machine_frame or getattr(session,'saved_machine',None)
        motion=self.service.machine.motion(session,self.service.action('holder.slide'))
        return slide_illustration(targets,machine,motion['distance_mm'])

    def fingerprint(self,rig):
        digest=hashlib.sha256()
        for name in PROFILE_GROUPS:
            path=self.service.profile(name,rig);digest.update(name.encode());digest.update(path.read_bytes() if path.exists() else b'')
        return digest.hexdigest()

    def frame(self,s,number,age=60):
        f=s.frames.get(number)
        if s.mode!='camera' or not s.calibration or not f or not f['pose'] or time.monotonic()-f['at']>age:
            raise HTTPException(409,'请完成当前画幅标定，让定位板完整入镜并重新取景。')
        return f

    def reference(self,identity,command):
        service=self.service
        with service.session(identity) as s,service.profile_lock:
            f=self.frame(s,command.client_frame_id,5)
            if s.locating:raise HTTPException(409,'请等待当前识别结束。')
            if s.targets or service.profile('rigs',s.rig).exists():
                raise HTTPException(409,'已有作用点，请先选择“备份并重新配置”，避免新坐标覆盖旧配置。')
            matrix=np.eye(4)
            value=MachineFrame(marker_id=MARKER_ID,marker_length_m=MARKER_LENGTH,marker_from_machine=matrix.ravel().tolist(),
                frame_id=uuid.uuid4().hex,source_frame_sha256=[f['sha256']],quality={'marker_reprojection_px':f['pose']['reprojection_px']},
                placement_method='printed_reference',reference_profile_id=PROFILE).model_dump()
            service.store_profile(service.profile('machines',s.rig),value)
            s.machine_frame=value;s.saved_machine=value;s.automatic_views.clear();s.automatic_candidate=None
            service.event(s,'automatic.reference_confirmed',{'profile_id':PROFILE,'client_frame_id':command.client_frame_id,'source_sha256':f['sha256'],'frame_id':value['frame_id']})
            return {'status':'ready','machine_frame':value,'message':'坐标板工作坐标已启用；请保持定位板和打印机相对固定。'}

    def reset(self,identity):
        service=self.service
        # Do not erase another active camera session's reference.
        with service.lock:
            s=service.sessions.get(identity)
            if s and any(v.identity!=identity and v.rig==s.rig and not v.closed for v in service.sessions.values()):
                raise HTTPException(409,'请先关闭其他使用这台打印机的空间指导页面。')
        with service.session(identity) as s,service.profile_lock:
            if s.mode!='camera' or s.locating:raise HTTPException(409,'请先启动实机摄像头并等待当前识别结束。')
            backup=service.root/'profile-backups'/uuid.uuid4().hex;backup.mkdir(parents=True)
            entries=[]
            for name in PROFILE_GROUPS:
                path=service.profile(name,s.rig)
                if path.exists():
                    raw=path.read_bytes();shutil.copyfile(path,backup/(name+'.json'));entries.append({'group':name,'sha256':hashlib.sha256(raw).hexdigest()})
            service.store_profile(backup/'manifest.json',{'rig_id':s.rig,'files':entries,'camera_calibration_preserved':True})
            for name in PROFILE_GROUPS:service.profile(name,s.rig).unlink(missing_ok=True)
            s.targets={};s.authorized.clear();s.invalidated={};service.rig_validity[s.rig]=s.invalidated
            s.machine_frame=None;s.saved_machine=None;s.motion_parameters={};s.orientations={};s.candidates.clear();s.machine_candidates.clear()
            s.automatic_views.clear();s.automatic_candidate=None;s.frames.clear();s.pinned.clear()
            service.part_tracking.cancel(identity)
            service.event(s,'automatic.profiles_reset',{'backup_id':backup.name,'files':entries})
            return {'status':'reset','backup_id':backup.name,'message':'旧位置与动画参数已备份；相机标定已保留。'}

    def observe(self,identity,command):
        service=self.service
        with service.session(identity) as s:
            service.require_u7(s,command.action_id)
            if command.action_id not in ('holder.base','holder.slide'):raise HTTPException(422,'自动配置当前仅用于 U7。')
            f=self.frame(s,command.client_frame_id)
            if f['action_id']!=command.action_id or f.get('target_id','main')!=command.target_id:raise HTTPException(409,'照片属于其他步骤或目标。')
            if not s.machine_frame:raise HTTPException(409,'请先确认坐标板方向，或设置打印机工作坐标。')
            if s.locating:raise HTTPException(409,'正在处理当前照片，请稍候。')
            if not service.config['vlm']['api_key'].strip():raise HTTPException(503,'请先配置 VLM 服务。')
            s.locating=True;machine_id=s.machine_frame['frame_id'];profile_sha=self.fingerprint(s.rig)
            view_id=uuid.uuid4().hex;folder=service.root/'runs'/identity/('automatic-'+view_id);folder.mkdir(parents=True)
        try:
            from .automatic_vision import observe
            points,advice=observe(service.client,service.config,f['raw'],service.references['base'],folder)
            with service.session(identity) as s:
                if not s.machine_frame or machine_id!=s.machine_frame['frame_id'] or profile_sha!=self.fingerprint(s.rig):
                    raise HTTPException(409,'坐标或作用点已变化，本次定位已丢弃。')
                view={'id':view_id,'frame':f,'points':points,'machine_id':machine_id,'profile_sha':profile_sha,'action_id':command.action_id,'created':time.monotonic()}
                while len(s.automatic_views)>=2:s.automatic_views.pop(next(iter(s.automatic_views)))
                s.automatic_views[view_id]=view
                result={'view_id':view_id,'session_id':identity,'action_id':command.action_id,'client_frame_id':command.client_frame_id,'source_sha256':f['sha256'],
                    'points':[{'id':k,'point':{'x':p[0],'y':p[1]}} for k,p in points.items()],'message':'已定位螺丝。保持打印机和坐标板不动，横移相机约 15–25 厘米，再拍第二视角。'}
                service.store_profile(folder/'view.json',result);service.event(s,'automatic.features_located',result)
                return result
        except HTTPException:raise
        except Exception as error:
            from .vision_context import failure
            failure(folder,error)
            raise HTTPException(422,'自动定位未完成；请靠近底座、避开反光及遮挡后重试，或使用手动设点。') from None
        finally:
            with service.lock:current=service.sessions.get(identity)
            if current:
                with current.lock:current.locating=False

    def candidate(self,identity,command):
        service=self.service
        with service.session(identity) as s:
            service.require_u7(s,command.action_id)
            a,b=[s.automatic_views.get(i) for i in (command.first_view,command.second_view)]
            if not a or not b or a is b:raise HTTPException(409,'需要两张不同视角的自动定位结果。')
            with service.profile_lock:
                profile_sha=self.fingerprint(s.rig)
                saved_path=service.profile('rigs',s.rig)
                saved_targets=json.loads(saved_path.read_text()) if saved_path.is_file() else {}
            if any(time.monotonic()-v['created']>300 or v['action_id']!=command.action_id or v['machine_id']!=(s.machine_frame or {}).get('frame_id') or v['profile_sha']!=profile_sha for v in (a,b)):
                raise HTTPException(409,'两次取景已失效或配置已改变，请重新拍摄。')
            matrix=np.array(s.calibration['matrix']);dist=np.array(s.calibration['distortion']);diagnostic=[]
            folder=service.root/'runs'/identity/('automatic-candidate-'+uuid.uuid4().hex);folder.mkdir(parents=True)
            names=['screw_upper','screw_lower'];guide_rejection=''
            try:
                def reconstruct(labels):
                    records=[]
                    try:return triangulate([a['points'][k] for k in labels],a['frame']['pose']['transform'],[b['points'][k] for k in labels],b['frame']['pose']['transform'],matrix,dist,records)
                    finally:
                        for name,record in zip(labels,records):record['feature_id']=name
                        diagnostic.extend(records)
                points,quality=reconstruct(names)
                features=dict(zip(names,np.array(points)))
                work=np.array(s.machine_frame['marker_from_machine']).reshape(4,4);inverse=np.linalg.inv(work)
                local={k:(inverse@np.r_[v,1])[:3] for k,v in features.items()}
                delta=local['screw_upper']-local['screw_lower']
                if delta[2]<.005 or abs(delta[0])>.02 or abs(delta[1])>.02 or np.linalg.norm(delta)>.12:
                    raise ValueError('螺丝上下关系与工作坐标不一致，请检查坐标板朝向及两次定位。')
                if s.machine_frame.get('placement_method')=='printed_reference' and min(v[2] for v in local.values())<-.01:
                    raise ValueError('目标重建到定位板下方，请检查纸张尺寸、标定及摆放方向。')
                if {'guide_top','guide_bottom'}<=a['points'].keys() and {'guide_top','guide_bottom'}<=b['points'].keys():
                    try:
                        guide,guide_quality=reconstruct(['guide_top','guide_bottom'])
                        guide_local=[(inverse@np.r_[v,1])[:3] for v in guide];d=guide_local[0]-guide_local[1]
                        if d[2]<.008 or abs(d[0])>.02 or abs(d[1])>.02 or np.linalg.norm(d)>.15:
                            raise ValueError('导向边不符合竖直方向。')
                        if any(np.linalg.norm(np.asarray(g)-features['screw_lower'])>.12 for g in guide):raise ValueError('导向边与灰色底座距离不符。')
                        features.update(zip(['guide_top','guide_bottom'],np.array(guide)))
                        quality={'maximum_reprojection_px':max(quality['maximum_reprojection_px'],guide_quality['maximum_reprojection_px']),
                            'minimum_ray_angle_deg':min(quality['minimum_ray_angle_deg'],guide_quality['minimum_ray_angle_deg'])}
                    except ValueError as error:guide_rejection=str(error)
                targets={};preserved=[]
                for recipe in self.recipes:
                    if not all(k in features for k in recipe.feature_ids):continue
                    if recipe.operation=='translate' and 'guide_top' not in features:continue
                    action=service.action(recipe.action_id);motion=service.machine.motion(s,action)
                    axis=work[:3,'XYZ'.index(motion['axis'])]*motion['direction']
                    for target_id,feature_id in zip(recipe.target_ids,recipe.feature_ids):
                        _,instance,key=service.target(action['action_id'],target_id)
                        if key in saved_targets and key not in s.invalidated and not saved_targets[key].get('automatic_recipe_id'):
                            preserved.append(instance['label']);continue
                        end=features[feature_id];start=end-axis*motion['distance_mm']/1000
                        targets[key]={'schema_version':'manual2ar-spatial-target-v1','action_id':action['action_id'],'target_id':target_id,'target_label':instance['label'],
                            'points_m':[start.tolist(),end.tolist()],'quality':quality,'marker_id':MARKER_ID,'marker_length_m':MARKER_LENGTH,
                            'target_epoch':s.invalidated.get(key,''),'source_frame_sha256':[v['frame']['sha256'] for v in (a,b)],'official_snapshot':service.plan['snapshot_id'],
                            'automatic_recipe_id':recipe.id,'machine_frame_id':s.machine_frame['frame_id'],'placement_method':'vlm_two_view'}
                required={'holder.base','holder.base::second'} if command.action_id=='holder.base' else {'holder.slide'}
                if not required<=targets.keys()|{k for k in s.authorized if k in saved_targets and k not in s.invalidated}:raise ValueError('当前动作所需功能点不完整，请补拍导向边或使用手动设点。')
                if not targets:raise ValueError('现有手动位置已保留，无需自动覆盖；如需重建请先备份并重新配置。')
            except ValueError as error:
                service.store_profile(folder/'diagnostic.json',{'accepted':False,'error':str(error),'points':diagnostic})
                raise HTTPException(422,str(error)) from None
            if command.second_frame!=b['frame'].get('number'):raise HTTPException(409,'预览帧与第二次取景不匹配。')
            candidate_id=uuid.uuid4().hex
            s.automatic_candidate={'id':candidate_id,'created':time.monotonic(),'profile_sha':profile_sha,'machine_id':s.machine_frame['frame_id'],'targets':targets}
            preview=[]
            for key,target in targets.items():
                xy=project([target['points_m'][1]],b['frame']['pose']['transform'],matrix,dist)[0]
                preview.append({'id':key,'point':{'x':float(xy[0]),'y':float(xy[1])}})
            from .placement import slide_illustration
            illustration=slide_illustration({**{k:v for k,v in saved_targets.items() if k not in s.invalidated and k in s.authorized},**targets},s.machine_frame)
            observed_slide='holder.slide' in targets or ('holder.slide' in s.authorized and 'holder.slide' in saved_targets and 'holder.slide' not in s.invalidated)
            result={'candidate_id':candidate_id,'client_frame_id':command.second_frame,'source_sha256':b['frame']['sha256'],'session_id':identity,'points':preview,
                'target_count':len(targets),'slide_ready':observed_slide or illustration is not None,'slide_illustrative':not observed_slide and illustration is not None,
                'message':'请核对十字是否落在螺丝和导向边上；确认后保存。'+('手动配置的位置保持不变。' if preserved else ''),**quality}
            service.store_profile(folder/'diagnostic.json',{'accepted':True,'points':diagnostic,'targets':targets,'result':result,'guide_rejection':guide_rejection})
            service.event(s,'automatic.candidate',result)
            return result

    def confirm(self,identity,command):
        service=self.service
        with service.session(identity) as s,service.profile_lock:
            value=s.automatic_candidate
            if not value or value['id']!=command.candidate_id or time.monotonic()-value['created']>300:
                raise HTTPException(409,'自动配置候选已过期。')
            if value['profile_sha']!=self.fingerprint(s.rig) or value['machine_id']!=(s.machine_frame or {}).get('frame_id'):
                raise HTTPException(409,'配置已被修改，请重新预览；未覆盖现有位置。')
            path=service.profile('rigs',s.rig)
            latest=json.loads(path.read_text()) if path.is_file() else {}
            for key,target in value['targets'].items():
                if target['target_epoch']!=s.invalidated.get(key,''):raise HTTPException(409,'部件位置已变化，请重新拍摄。')
                latest[key]=target
            service.store_profile(service.profile('rigs',s.rig),latest)
            s.targets=latest;s.authorized.update(value['targets']);s.reuse=True;s.saved_machine=s.machine_frame
            for key in value['targets']:s.invalidated.pop(key,None)
            service.store_profile(service.profile('rig-validity',s.rig),s.invalidated)
            s.automatic_candidate=None;s.automatic_views.clear()
            service.event(s,'automatic.confirmed',{'candidate_id':value['id'],'targets':list(value['targets'])})
            return {'status':'saved','target_count':len(value['targets']),'message':'自动作用点已保存，动画按官方步骤模板配置；安装仍需单独核验。'}
