"""Portable visual guidance: authored assets and animation, independent of task checks/AR SDKs."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
import numpy as np


class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)


class Track(Strict):
    kind:Literal['rotate','path','opacity']
    target:str='*'
    axis:list[float]=Field(default_factory=lambda:[0.,1.,0.],min_length=3,max_length=3)
    pivot_m:list[float]=Field(default_factory=lambda:[0.,0.,0.],min_length=3,max_length=3)
    degrees:float=Field(default=0,ge=-360,le=360)
    start:float=Field(default=0,ge=0,lt=1)
    end:float=Field(default=1,gt=0,le=1)
    easing:Literal['linear','smoothstep']='linear'
    from_value:float=Field(default=1,ge=0,le=1)
    to_value:float=Field(default=1,ge=0,le=1)

    @model_validator(mode='after')
    def interval(self):
        if self.end<=self.start or np.linalg.norm(self.axis)<1e-6:raise ValueError('Invalid animation interval or axis')
        return self


class Clip(Strict):
    id:str=Field(pattern=r'^[a-z][a-z0-9_.-]{0,79}$')
    tracks:list[Track]=Field(default_factory=list,max_length=16)


class MeshReference(Strict):
    path:str=Field(pattern=r'^meshes/[a-z0-9_.-]+\.json$')
    sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    triangles:int=Field(gt=0,le=2400)
    vertices:int=Field(gt=0,le=7200)


class Anchor(Strict):
    id:str
    position_m:list[float]=Field(min_length=3,max_length=3)


class AssetDefinition(Strict):
    id:str=Field(pattern=r'^[a-z][a-z0-9_.-]{0,79}$')
    version:str=Field(default='1.0.0',pattern=r'^\d+\.\d+\.\d+$')
    label:str
    category:Literal['highlight','movement','gesture','tool','context']
    units:Literal['metres']='metres'
    geometry_accuracy:Literal['teaching_proxy']='teaching_proxy'
    nominal_axis_m:float=Field(gt=0,le=1)
    mesh:MeshReference
    anchors:list[Anchor]=Field(min_length=1,max_length=16)
    clips:list[Clip]=Field(min_length=1,max_length=16)
    source_recipe:str=Field(pattern=r'^recipes/[a-z0-9_.-]+\.json$')
    license:Literal['project-authored']='project-authored'


class Layer(Strict):
    printer_rotation_degrees:list[float]|None=Field(default=None,min_length=3,max_length=3)
    rotation_degrees:list[float]=Field(default_factory=lambda:[0.,0.,0.],min_length=3,max_length=3)
    reverse_with_rotation:bool=False
    id:str
    asset_id:str
    clip_id:str
    anchor:Literal['start','end']
    extent_ratio:float=Field(default=1,gt=0,le=2)
    minimum_extent_m:float=Field(default=.02,gt=0,le=.2)
    maximum_extent_m:float=Field(default=.12,gt=0,le=.2)
    opacity:float=Field(default=1,gt=0,le=1)


class PresentationDefinition(Strict):
    id:str
    label:str
    duration_seconds:float=Field(ge=.5,le=10)
    layers:list[Layer]=Field(min_length=1,max_length=8)
    source_url:str
    citation_ids:list[str]=Field(min_length=1)
    orientation_policy:Literal['authored_axis_marker_roll']='authored_axis_marker_roll'
    illustrative_only:Literal[True]=True


class AssetCatalog(Strict):
    schema_version:Literal['manual2ar-visual-library-v1']='manual2ar-visual-library-v1'
    library_id:str=Field(default='manual2ar.teaching',pattern=r'^[a-z][a-z0-9_.-]{0,79}$')
    version:str=Field(default='1.0.0',pattern=r'^\d+\.\d+\.\d+$')
    style_id:Literal['clear-instruction-v1']='clear-instruction-v1'
    coordinate_convention:Literal['right_handed_xyz_metres_functional_origin_positive_y']='right_handed_xyz_metres_functional_origin_positive_y'
    assets:list[AssetDefinition]=Field(min_length=1,max_length=1000)
    presentations:list[PresentationDefinition]=Field(min_length=1,max_length=1000)

    @model_validator(mode='after')
    def references(self):
        assets={a.id:a for a in self.assets}
        if len(assets)!=len(self.assets) or len({p.id for p in self.presentations})!=len(self.presentations):raise ValueError('Duplicate asset or presentation ID')
        for a in self.assets:
            if len({c.id for c in a.clips})!=len(a.clips):raise ValueError('Duplicate clip ID')
        for p in self.presentations:
            if len({i.id for i in p.layers})!=len(p.layers):raise ValueError('Duplicate layer ID')
            for layer in p.layers:
                if layer.asset_id not in assets or layer.clip_id not in {c.id for c in assets[layer.asset_id].clips}:raise ValueError('Unknown asset/clip reference')
                if layer.maximum_extent_m<layer.minimum_extent_m:raise ValueError('Invalid size interval')
        return self


class MeshPart(Strict):
    id:str
    vertices:list[float]=Field(min_length=9,max_length=21600)
    triangles:list[int]=Field(min_length=3,max_length=7200)
    color:list[float]=Field(min_length=4,max_length=4)

    @model_validator(mode='after')
    def geometry(self):
        if len(self.vertices)%3 or len(self.triangles)%3 or min(self.triangles)<0 or max(self.triangles)>=len(self.vertices)//3:raise ValueError('Invalid mesh topology')
        if any(not 0<=c<=1 for c in self.color) or max(abs(v) for v in self.vertices)>1:raise ValueError('Invalid color or metre scale')
        vertices=np.asarray(self.vertices).reshape(-1,3);tri=vertices[np.asarray(self.triangles).reshape(-1,3)]
        if np.any(np.linalg.norm(np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]),axis=1)<1e-12):raise ValueError('Degenerate triangle')
        return self


class AssetMesh(Strict):
    schema_version:Literal['manual2ar-asset-mesh-v1']='manual2ar-asset-mesh-v1'
    asset_id:str
    parts:list[MeshPart]=Field(min_length=1,max_length=32)


class VisualInstance(Strict):
    id:str
    asset_id:str
    asset_version:str
    mesh_sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    clip_id:str
    reference_from_asset:list[float]=Field(min_length=16,max_length=16)
    path_m:list[float]=Field(default_factory=lambda:[0.,0.,0.],min_length=3,max_length=3)
    opacity:float=Field(default=1,gt=0,le=1)
    rotation_sign:Literal[-1,1]=1
    rotation_scale:float=Field(default=1,ge=0,le=1)
    visible:bool=True
    playing:bool=True
    speed:float=Field(default=1,ge=.25,le=4)
    reverse_with_rotation:bool=False

    @model_validator(mode='after')
    def transform(self):
        t=np.asarray(self.reference_from_asset).reshape(4,4);r=t[:3,:3];s=np.linalg.norm(r,axis=0)
        if not np.allclose(t[3],[0,0,0,1]) or not np.allclose(s,s[0]) or s[0]<1e-5 or s[0]>100 or not np.allclose(r.T@r,np.eye(3)*s[0]**2,atol=1e-6) or np.linalg.det(r)<=0:raise ValueError('Placement must be positive uniform scale and rigid orientation')
        if np.linalg.norm(self.path_m)>.4:raise ValueError('Illustrative path too long')
        return self


class VisualPresentation(Strict):
    schema_version:Literal['manual2ar-visual-presentation-v1']='manual2ar-visual-presentation-v1'
    library_id:str
    library_version:str
    catalog_sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    presentation_id:str
    reference_space_id:str=Field(default='calibrated-marker',min_length=1,max_length=100)
    duration_seconds:float=Field(ge=.5,le=10)
    illustrative_only:Literal[True]=True
    instances:list[VisualInstance]=Field(min_length=1,max_length=8)


class VisualTextLabel(Strict):
    id:str=Field(min_length=1,max_length=80)
    text:str=Field(min_length=1,max_length=50)
    brief:str=Field(default='',max_length=80)
    source:Literal['official_instruction','vlm_advice']='official_instruction'
    kind:Literal['component','context']='component'
    state:Literal['instruction','awaiting_check','passed','needs_attention']='instruction'
    reference_space_id:Literal['calibrated-marker']='calibrated-marker'
    position_m:list[float]=Field(min_length=3,max_length=3)

    @model_validator(mode='after')
    def local_anchor(self):
        if np.linalg.norm(self.position_m)>1:raise ValueError('Text anchor outside calibrated work area')
        return self
