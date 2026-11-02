from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class ComponentBox(BaseModel):
    component_id: str = Field(min_length=1)
    bbox_0_1000: list[int] = Field(min_length=4, max_length=4)
    observation: str = ""

    @field_validator("bbox_0_1000")
    @classmethod
    def validate_box(cls, box: list[int]) -> list[int]:
        if any(value < 0 or value > 1000 for value in box):
            raise ValueError("bounding-box coordinates must be in [0, 1000]")
        if box[0] >= box[2] or box[1] >= box[3]:
            raise ValueError("bounding box must have positive width and height")
        return box

class GuidanceTarget(BaseModel):
    """Explicit contract between procedure semantics and visual grounding.

    A detector box is only a proposal.  This object records which semantic
    object the mask is allowed to represent, which neighbouring objects are
    forbidden, and how the approved result may be rendered.
    """

    expected_component_id: str = Field(min_length=1)
    semantic_role: Literal["target", "source", "forbidden", "path"] = "target"
    target_slot_id: int | None = Field(default=None, ge=1, le=4)
    render_mode: Literal[
        "mask", "outline", "billboard", "arrow", "polyline", "none"
    ] = "mask"
    forbidden_component_ids: list[str] = Field(default_factory=list)
    target_point_0_1000: list[int] | None = None
    expected_area_ratio_min: float = Field(default=0.0005, ge=0.0, le=1.0)
    expected_area_ratio_max: float = Field(default=0.30, ge=0.0, le=1.0)
    forbidden_regions_0_1000: list[list[int]] = Field(default_factory=list)

    @field_validator("target_point_0_1000")
    @classmethod
    def validate_target_point(cls, point: list[int] | None) -> list[int] | None:
        if point is None:
            return None
        if len(point) != 2 or any(value < 0 or value > 1000 for value in point):
            raise ValueError("target point must contain two coordinates in [0, 1000]")
        return point

    @field_validator("forbidden_regions_0_1000")
    @classmethod
    def validate_forbidden_regions(cls, regions: list[list[int]]) -> list[list[int]]:
        for region in regions:
            ComponentBox(component_id="forbidden-region", bbox_0_1000=region)
        return regions

    @model_validator(mode="after")
    def validate_expected_area_range(self) -> "GuidanceTarget":
        if self.expected_area_ratio_min >= self.expected_area_ratio_max:
            raise ValueError("expected mask area minimum must be below maximum")
        return self

class TrackedComponent(BaseModel):
    component_id: str = Field(min_length=1)
    status: Literal["tracking", "lost"]
    quality: float = Field(ge=0.0, le=1.0)
    bbox_0_1000: list[int] = Field(min_length=4, max_length=4)
    polygon_0_1000: list[list[int]] = Field(default_factory=list)
    centroid_0_1000: list[int] = Field(min_length=2, max_length=2)
    overlay_png_base64: str = ""
    provider: str = Field(min_length=1)
    requires_redetection: bool = False
    mask_quality_passed: bool = True
    mask_quality_reasons: list[str] = Field(default_factory=list)
    mask_area_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    prompt_containment: float = Field(default=1.0, ge=0.0, le=1.0)
    overlay_semantic: Literal[
        "next_action", "verified", "insufficient", "error"
    ] = "next_action"
    frame_index: int = Field(default=0, ge=0)
    world_anchor_status: Literal[
        "not_reported", "client_pending", "anchored", "lost", "relocalizing"
    ] = "not_reported"
    drift_ratio: float = Field(default=0.0, ge=0.0)
    relocalization_count: int = Field(default=0, ge=0)
