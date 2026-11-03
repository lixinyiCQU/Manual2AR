"""Additive desktop guidance visualization contract, independent of tutorial checks."""
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator


class CaptureSnapshot(BaseModel):
    """Frozen RGB domain; optional native AR pose is never inferred from RGB.

    Matrices are row-major, metres, right-handed camera X right/Y down/Z forward.
    Native AR adapters must convert their own coordinate system explicitly.
    """
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    schema_version:Literal['manual2ar-capture-v1']='manual2ar-capture-v1'
    provider_id:Literal['desktop_rgb','synthetic','arkit']
    client_frame_id:int=Field(ge=1)
    source_sha256:str=Field(pattern=r'^[a-f0-9]{64}$')
    width:int=Field(ge=320,le=4096)
    height:int=Field(ge=240,le=4096)
    capture_monotonic_ms:float=Field(ge=0)
    pixel_domain:Literal['upright_unmirrored']='upright_unmirrored'
    reference_space_id:str=Field(default='',max_length=100)
    camera_intrinsics:list[float]=Field(default_factory=list,max_length=9)
    world_from_camera:list[float]=Field(default_factory=list,max_length=16)

    @model_validator(mode='after')
    def native_pose(self):
        if self.camera_intrinsics and len(self.camera_intrinsics)!=9:
            raise ValueError('Intrinsics require a row-major 3x3 matrix')
        if self.world_from_camera:
            import numpy as np
            if len(self.world_from_camera)!=16:raise ValueError('Pose requires a row-major 4x4 matrix')
            matrix=np.asarray(self.world_from_camera).reshape(4,4)
            if not np.allclose(matrix[3],[0,0,0,1]) or not np.allclose(matrix[:3,:3].T@matrix[:3,:3],np.eye(3),atol=1e-4) or not np.isclose(np.linalg.det(matrix[:3,:3]),1,atol=1e-4):
                raise ValueError('Pose must be a rigid right-handed transform')
        if self.provider_id=='arkit' and (not self.reference_space_id or not self.world_from_camera or not self.camera_intrinsics):
            raise ValueError('Native AR requires a reference space, intrinsics and frozen pose')
        return self


class Pixel(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    x:float
    y:float


class Line(BaseModel):
    model_config=ConfigDict(extra='forbid')
    a:Pixel
    b:Pixel


class SpatialProjection(BaseModel):
    """Frozen OpenCV projection, paired with the enclosing RGB frame identity."""
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    camera_from_marker:list[float]=Field(min_length=16,max_length=16)
    intrinsics:list[float]=Field(min_length=9,max_length=9)
    distortion:list[float]=Field(min_length=4,max_length=8)


class GuidanceAsset(BaseModel):
    """Metre placement; asset local origin is its functional tip, +Y into target."""
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    asset_id:Literal['hex_key','scissors','movement_arrow']
    marker_from_asset:list[float]=Field(min_length=16,max_length=16)
    motion:Literal['loosen','tighten','cut','translate','static']='static'
    translation_m:list[float]=Field(default_factory=lambda:[0.,0.,0.],min_length=3,max_length=3)


class GuidanceVisual(BaseModel):
    model_config=ConfigDict(extra='forbid')
    schema_version:Literal['manual2ar-spatial-visual-v1']='manual2ar-spatial-visual-v1'
    kind:Literal['slide','fasten','align','cut','highlight']
    label:str=Field(min_length=1,max_length=60)
    anchor:Pixel
    trajectory:list[Pixel]=Field(default_factory=list,max_length=65)
    tool_lines:list[Line]=Field(default_factory=list,max_length=64)
    # Additive: old clients retain their line reference; new clients project meshes.
    projection:SpatialProjection|None=None
    asset:GuidanceAsset|None=None
    # The animation is explanatory, not an observation of a user's movement.
    illustrative_only:Literal[True]=True
    duration_seconds:float=Field(default=1.2,ge=.5,le=10,allow_inf_nan=False)
