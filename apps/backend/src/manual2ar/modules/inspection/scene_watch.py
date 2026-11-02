"""Suggest unclassified objects from persistent, unexplained plate-mask holes.

This is a current-frame geometric proposal, not a new semantic detector and not
evidence that the rest of the plate is clean. IDs never enter Cutie's memory.
"""
import cv2
import numpy as np

class PlateSceneWatch:
    def __init__(self,settings=None):
        self.settings=settings or {};self.previous=[];self.next_id=1;self.baseline=[]
    def reset(self):self.previous=[];self.next_id=1;self.baseline=[];self.known_regions=[]
    def prime(self,masks,objects=None):
        # Stable initial lettering/cutouts are not newly appeared objects.
        # Known anomalies are excluded from the baseline, so replacements at
        # their old positions can still generate a proposal after track loss.
        self.reset();self.baseline=self.update(masks,seed=True);self.previous=[]
        plate=masks.get('build_plate')
        if plate is not None and np.any(plate):
            h,w=plate.shape;px,py,pw,ph=cv2.boundingRect(np.asarray(plate,np.uint8))
            # Failed localization is still a known semantic finding. A hole at
            # that same plate-relative region is not evidence of a NEW object.
            # This never clears an anomaly or assigns it a new tracking identity.
            for obj in objects or []:
                box=obj.get('bbox_0_1000')
                if obj.get('kind')=='plate' or obj.get('tracking_ready') or not obj.get('found') or not box:continue
                a,b,c,d=box;self.known_regions.append(((a*w/1000-px)/pw,(b*h/1000-py)/ph,(c*w/1000-px)/pw,(d*h/1000-py)/ph))
    def update(self,masks,seed=False):
        if not self.settings.get('scene_watch_enabled',True):return []
        plate=masks.get('build_plate')
        if plate is None or not np.any(plate):self.previous=[];return []
        plate=np.asarray(plate,np.uint8);h,w=plate.shape
        contours,_=cv2.findContours(plate,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        if not contours:self.previous=[];return []
        outer=np.zeros_like(plate);cv2.drawContours(outer,[max(contours,key=cv2.contourArea)],-1,1,cv2.FILLED)
        inner=cv2.erode(outer,np.ones((3,3),np.uint8));holes=(inner>0)&(plate==0)
        for key,mask in masks.items():
            if key!='build_plate':holes&=cv2.dilate(np.asarray(mask,np.uint8),np.ones((5,5),np.uint8))==0
        count,labels,stats,centers=cv2.connectedComponentsWithStats(holes.astype(np.uint8),connectivity=8)
        px,py,pw,ph=cv2.boundingRect(outer)
        minimum=max(self.settings.get('scene_candidate_min_pixels',32),round(h*w*self.settings.get('scene_candidate_min_frame_ratio',.0002)))
        maximum=float(outer.sum())*.45
        candidates=[];used=set();required=self.settings.get('scene_candidate_confirm_frames',2)
        for index in sorted(range(1,count),key=lambda i:int(stats[i,cv2.CC_STAT_AREA]),reverse=True):
            x,y,bw,bh,area=map(int,stats[index])
            if not minimum<=area<=maximum:continue
            cx,cy=centers[index];position=((cx-px)/max(1,pw),(cy-py)/max(1,ph));prior=None
            if not seed and any(a<=position[0]<=c and b<=position[1]<=d for a,b,c,d in getattr(self,'known_regions',[])):continue
            relative_area=area/max(1,pw*ph)
            if not seed and any(np.linalg.norm(np.asarray(position)-b['position'])<.045 and .5<b['relative_area']/relative_area<2 for b in self.baseline):continue
            for i,p in enumerate(self.previous):
                if i not in used and np.linalg.norm(np.asarray(position)-p['position'])<.07:
                    prior=p;used.add(i);break
            identity=prior['id'] if prior else 'unclassified_'+str(self.next_id)
            if prior is None:self.next_id+=1
            candidates.append({'id':identity,'position':position,'relative_area':relative_area,'streak':prior['streak']+1 if prior else 1,
                'bbox_0_1000':[round(x/w*1000),round(y/h*1000),round((x+bw)/w*1000),round((y+bh)/h*1000)],
                'pixel_area':area,'proposal_source':'unexplained_plate_mask_hole','label_code':'unclassified_object'})
            if not seed and len(candidates)>=3:break
        self.previous=candidates
        if seed:return candidates
        return [{k:v for k,v in c.items() if k not in ('position','relative_area','streak')} for c in candidates if c['streak']>=required]
