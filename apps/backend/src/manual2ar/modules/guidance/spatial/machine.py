"""Explicit printer work-frame authoring, independent of VLM and part tracking."""
import json
import time
import uuid
import numpy as np
import cv2
from fastapi import HTTPException
from manual2ar_contracts.machine_frame import MachineFrame,MotionParameters
from manual2ar_perception.spatial import triangulate
from .printing import MARKER_ID,MARKER_LENGTH


def from_points(points):
    """O, point along +X, point along +Z. Gram-Schmidt keeps measured X and orthogonalizes Z."""
    o,px,pz=np.asarray(points,dtype=float);x=px-o;z=pz-o
    if not .025<=np.linalg.norm(x)<=.4 or not .025<=np.linalg.norm(z)<=.4:raise ValueError('坐标方向点应距离原点 25–400 毫米。')
    cosine=float(np.dot(x,z)/(np.linalg.norm(x)*np.linalg.norm(z)))
    if abs(cosine)>.35:raise ValueError('请选择互相垂直的 +X 和 +Z 实物方向；不要选择接近同一条线的点。')
    x/=np.linalg.norm(x);z-=x*np.dot(x,z);z/=np.linalg.norm(z);y=np.cross(z,x)
    transform=np.eye(4);transform[:3,:3]=np.column_stack([x,y,z]);transform[:3,3]=o
    return transform,float(np.degrees(np.arccos(np.clip(cosine,-1,1))))


def default_motion(action):
    return MotionParameters.model_validate(action.get('machine_motion',{'enabled':False})).model_dump()


def effective_points(points,action,machine,motion):
    """Existing authored end remains fixed; motion axis is explicitly selected in printer coordinates."""
    original=np.asarray(points,dtype=float)
    if not machine or not motion['enabled'] or action['chapter_id']!='U7':return original,None
    t=np.asarray(machine['marker_from_machine']).reshape(4,4)
    direction=t[:3,'XYZ'.index(motion['axis'])]*motion['direction'];end=original[1]
    return np.array([end-direction*motion['distance_mm']/1000,end]),direction


