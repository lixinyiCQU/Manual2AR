"""Additive desktop guidance visualization contract, independent of tutorial checks."""
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field


class Pixel(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    x:float
    y:float


class Line(BaseModel):
    model_config=ConfigDict(extra='forbid')
    a:Pixel
    b:Pixel


class GuidanceVisual(BaseModel):
    model_config=ConfigDict(extra='forbid')
    schema_version:Literal['manual2ar-spatial-visual-v1']='manual2ar-spatial-visual-v1'
    kind:Literal['slide','fasten','align','cut','highlight']
    label:str=Field(min_length=1,max_length=60)
    anchor:Pixel
    trajectory:list[Pixel]=Field(default_factory=list,max_length=65)
    tool_lines:list[Line]=Field(default_factory=list,max_length=64)
    # The animation is explanatory, not an observation of a user's movement.
    illustrative_only:Literal[True]=True
    duration_seconds:float=Field(default=3,ge=1,le=10,allow_inf_nan=False)
