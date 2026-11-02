"""Plate inspection 1.0.0: semantic findings survive localization/display failures.

No color prior, per-class physical-size prior or initial-frame tracking fence.
The mask checks below only decide whether a proposed highlight is defensible.
"""
import cv2
import numpy as np

VERSION='plate-surface-v1.0.1'

def initial_mask_quality(state,settings):
    mask=state.mask
    height,width=mask.shape
    area=cv2.countNonZero(mask);ratio=area/max(1,width*height)
    if not area:return False,['segmentation_empty'],0.,0.
    reasons=[]
    # An unqualified all-foreground result supplies no boundary evidence.
    if area==width*height:reasons.append('segmentation_has_no_background')
    x1,y1,x2,y2=state.semantic_box
    containment=cv2.countNonZero(mask[y1:y2,x1:x2])/area
    if containment<settings['mask_prompt_containment_min']:reasons.append('mask_leaves_prompt_region')
    point=state.guidance_target.target_point_0_1000
    x=min(width-1,max(0,round(point[0]*width/1000)))
    y=min(height-1,max(0,round(point[1]*height/1000)))
    radius=max(1,round(min(x2-x1,y2-y1)*settings['mask_point_support_radius_ratio']))
    if not np.any(mask[max(0,y-radius):min(height,y+radius+1),max(0,x-radius):min(width,x+radius+1)]):
        reasons.append('target_point_not_supported_by_mask')
    return not reasons,reasons,ratio,containment
