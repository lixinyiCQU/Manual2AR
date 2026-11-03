"""Task-selected illustration assets. Geometry never supplies installation evidence."""
import numpy as np
from manual2ar_contracts.spatial import GuidanceVisual
from manual2ar_perception.spatial import visual_geometry


def compose(action, label, points, camera_from_marker, intrinsics, distortion):
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
        placement=np.eye(4)
        size=min(length,.12) if preset['asset_id']!='movement_arrow' else min(.05,length*.7)
        placement[:3,:3]=np.column_stack([side,axis,normal])*size
        placement[:3,3]=start if preset['motion']=='translate' else end
        result['projection']={'camera_from_marker':np.asarray(camera_from_marker).ravel().tolist(),
            'intrinsics':np.asarray(intrinsics).ravel().tolist(),'distortion':np.asarray(distortion).ravel().tolist()}
        result['asset']={'asset_id':preset['asset_id'],'marker_from_asset':placement.ravel().tolist(),
            'motion':preset['motion'],'translation_m':delta.tolist() if preset['motion']=='translate' else [0.,0.,0.]}
    return GuidanceVisual(**result,label=label).model_dump()
