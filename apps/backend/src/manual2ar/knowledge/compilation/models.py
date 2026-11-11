"""Compiler intermediates; runtime ProcedureDocument and ObservationNode stay unchanged."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field


ComponentName = Annotated[str, Field(pattern=r'^(source|target):\S.{0,159}$')]


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Claim(Strict):
    text: str = Field(min_length=1, max_length=1200)
    origin: Literal['explicit', 'inferred', 'observation_policy']
    citation_ids: list[str] = Field(min_length=1, max_length=12)
    rationale: str = Field(min_length=1, max_length=600)
    image_ids: list[str] = Field(default_factory=list, max_length=8)


class ActionEvidence(Strict):
    action_id: str = Field(pattern=r'^[A-Za-z][A-Za-z0-9_-]{0,39}$')
    instruction: Claim
    target_components: list[ComponentName] = Field(min_length=1, max_length=12)


class ExtractedActions(Strict):
    actions: list[ActionEvidence] = Field(min_length=1, max_length=40)
    limitations: list[Claim] = Field(default_factory=list, max_length=40)


class DraftState(Strict):
    action_id: str
    instruction: Claim
    preconditions: list[Claim] = Field(default_factory=list, max_length=12)
    postconditions: list[Claim] = Field(min_length=1, max_length=12)
    wrong_states: list[Claim] = Field(default_factory=list, max_length=12)
    target_components: list[ComponentName] = Field(min_length=1, max_length=12)
    warnings: list[Claim] = Field(default_factory=list, max_length=12)


class DraftGraph(Strict):
    states: list[DraftState] = Field(min_length=1, max_length=40)
    limitations: list[Claim] = Field(default_factory=list, max_length=40)


class DraftObservation(Strict):
    action_id: str
    postcondition_index: int = Field(ge=0)
    component_ids: list[ComponentName] = Field(min_length=1, max_length=12)
    viewpoint: Literal['front', 'rear', 'left', 'right', 'top', 'bottom', 'close_up', 'overview']
    capture_instruction: Claim
    evidence_type: Literal['presence', 'connection', 'position', 'orientation', 'display', 'relation']
    visualization: Literal['box', 'mask', 'arrow', 'polyline', 'none']
    verification_channel: Literal['vision', 'sensor', 'manual']
    requires_same_frame: bool
    visibility_limit: Claim


class DraftObservations(Strict):
    observations: list[DraftObservation] = Field(min_length=1, max_length=240)


class DirectDraft(DraftGraph):
    observations: list[DraftObservation] = Field(min_length=1, max_length=240)
