"""Evidence overlays use the same accepted masks and plate-scope flags as Unity."""
import cv2
import numpy as np


def save_overlay(path,image,rows,masks):
    canvas=cv2.imdecode(np.frombuffer(image,np.uint8),cv2.IMREAD_COLOR)
    for row in rows:
        if row.get('plate_relation')=='outside':continue
        mask=masks.get(row['id'])
        if mask is not None:
            color=np.array([230,175,30] if row['kind']=='plate' else [60,60,245] if row['kind']=='foreign_object' else [0,190,255]);canvas[mask]=(canvas[mask]*.65+color*.35).astype(np.uint8)
        elif row.get('bbox_0_1000') and row['kind']!='plate':
            h,w=canvas.shape[:2];a,b,c,d=row['bbox_0_1000'];cv2.rectangle(canvas,(a*w//1000,b*h//1000),(c*w//1000,d*h//1000),(0,160,255),2)
    cv2.imwrite(str(path),canvas)
