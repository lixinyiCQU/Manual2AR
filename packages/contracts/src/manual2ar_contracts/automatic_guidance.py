"""Semantic observations and declarative recipes; geometry alone resolves metric placement."""
from typing import Literal
from pydantic import Field, model_validator
from .machine_frame import Strict


class FunctionalPoint(Strict):
    id: Literal['screw_upper', 'screw_lower', 'guide_top', 'guide_bottom']
    status: Literal['found', 'unseen', 'uncertain']
    point_0_1000: list[float] = Field(max_length=2)
    confidence: float = Field(ge=0, le=1)
    evidence: str = Field(min_length=1, max_length=300)

    @model_validator(mode='after')
    def coordinate(self):
        if self.status == 'found':
            if len(self.point_0_1000) != 2 or any(not 0 <= v <= 1000 for v in self.point_0_1000):
                raise ValueError('A visible feature requires a normalized image point')
        elif self.point_0_1000:
            raise ValueError('An unseen/uncertain feature has no usable coordinates')
        return self


class FunctionalObservation(Strict):
    points: list[FunctionalPoint] = Field(min_length=4, max_length=4)
    next_action: str = Field(max_length=500)

    @model_validator(mode='after')
    def unique(self):
        if {p.id for p in self.points} != {'screw_upper', 'screw_lower', 'guide_top', 'guide_bottom'}:
            raise ValueError('Return exactly the four distinct functional features')
        return self


class GuidanceRecipe(Strict):
    """All five visual categories share bindings; executable assets remain allow-listed."""
    id: str = Field(pattern=r'^[a-z][a-z0-9_.-]{0,79}$')
    category: Literal['highlight', 'movement', 'gesture', 'tool', 'context']
    action_id: str
    target_ids: list[str] = Field(min_length=1, max_length=8)
    feature_ids: list[str] = Field(min_length=1, max_length=8)
    presentation_id: str
    operation: Literal['highlight', 'tighten', 'translate', 'grasp', 'information']
    direction_source: Literal['printer_work_frame', 'observed_guide', 'none']
    citation_ids: list[str] = Field(min_length=1)
    illustrative_only: Literal[True] = True

    @model_validator(mode='after')
    def bindings(self):
        if len(self.target_ids)!=len(self.feature_ids) or len(set(self.target_ids))!=len(self.target_ids):
            raise ValueError('Each target requires exactly one feature binding')
        return self
