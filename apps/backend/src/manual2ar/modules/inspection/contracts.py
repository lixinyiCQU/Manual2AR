"""Module-three wire contracts. A semantic finding and a display mask are independent."""
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator
from manual2ar_contracts.identity import FrameIdentity

class Strict(BaseModel):model_config=ConfigDict(extra='forbid')

class Region(Strict):
    found:bool
    confidence:float=Field(ge=0,le=1)
    bbox_0_1000:list[int]|None=Field(default=None,description='Tight axis-aligned box of this target in CURRENT image, [left,top,right,bottom], normalized 0..1000; null if not found.')
    target_point_0_1000:list[int]|None=Field(default=None,description='Positive segmentation point on a visible pixel of THIS target. For plate choose bare exposed plate, never an object on it or the box center by default.')
    evidence:str=Field(max_length=1200)
    @model_validator(mode='after')
    def geometry(self):
        if self.found:
            b=self.bbox_0_1000;p=self.target_point_0_1000
            if not b or len(b)!=4 or not 0<=b[0]<b[2]<=1000 or not 0<=b[1]<b[3]<=1000:raise ValueError('Invalid box')
            if p is not None and (len(p)!=2 or not b[0]<=p[0]<=b[2] or not b[1]<=p[1]<=b[3]):raise ValueError('Invalid foreground point')
        return self

class Plate(Region):
    polygon_0_1000:list[list[int]]=Field(default_factory=list,max_length=8,description='Ordered actual outer plate boundary in the current perspective, often a trapezoid. Never substitute the axis-aligned box corners. May encompass regions occluded by objects; not every interior pixel is bare plate.')
    @model_validator(mode='after')
    def polygon(self):
        if self.polygon_0_1000 and (len(self.polygon_0_1000)<3 or any(len(p)!=2 or any(v<0 or v>1000 for v in p) for p in self.polygon_0_1000)):raise ValueError('Invalid plate polygon')
        return self

class Anomaly(Region):
    kind:Literal['foreign_object','residue']
    description:str=Field(min_length=1,max_length=300)
    on_plate:Literal['yes','no','uncertain']

class Observation(Strict):
    plate:Plate
    coverage:Literal['full','partial','uncertain']
    surface_assessment:Literal['clear','anomaly','uncertain']
    confidence:float=Field(ge=0,le=1)
    view_issues:list[Literal['toolhead_upper_left','cropped','blur','glare','other_occlusion','unknown']]=Field(default_factory=list,max_length=6)
    visible_surface_assessment:Literal['clear','anomaly','uncertain']|None=None
    anomalies:list[Anomaly]=Field(max_length=7)
    limitations:list[str]=Field(default_factory=list,max_length=12)
    next_action:str=Field(max_length=1200)

class Begin(Strict):
    task_id:str='plate_surface'
    provider:Literal['opencv','sam31_cutie']='opencv'
    source:Literal['camera','static']='camera'

class Frame(FrameIdentity):
    image_base64:str=Field(min_length=32,max_length=2800000)
    source_sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    client_frame_id:int=Field(ge=1,le=10000000)
    check_id:str|None=Field(default=None,max_length=60)

class StartCheck(Frame):
    request_id:str=Field(pattern=r'^[a-f0-9]{32}$')

class ClientEvent(Strict):
    event:Literal['camera.started','camera.stopped','monitor.started','monitor.stopped','frontend.render','frontend.stale_hidden','frontend.performance']
    data:dict=Field(default_factory=dict)

class SaveEvidence(Strict):
    check_id:str=Field(pattern=r'^check_[a-f0-9]{16}$')

class ConfirmOcclusion(Strict):
    check_id:str=Field(pattern=r'^check_[a-f0-9]{16}$')
    inspection_source_sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    confirmed:Literal[True]
