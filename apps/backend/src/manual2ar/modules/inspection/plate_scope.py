"""Current-frame plate scope. Lost tracking alone never proves removal."""
from copy import deepcopy
import cv2
import numpy as np


def mask_scope(plate_mask, object_mask):
    """Conservative support envelope in the CURRENT image, including object holes.

    A convex hull preserves trapezoidal perspective instead of expanding the
    plate to its axis-aligned box. Missing masks, cropped edges or loss do not
    supply enough geometric evidence to newly declare removal.
    """
    if plate_mask is None or object_mask is None:return None
    plate=np.asarray(plate_mask,bool);obj=np.asarray(object_mask,bool)
    if plate.ndim!=2 or obj.shape!=plate.shape or not plate.any() or not obj.any() or plate.all():return None
    contours,_=cv2.findContours(plate.astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    points=np.concatenate(contours)
    x,y,w,h=cv2.boundingRect(points)
    if x==0 or y==0 or x+w==plate.shape[1] or y+h==plate.shape[0]:return None
    hull=cv2.convexHull(points)
    if len(hull)<3:return None
    envelope=np.zeros(plate.shape,np.uint8);cv2.fillConvexPoly(envelope,hull,1)
    # Avoid treating a small contour/registration error as a removed object.
    envelope=cv2.dilate(envelope,np.ones((5,5),np.uint8)).astype(bool)
    overlap=int(np.count_nonzero(obj&envelope))
    return {'basis':'current_plate_mask_hull','overlap_pixels':overlap,
            'object_pixels':int(obj.sum()),'outside':overlap==0}


def disjoint_boxes(a,b):
    if a is None or b is None or len(a)!=4 or len(b)!=4:return False
    if not (a[0]<a[2] and a[1]<a[3] and b[0]<b[2] and b[1]<b[3]):return False
    return a[2]<=b[0] or b[2]<=a[0] or a[3]<=b[1] or b[3]<=a[1]


def update_scope(rows,masks,removed):
    plate=next((o for o in rows if o['kind']=='plate' and o['tracking_ready']),None)
    before=set(removed)
    for row in rows:
        if row['kind']=='plate':continue
        if plate is not None and row['tracking_ready']:
            outside=disjoint_boxes(row.get('bbox_0_1000'),plate.get('bbox_0_1000'))
            evidence=mask_scope(masks.get(plate['id']),masks.get(row['id']))
            if evidence is not None:
                outside=evidence['outside'];row['scope_evidence']=evidence
            elif masks.get(plate['id']) is not None:
                # A current but incomplete plate mask cannot certify off-plate.
                outside=False
            if outside:removed.add(row['id'])
            else:removed.discard(row['id'])
        if row['id'] in removed:
            row.update(plate_relation='outside',removal_state='removed',tracker_ready=row['tracking_ready'],tracking_ready=False)
            masks.pop(row['id'],None)
        else:row['plate_relation']='on_or_overlapping_plate' if row['tracking_ready'] and plate is not None else 'unknown'
    return before!=removed


def scope_decision(original,removed,plate_usable):
    value=deepcopy(original);known=set(value.get('semantic_anomaly_ids',[]));resolved=known&removed
    value.update(snapshot_semantic_anomaly_ids=sorted(known),removed_anomaly_ids=sorted(resolved),semantic_anomaly_ids=sorted(known-resolved))
    if known and known==resolved:
        if plate_usable and not value.get('unresolved'):
            value.update(status='known_anomalies_removed',message='检测到的异物或残料已移出打印板范围。',scope='当前帧跟踪确认已检出的目标移出打印板范围；本次未重新调用VLM。')
        else:value.update(status='insufficient_evidence',message='已移出检测目标，当前板面仍需确认。')
    return value
