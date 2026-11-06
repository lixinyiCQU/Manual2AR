from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from manual2ar_contracts.spatial import CaptureSnapshot
from manual2ar_contracts.machine_frame import MotionParameters


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Begin(Strict):
    visual_client_revision:str=Field(default='',max_length=80)
    tutorial_run_id: str = Field(default='', pattern=r'^([a-f0-9]{32})?$')
    mode: Literal['camera', 'replay'] = 'camera'
    camera_id: str = Field(pattern=r'^[a-zA-Z0-9_.-]{1,64}$')
    rig_id: str = Field(default='a1-mini', pattern=r'^[a-zA-Z0-9_.-]{1,64}$')
    reuse_targets: bool = Field(default=False, strict=True)


class Frame(Strict):
    snapshot:CaptureSnapshot | None = None
    target_id:str=Field(default='main',pattern=r'^[a-z][a-z0-9_]{0,31}$')
    client_frame_id: int = Field(ge=1)
    image_base64: str = Field(min_length=32, max_length=3_000_000)
    source_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    action_id: str = Field(min_length=1, max_length=100)
    calibration_sample: bool = Field(default=False, strict=True)


class Pixel(Strict):
    x: float = Field(ge=0, le=1920)
    y: float = Field(ge=0, le=1080)


class Author(Strict):
    target_id:str=Field(default='main',pattern=r'^[a-z][a-z0-9_]{0,31}$')
    action_id: str = Field(min_length=1, max_length=100)
    first_frame: int = Field(ge=1)
    second_frame: int = Field(ge=1)
    first_points: list[Pixel] = Field(min_length=2, max_length=2)
    second_points: list[Pixel] = Field(min_length=2, max_length=2)


class Save(Strict):
    candidate_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    confirmed: Literal[True]


class Verify(Strict):
    target_id:str=Field(default='main',pattern=r'^[a-z][a-z0-9_]{0,31}$')
    action_id: str = Field(min_length=1, max_length=100)
    client_frame_id: int = Field(ge=1)


class Interaction(Strict):
    event_id:str=Field(pattern=r'^[a-f0-9]{32}$')
    action_id:str=Field(min_length=1,max_length=100)
    target_id:str=Field(default='main',pattern=r'^[a-z][a-z0-9_]{0,31}$')
    name:Literal['play','pause','replay','animation_finished','auto_started','auto_resumed','user_marked','target_selected','tracking_hidden','render_ready']
    visible_triangles:int=Field(default=0,ge=0,le=25000)
    renderer_id:str=Field(default='',max_length=120)
    client_frame_id:int=Field(ge=0)
    source_sha256:str=Field(default='',pattern=r'^([a-f0-9]{64})?$')
    progress:float=Field(default=0,ge=0,le=1)
    request_ms:float=Field(default=0,ge=0,le=300000)
    presentation_fps:float=Field(default=0,ge=0,le=240)


class Orientation(Strict):
    action_id:str=Field(min_length=1,max_length=100)
    target_id:str=Field(default='main',pattern=r'^[a-z][a-z0-9_]{0,31}$')
    rotation_degrees:list[float]=Field(min_length=3,max_length=3)
    rotation_sign:Literal[-1,1]=1


class MachineAuthor(Strict):
    first_frame:int=Field(ge=1)
    second_frame:int=Field(ge=1)
    first_points:list[Pixel]=Field(min_length=3,max_length=3)
    second_points:list[Pixel]=Field(min_length=3,max_length=3)


class MotionCommand(Strict):
    action_id:str=Field(min_length=1,max_length=100)
    parameters:MotionParameters


class ReuseSaved(Strict):
    confirmed:Literal[True]


class PrintedReference(Strict):
    client_frame_id:int=Field(ge=1)
    placement_confirmed:Literal[True]


class AutomaticPair(Strict):
    action_id:Literal['holder.base','holder.slide']
    first_view:str=Field(pattern=r'^[a-f0-9]{32}$')
    second_view:str=Field(pattern=r'^[a-f0-9]{32}$')
    second_frame:int=Field(ge=1)
