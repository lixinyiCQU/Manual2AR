"""A direction-only illustration from known base points, never a recovered hidden slot."""
import numpy as np
from .printing import MARKER_ID, MARKER_LENGTH

SLIDE_NOTE='滑入方向示意以底座参考点为终点，不代表隐藏插槽、卡扣或实际行程；请对照官方图操作。'


def slide_illustration(targets,machine,distance_mm=60):
    if not machine:return None
    bases=[targets.get(k) for k in ('holder.base','holder.base::second')]
    if not all(bases):return None
    try:
        work=np.asarray(machine['marker_from_machine'],dtype=float).reshape(4,4)
        ends=[]
        for target in bases:
            if target.get('marker_id')!=MARKER_ID or target.get('marker_length_m')!=MARKER_LENGTH:return None
            if target.get('machine_frame_id') and target['machine_frame_id']!=machine['frame_id']:return None
            points=np.asarray(target['points_m'],dtype=float)
            if points.shape!=(2,3) or not np.isfinite(points).all() or np.max(np.linalg.norm(points,axis=1))>1:return None
            ends.append(points[1])
        delta=work[:3,:3].T@(ends[0]-ends[1])
        if not .005<delta[2]<.12 or max(abs(delta[:2]))>.02:return None
        if not 8<=distance_mm<=200:return None
        end=(ends[0]+ends[1])/2
        start=end+work[:3,2]*distance_mm/1000
        return {'schema_version':'manual2ar-spatial-target-v1','action_id':'holder.slide','target_id':'main',
            'target_label':'底座参考点 · 滑入方向示意','points_m':[start.tolist(),end.tolist()],
            'marker_id':MARKER_ID,'marker_length_m':MARKER_LENGTH,'machine_frame_id':machine['frame_id'],
            'placement_method':'base_reference_illustration','illustrative_only':True,
            'derived_from':['holder.base','holder.base::second'],'placement_note':SLIDE_NOTE}
    except (KeyError,ValueError,TypeError):return None
