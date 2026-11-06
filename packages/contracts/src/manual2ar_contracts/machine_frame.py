"""Teaching work coordinates and motion parameters; never machine control commands."""
from typing import Literal
import re
import numpy as np
from pydantic import BaseModel,ConfigDict,Field,model_validator


class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)


class MachineFrame(Strict):
    schema_version:Literal['manual2ar-machine-frame-v1']='manual2ar-machine-frame-v1'
    reference_space_id:Literal['calibrated-marker']='calibrated-marker'
    marker_id:int
    marker_length_m:float=Field(gt=0,le=1)
    marker_from_machine:list[float]=Field(min_length=16,max_length=16)
    frame_id:str=Field(pattern=r'^[a-f0-9]{32}$')
    source_frame_sha256:list[str]=Field(min_length=1,max_length=2)
    placement_method:Literal['manual_two_view','printed_reference']='manual_two_view'
    reference_profile_id:str=Field(default='',max_length=80)
    quality:dict[str,float]
    illustrative_only:Literal[True]=True

    @model_validator(mode='after')
    def rigid(self):
        if len(self.source_frame_sha256)!=(1 if self.placement_method=='printed_reference' else 2):raise ValueError('Evidence count differs from placement method')
        if self.placement_method=='printed_reference' and not self.reference_profile_id:raise ValueError('Printed reference requires its profile ID')
        if any(not re.fullmatch('[a-f0-9]{64}',value) for value in self.source_frame_sha256):raise ValueError('Invalid source image identity')
        t=np.asarray(self.marker_from_machine).reshape(4,4);r=t[:3,:3]
        if not np.allclose(t[3],[0,0,0,1]) or not np.allclose(r.T@r,np.eye(3),atol=1e-6) or not np.isclose(np.linalg.det(r),1,atol=1e-6) or np.linalg.norm(t[:3,3])>1:
            raise ValueError('Machine frame must be a rigid right-handed metre transform')
        return self


class ComponentMotion(Strict):
    id:str=Field(pattern=r'^[a-z][a-z0-9_.-]{0,79}$')
    visible:bool=True
    playing:bool=True
    rotation_degrees:list[float]=Field(default_factory=lambda:[0.,0.,0.],min_length=3,max_length=3)
    offset_mm:list[float]=Field(default_factory=lambda:[0.,0.,0.],min_length=3,max_length=3)
    scale:float=Field(default=1,ge=.25,le=3)
    speed:float=Field(default=1,ge=.25,le=4)
    rotation_sign:Literal[-1,0,1]=0

    @model_validator(mode='after')
    def bounded(self):
        if any(abs(v)>180 for v in self.rotation_degrees) or any(abs(v)>100 for v in self.offset_mm):raise ValueError('Component rotation/offset exceeds teaching bounds')
        return self


class MotionParameters(Strict):
    schema_version:Literal['manual2ar-teaching-motion-v1']='manual2ar-teaching-motion-v1'
    enabled:bool=Field(default=True,strict=True)
    axis:Literal['X','Y','Z']='Z'
    direction:Literal[-1,1]=-1
    distance_mm:float=Field(default=60,ge=8,le=200)
    duration_seconds:float=Field(default=1.2,ge=.5,le=10)
    rotation_degrees:float=Field(default=360,ge=0,le=360)
    rotation_sign:Literal[-1,1]=1

    components:list[ComponentMotion]=Field(default_factory=list,max_length=8)

    @model_validator(mode='after')
    def unique_components(self):
        if len({v.id for v in self.components})!=len(self.components):raise ValueError('Duplicate component ID')
        return self
