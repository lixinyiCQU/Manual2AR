"""Shared SAM initialization evidence and strict shape/identity validation."""
from pathlib import Path
import numpy as np
from PIL import Image
from ..artifacts import dump,validate_targets

def exclusive_initial_masks(masks):
    """Cutie memory takes mutually exclusive visible instances, not amodal masks.

    Keep smaller instances in overlap regions before larger supporting surfaces.
    Return in the original target order: list position is the remote object ID.
    """
    values=[np.asarray(m,bool) for m in masks]
    if not values or len({m.shape for m in values})!=1:raise ValueError('Initial masks differ in shape')
    occupied=np.zeros_like(values[0]);output=[None]*len(values)
    for i in sorted(range(len(values)),key=lambda i:int(values[i].sum())):
        output[i]=values[i]&~occupied;occupied|=values[i]
    return output,dict(policy='smaller-visible-instances-first-v1',
        overlap_pixels=int((np.sum(values,axis=0)>1).sum()),
        input_pixels=[int(m.sum()) for m in values],output_pixels=[int(m.sum()) for m in output])


def select_candidate(masks,scores,height,width):
    masks=np.asarray(masks);scores=np.asarray(scores,dtype=np.float64).reshape(-1)
    if masks.ndim==2:masks=masks[None]
    if masks.shape!=(len(scores),height,width) or len(scores)==0:raise ValueError('Initializer mask/score shape mismatch')
    if not np.isfinite(masks).all() or not np.isfinite(scores).all():raise ValueError('Nonfinite initialization output')
    best=int(np.argmax(scores));mask=masks[best]>0
    return mask,best,scores.tolist()


def save_initialization(folder,targets,masks,scores,metadata,prefix='initial'):
    targets=validate_targets(targets);folder=Path(folder);raw=folder/prefix;raw.mkdir(exist_ok=True)
    if len(masks)!=len(targets) or len(scores)!=len(targets):raise ValueError('Initializer target identity mismatch')
    shapes={np.asarray(m).shape for m in masks}
    if len(shapes)!=1 or len(next(iter(shapes)))!=2:raise ValueError('Initializer mask dimensions differ')
    height,width=next(iter(shapes));rows=[]
    for target,mask,score in zip(targets,masks,scores):
        mask=np.asarray(mask)
        if not np.isfinite(mask).all():raise ValueError('Nonfinite initial mask')
        mask=mask.astype(bool);identity=target['component_id']
        Image.fromarray(mask.astype(np.uint8)*255).save(raw/(identity+'.png'))
        x,y=target['target_point_0_1000'];x=min(width-1,round(x*width/1000));y=min(height-1,round(y*height/1000))
        a,b,c,d=target['bbox_0_1000'];a,c=round(a*width/1000),round(c*width/1000);b,d=round(b*height/1000),round(d*height/1000)
        rows.append(dict(component_id=identity,area_ratio=float(mask.mean()),point_in_mask=bool(mask[y,x]),
            mask_box_containment=float(mask[b:d,a:c].sum()/max(1,mask.sum())),model_score=score,
            note='Geometry and model score are diagnostics, not human-validated accuracy'))
    value=dict(**metadata,targets=rows,overlap_pixels=int((np.sum(masks,axis=0)>1).sum()))
    dump(folder/'initialization.json',value)
    return value
