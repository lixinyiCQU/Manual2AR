"""Optional, frozen-photo semantic preview. Never writes metric placements."""
import base64
import json
from typing import Literal
import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator
from manual2ar_contracts.perception import GuidanceTarget
from manual2ar_perception.segmentation import ComponentMaskTracker


class LocatedTarget(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    action_id:str
    target_id:str
    status:Literal['found','unseen','uncertain']
    confidence:float=Field(ge=0,le=1)
    bbox_0_1000:list[int]=Field(max_length=4)
    foreground_point_0_1000:list[int]=Field(max_length=2)

    @model_validator(mode='after')
    def geometry(self):
        if self.status=='found':
            if len(self.bbox_0_1000)!=4 or len(self.foreground_point_0_1000)!=2:
                raise ValueError('A found target needs a box and an interior foreground point')
            x,y,r,b=self.bbox_0_1000;px,py=self.foreground_point_0_1000
            if not(0<=x<r<=1000 and 0<=y<b<=1000 and x<px<r and y<py<b):
                raise ValueError('Invalid XYXY box or foreground point')
        return self


def prompt_for(action,instance):
    binding={'action_id':action['action_id'],'target_id':instance['id'],
        'official_instruction':action['instruction'],'official_quote':action['official_text'],
        'target_components':action['target_components'],'selected_target':instance['label'],
        'tool_type':action['tool_type']}
    return ('Locate the CURRENTLY VISIBLE target for this Bambu Lab A1 mini instruction. '
        'This request helps a learner FIND the location; it is NOT installation verification. '
        'Do not judge completion, torque or tool safety; do not infer metric 3D positions. '
        'For screws choose the selected individual screw only if visually distinguishable. '
        'For a slot highlight the slot; for foam/tie highlight only actual packaging. '
        'Never identify wiring as a transport tie. If the target has already been removed, '
        'is occluded, or the selected screw cannot be disambiguated, return unseen/uncertain '
        'with empty arrays. Do not invent a location. '
        'bbox_0_1000 is [left,top,right,bottom], top-left origin, normalized 0..1000. '
        'foreground_point_0_1000 must lie INSIDE visible target material and the box. '
        'Echo action_id and target_id exactly. Binding: '+json.dumps(binding,ensure_ascii=False))


def locate(client,config,raw,action,instance,folder):
    prompt=prompt_for(action,instance)
    (folder/'input.jpg').write_bytes(raw);(folder/'prompt.txt').write_text(prompt,encoding='utf-8')
    answer=LocatedTarget.model_validate(client.chat_structured(prompt=prompt,
        schema=LocatedTarget.model_json_schema(),images_base64=[base64.b64encode(raw).decode()],
        max_tokens=min(1600,config['verification']['max_tokens'])))
    if (answer.action_id,answer.target_id)!=(action['action_id'],instance['id']):
        raise ValueError('Grounding belongs to another action or target')
    if answer.confidence<config['verification']['minimum_confidence']:
        answer=answer.model_copy(update={'status':'uncertain','bbox_0_1000':[],'foreground_point_0_1000':[]})
    pixels=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR);height,width=pixels.shape[:2]
    result={**answer.model_dump(),'width':width,'height':height,'box_lines':[],'outlines':[],
        'purpose':'localization_preview','coordinate_space':'image_pixels','metric_placement':False,
        'segmentation':'not_requested'}
    if answer.status=='found':
        x,y,r,b=answer.bbox_0_1000;box=[round(x*width/1000),round(y*height/1000),round(r*width/1000),round(b*height/1000)]
        x,y,r,b=box
        corners=[{'x':x,'y':y},{'x':r,'y':y},{'x':r,'y':b},{'x':x,'y':b}]
        result['box_lines']=[{'a':corners[i],'b':corners[(i+1)%4]} for i in range(4)]
        mask=ComponentMaskTracker.seeded_mask(pixels,box,GuidanceTarget(expected_component_id=action['action_id'],target_point_0_1000=answer.foreground_point_0_1000))
        cv2.imwrite(str(folder/'mask.png'),mask)
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        for contour in sorted(contours,key=cv2.contourArea,reverse=True)[:8]:
            if cv2.contourArea(contour)<4:continue
            approx=cv2.approxPolyDP(contour,max(1,cv2.arcLength(contour,True)*.005),True)
            result['outlines'].append({'points':[{'x':int(p[0]),'y':int(p[1])} for p in approx[:,0]]})
        result['segmentation']='opencv_seeded_preview' if result['outlines'] else 'unavailable'
    (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
