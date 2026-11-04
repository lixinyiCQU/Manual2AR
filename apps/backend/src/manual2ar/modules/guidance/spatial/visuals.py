"""Task-selected illustration assets. Geometry never supplies installation evidence."""
import numpy as np
from manual2ar_contracts.spatial import GuidanceVisual
from manual2ar_perception.spatial import visual_geometry


def compose(action, label, points, camera_from_marker, intrinsics, distortion, library=None, orientation=None, machine=None, motion=None):
    preset=action.get('visual_guidance')
    points=np.asarray(points,dtype=float)
    if points.shape!=(2,3) or not np.all(np.isfinite(points)) or not .008<=np.linalg.norm(points[1]-points[0])<=.4:
        raise ValueError('Invalid authored tool axis or movement path')
    result=visual_geometry(points,action['kind'],camera_from_marker,intrinsics,distortion)
    if preset:
        start,end=np.asarray(points,dtype=float)
        delta=end-start
        length=np.linalg.norm(delta)
        if not .008<=length<=.4:
            raise ValueError('Invalid authored tool axis or movement path')
        axis=delta/length
        # A roll reference from the fixed marker, not a newly inferred surface normal.
        reference=np.array([0.,0.,1.]) if abs(axis[2])<.9 else np.array([1.,0.,0.])
        side=np.cross(axis,reference);side/=np.linalg.norm(side)
        normal=np.cross(side,axis)
        from .orientation import rotation,axes
        active_machine=bool(machine and motion and motion['enabled'] and action['chapter_id']=='U7')
        settings=orientation or {}
        if active_machine:
            # Roll comes from the printer's fixed work frame, never its current camera view.
            work=np.asarray(machine['marker_from_machine']).reshape(4,4)[:3,:3]
            side=work[:,0]-axis*np.dot(work[:,0],axis)
            if np.linalg.norm(side)<.1:side=work[:,1]-axis*np.dot(work[:,1],axis)
            side/=np.linalg.norm(side);normal=np.cross(side,axis);settings={}
        basis=np.column_stack([side,axis,normal])@rotation(settings.get("rotation_degrees",[0,0,0]))
        placement=np.eye(4)
        size=min(length,.12) if preset['asset_id']!='movement_arrow' else min(.05,length*.7)
        placement[:3,:3]=basis*size
        placement[:3,3]=start if preset['motion']=='translate' else end
        result['projection']={'camera_from_marker':np.asarray(camera_from_marker).ravel().tolist(),
            'intrinsics':np.asarray(intrinsics).ravel().tolist(),'distortion':np.asarray(distortion).ravel().tolist()}
        result['asset']={'asset_id':preset['asset_id'],'marker_from_asset':placement.ravel().tolist(),
            'motion':preset['motion'],'translation_m':delta.tolist() if preset['motion']=='translate' else [0.,0.,0.]}
        if preset.get('presentation_id'):
            if library is None:
                from manual2ar.resources import ResourceStore
                from manual2ar.visuals.library import VisualAssetLibrary
                library=VisualAssetLibrary(ResourceStore.configured().path('visual.guidance.catalog'))
            result['presentation']=library.compose(preset['presentation_id'],points,basis,work if active_machine else None)
            components={c['id']:c for c in (motion or {}).get('components',[])}
            for item in result['presentation']['instances']:
                item['rotation_sign']=motion['rotation_sign'] if motion and (active_machine or not settings) else settings.get('rotation_sign',1)
                # Tightening clips show one bounded stroke, never a required turn count.
                item['rotation_scale']=motion['rotation_degrees']/360 if motion else 1
                component=components.get(item['id'])
                if component:
                    item.update(visible=component['visible'],playing=component['playing'],speed=component['speed'])
                    if component['rotation_sign']:item['rotation_sign']=component['rotation_sign']
                    component_placement=np.array(item['reference_from_asset']).reshape(4,4)
                    component_placement[:3,:3]=component_placement[:3,:3]@rotation(component['rotation_degrees'])*component['scale']
                    # Offsets use the printer work frame when active; model rotation never turns the path.
                    offset=np.array(component['offset_mm'])/1000
                    component_placement[:3,3]+=(work if active_machine else basis)@offset
                    item['reference_from_asset']=component_placement.ravel().tolist()
            result['duration_seconds']=result['presentation']['duration_seconds']
            if motion:
                result['duration_seconds']=motion['duration_seconds'];result['presentation']['duration_seconds']=motion['duration_seconds']
                result['motion_parameters']=motion
            if active_machine:
                result['machine_frame_id']=machine['frame_id']
                label+=' · '+('+' if motion['direction']==1 else '−')+motion['axis']
        result['axes']=axes(placement[:3,3],basis,camera_from_marker,intrinsics,distortion)
    brief={'holder.base':'对准底座螺丝，按官方说明固定','holder.slide':'对准导向槽，从上往下滑入'}.get(action['action_id'],'')
    result['text_labels']=[{'id':action['action_id'],'text':label[:50],'brief':brief,'position_m':points[1].tolist()}]
    if action['chapter_id']=='U7':result['text_labels']=[]
    return GuidanceVisual(**result,label=label).model_dump()