class MachineGuidance:
    def __init__(self,service):self.service=service

    def load(self,rig):
        path=self.service.profile('machines',rig)
        if not path.exists():return None
        value=MachineFrame.model_validate_json(path.read_bytes()).model_dump()
        if value['marker_id']!=MARKER_ID or value['marker_length_m']!=MARKER_LENGTH:raise ValueError('Machine reference marker differs')
        return value

    def motion(self,session,action):
        return session.motion_parameters.get(action['action_id'],default_motion(action))

    def author(self,identity,command):
        service=self.service
        with service.session(identity) as s:
            if s.mode!='camera' or not s.calibration:raise HTTPException(409,'请先完成当前相机画幅的标定。')
            frames=[s.frames.get(command.first_frame),s.frames.get(command.second_frame)]
            if command.first_frame==command.second_frame or any(not f or not f['pose'] or time.monotonic()-f['at']>300 for f in frames):raise HTTPException(409,'需要两个新鲜且清楚看到固定标记的不同视角。')
            p=np.array([[v.x,v.y] for v in command.first_points]);q=np.array([[v.x,v.y] for v in command.second_points])
            attempt=uuid.uuid4().hex
            folder=service.root/'runs'/identity/('machine-'+attempt);folder.mkdir(parents=True)
            for index,(f,pixels) in enumerate(zip(frames,[p,q])):
                (folder/f'view-{index+1}.jpg').write_bytes(f['raw'])
                image=cv2.imdecode(np.frombuffer(f['raw'],np.uint8),cv2.IMREAD_COLOR)
                if image is not None:
                    for label,pixel in zip(['O','+X','+Z'],pixels):
                        point=tuple(np.rint(pixel).astype(int))
                        cv2.drawMarker(image,point,(0,255,255),cv2.MARKER_CROSS,14,2)
                        cv2.putText(image,label,(point[0]+8,point[1]-8),cv2.FONT_HERSHEY_SIMPLEX,.6,(0,255,255),2)
                    cv2.imwrite(str(folder/f'view-{index+1}-clicks.jpg'),image)
            def pose_record(frame):
                pose=frame['pose']
                return {key:np.asarray(value).tolist() for key,value in pose.items()}
            diagnostic={'schema_version':'manual2ar-machine-diagnostic-v1','attempt_id':attempt,
                'first_frame':command.first_frame,'second_frame':command.second_frame,
                'first_pixels':p.tolist(),'second_pixels':q.tolist(),'point_labels':['O','+X','+Z'],
                'frames':[{'sha256':f['sha256'],'size':list(f['size']),'pose':pose_record(f)} for f in frames],
                'calibration':s.calibration,'thresholds':{'maximum_reprojection_px':3,'ray_angle_deg':[5,100]},'points':[]}
            matrix=np.array(s.calibration['matrix']);distortion=np.array(s.calibration['distortion'])
            try:
                for pixels,frame in zip([p,q],frames):
                    if np.any(pixels<0) or np.any(pixels>=np.asarray(frame['size'])):raise ValueError('坐标点超出取景范围。')
                points,a=triangulate(p,frames[0]['pose']['transform'],q,frames[1]['pose']['transform'],matrix,distortion,diagnostic['points'])
                transform,angle=from_points(points)
            except ValueError as error:
                message=str(error)
                for index,label in enumerate(['O','+X','+Z']):message=message.replace(f'第 {index+1} 点：',f'{label} 点：')
                diagnostic.update(status='rejected',error=message)
                service.store_profile(folder/'diagnostic.json',diagnostic)
                service.event(s,'machine.rejected',{'attempt_id':attempt,'error':message,'points':diagnostic['points']})
                raise HTTPException(422,f'{message} 诊断编号：{attempt[:8]}') from None
            diagnostic.update(status='accepted',quality=a)
            service.store_profile(folder/'diagnostic.json',diagnostic)
            quality={'maximum_reprojection_px':a['maximum_reprojection_px'],'minimum_ray_angle_deg':a['minimum_ray_angle_deg'],'measured_xz_angle_deg':angle}
            candidate=attempt
            value=MachineFrame(marker_id=MARKER_ID,marker_length_m=MARKER_LENGTH,marker_from_machine=transform.ravel().tolist(),frame_id=candidate,source_frame_sha256=[f['sha256'] for f in frames],quality=quality).model_dump()
            s.machine_candidates.clear();s.machine_candidates[candidate]=value
            service.store_profile(folder/'candidate.json',{'first_pixels':p.tolist(),'second_pixels':q.tolist(),**value})
            service.event(s,'machine.candidate',{'frame_id':candidate,**quality})
            from .orientation import axes
            preview=axes(transform[:3,3],transform[:3,:3],frames[1]['pose']['transform'],matrix,distortion,.05)
            return {'candidate_id':candidate,**value,'preview_axes':preview,'message':'坐标系已重建。确认红 X 沿横梁正向、蓝 Z 向上，绿 Y 按右手规则；标记与机架必须保持固定，再保存。'}

    def confirm(self,identity,command):
        service=self.service
        with service.session(identity) as s:
            value=s.machine_candidates.pop(command.candidate_id,None)
            if not value:raise HTTPException(409,'坐标系候选已失效，请重新设置。')
            with service.profile_lock:
                if s.mode!='replay':service.store_profile(service.profile('machines',s.rig),value)
                s.machine_frame=value
            service.event(s,'machine.confirmed',value)
            return {'status':'saved','frame':value}

    def save_motion(self,identity,command):
        service=self.service;action=service.action(command.action_id)
        if action['chapter_id']!='U7':raise HTTPException(422,'当前仅 U7 开放工作坐标系动作参数。')
        with service.session(identity) as s:
            service.require_u7(s,command.action_id)
            if command.parameters.enabled and not s.machine_frame:raise HTTPException(409,'请先设置或明确沿用打印机工作坐标系。')
            value=command.parameters.model_dump()
            presentation=service.asset_library.presentations.get(action.get('visual_guidance',{}).get('presentation_id'))
            allowed={layer.id for layer in presentation.layers} if presentation else set()
            if any(component['id'] not in allowed for component in value['components']):raise HTTPException(422,'动作组件不属于当前教学步骤。')
            with service.profile_lock:
                path=service.profile('motions',s.rig);saved=json.loads(path.read_text()) if path.is_file() else {};saved[command.action_id]=value
                if s.mode!='replay':service.store_profile(path,saved)
                s.motion_parameters[command.action_id]=value
            service.event(s,'motion.saved',{'action_id':command.action_id,**value})
            return value
