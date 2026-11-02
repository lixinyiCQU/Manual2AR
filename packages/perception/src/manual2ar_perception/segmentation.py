"""New-task-only seeded GrabCut, using the original optical-flow tracker."""
from contextvars import ContextVar
import cv2
import numpy as np
from manual2ar_perception.opencv import OpenCvMaskTracker

mask_context=ContextVar("component_initial_mask",default=None)

class ComponentMaskTracker(OpenCvMaskTracker):
    provider_name = 'opencv-component-seeded-grabcut-lk'

    def _initial_mask(self, image, component_id, box, guidance_target=None):
        if not component_id.startswith('intro_'):
            return super()._initial_mask(image,component_id,box,guidance_target)
        mask=self.seeded_mask(image,box,guidance_target)
        folder=mask_context.get()
        if folder is not None: cv2.imwrite(str(folder/(component_id+'_initial_raw.png')),mask)
        return mask

    @staticmethod
    def seeded_mask(image,box,guidance_target):
        height,width = image.shape[:2]
        x1,y1,x2,y2 = box
        result = np.zeros((height,width),np.uint8)
        px,py = max(6,round((x2-x1)*.25)),max(6,round((y2-y1)*.25))
        left,top,right,bottom = max(0,x1-px),max(0,y1-py),min(width,x2+px),min(height,y2+py)
        crop = image[top:bottom,left:right]
        if min(crop.shape[:2]) < 6: return result
        labels = np.full(crop.shape[:2],cv2.GC_PR_BGD,np.uint8)
        labels[y1-top:y2-top,x1-left:x2-left] = cv2.GC_PR_FGD
        labels[:2,:] = labels[-2:,:] = cv2.GC_BGD
        labels[:,:2] = labels[:,-2:] = cv2.GC_BGD
        point = guidance_target.target_point_0_1000
        sx,sy = round(point[0]/1000*width)-left,round(point[1]/1000*height)-top
        if not (2 <= sx < crop.shape[1]-2 and 2 <= sy < crop.shape[0]-2): return result
        cv2.circle(labels,(sx,sy),max(1,round(min(x2-x1,y2-y1)*.02)),cv2.GC_FGD,-1)
        try:
            cv2.grabCut(crop,labels,None,np.zeros((1,65),np.float64),np.zeros((1,65),np.float64),4,cv2.GC_INIT_WITH_MASK)
        except cv2.error: return result
        mask = np.where((labels==cv2.GC_FGD)|(labels==cv2.GC_PR_FGD),255,0).astype(np.uint8)
        count,parts,stats,_ = cv2.connectedComponentsWithStats(mask)
        clean = np.zeros_like(mask)
        for k in range(1,count):
            if stats[k,cv2.CC_STAT_AREA] >= max(3,round((x2-x1)*(y2-y1)*.0003)):
                clean[parts==k] = 255
        result[top:bottom,left:right] = clean
        return result
