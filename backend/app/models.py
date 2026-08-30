from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


VerificationStatus = Literal[
    "not_started",
    "in_progress",
    "completed",
    "wrong_operation",
    "uncertain",
]


class ManualProvenance(BaseModel):
    page: int = Field(ge=1)
    section: str = Field(min_length=1)
    source_text: str | None = None


class ObservationNode(BaseModel):
    inspection_id: str = Field(min_length=1)
    condition: str = Field(min_length=1)
    component_ids: list[str] = Field(min_length=1)
    viewpoint: Literal[
        "front",
        "rear",
        "left",
        "right",
        "top",
        "bottom",
        "close_up",
        "overview",
    ] = "close_up"
    capture_instruction: str = Field(min_length=1)
    evidence_type: Literal[
        "presence",
        "connection",
        "position",
        "orientation",
        "display",
        "relation",
    ] = "presence"
    visualization: Literal[
        "box",
        "mask",
        "arrow",
        "polyline",
        "none",
    ] = "box"
    verification_channel: Literal["vision", "sensor", "manual"] = "vision"
    manual_provenance: ManualProvenance
    requires_same_frame: bool = False


class ProcedureState(BaseModel):
    state_id: str = Field(min_length=1)
    step_index: int = Field(ge=0)
    state_type: Literal["initial_state", "action"] = "action"
    instruction: str = Field(min_length=1)
    preconditions: list[str] = Field(default_factory=list)
    postconditions: list[str] = Field(default_factory=list)
    wrong_states: list[str] = Field(default_factory=list)
    target_components: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    manual_provenance: ManualProvenance
    verification: str = Field(min_length=1)
    next_on_success: str | None = None
    observation_nodes: list[ObservationNode] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def compile_legacy_observation_nodes(cls, value: object) -> object:
        """Upgrade audited 0.8 fixtures without weakening live compilation.

        Live manual parsing builds richer nodes in ManualService.  This small
        compatibility compiler keeps the bundled audited profiles loadable and
        guarantees that every public ProcedureDocument already has the 0.9
        shape.
        """
        if not isinstance(value, dict) or value.get("observation_nodes"):
            return value
        payload = dict(value)
        state_id = str(payload.get("state_id", "S0"))
        provenance = payload.get("manual_provenance") or {
            "page": 1,
            "section": "manual review required",
        }
        components = [
            str(item)
            for item in payload.get("target_components", [])
            if str(item).strip()
        ] or ["source:设备当前操作区域"]
        nodes = []
        for index, condition in enumerate(payload.get("postconditions", []), start=1):
            text = str(condition).strip()
            if not text:
                continue
            lowered = text.lower()
            if any(marker in lowered for marker in ("后方", "背面", "rear", "back")):
                viewpoint = "rear"
            elif any(marker in lowered for marker in ("顶部", "上方", "进料口", "top")):
                viewpoint = "top"
            elif any(marker in lowered for marker in ("右侧", "右边", "料卷", "right", "spool")):
                viewpoint = "right"
            elif any(marker in lowered for marker in ("底部", "底座", "下方", "bottom", "base")):
                viewpoint = "bottom"
            elif any(marker in lowered for marker in ("左侧", "左边", "left")):
                viewpoint = "left"
            elif any(marker in lowered for marker in ("整机", "整体", "全貌", "overview")):
                viewpoint = "overview"
            else:
                viewpoint = "close_up"
            if any(marker in lowered for marker in ("连接", "插入", "接口", "connected", "inserted")):
                evidence_type = "connection"
            elif any(marker in lowered for marker in ("屏幕", "显示", "display", "code")):
                evidence_type = "display"
            elif any(marker in lowered for marker in ("水平", "竖直", "朝向", "orientation")):
                evidence_type = "orientation"
            elif any(marker in lowered for marker in ("位于", "左边", "右边", "上方", "下方", "position")):
                evidence_type = "position"
            else:
                evidence_type = "presence"
            if any(marker in lowered for marker in ("ptfe", "管路", "路径", "route", "tube")):
                visualization = "polyline"
            elif any(item.startswith("target:") for item in components):
                visualization = "arrow"
            elif evidence_type in {"connection", "display"}:
                visualization = "box"
            else:
                visualization = "mask"
            viewpoint_text = {
                "front": "移动到设备正面",
                "rear": "绕到设备后方",
                "left": "移动到设备左侧",
                "right": "移动到设备右侧",
                "top": "抬高手机从斜上方拍摄",
                "bottom": "降低手机从侧下方拍摄",
                "close_up": "靠近当前部件",
                "overview": "稍微后退让相关整体区域入镜",
            }[viewpoint]
            nodes.append(
                {
                    "inspection_id": f"{state_id}-C{index}",
                    "condition": text,
                    "component_ids": components,
                    "viewpoint": viewpoint,
                    "capture_instruction": f"{viewpoint_text}，完整拍摄：{text}",
                    "evidence_type": evidence_type,
                    "visualization": visualization,
                    "verification_channel": "vision",
                    "manual_provenance": provenance,
                    "requires_same_frame": len(components) > 1,
                }
            )
        payload["observation_nodes"] = nodes
        return payload

    @model_validator(mode="after")
    def validate_observation_coverage(self) -> "ProcedureState":
        if not self.observation_nodes:
            raise ValueError(
                f"{self.state_id} has no auditable observation_nodes"
            )
        conditions = {node.condition.strip() for node in self.observation_nodes}
        missing = [
            condition
            for condition in self.postconditions
            if condition.strip() not in conditions
        ]
        if missing:
            raise ValueError(
                f"{self.state_id} postconditions have no observation node: "
                + "; ".join(missing)
            )
        node_ids = [node.inspection_id for node in self.observation_nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError(f"{self.state_id} has duplicate inspection_id values")
        return self


class ProcedureDevice(BaseModel):
    device_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    role: str = "manual_defined_equipment"
    future_target_device: str | None = None


class ProcedureTask(BaseModel):
    task_id: str = Field(min_length=1)
    manual_id: str = Field(min_length=1)
    initial_state: str = Field(min_length=1)
    terminal_states: list[str] = Field(min_length=1)
    task_type: Literal[
        "load_spool",
        "unload_spool",
        "swap_spool",
        "recover_visible_jam",
        "legacy",
    ] = "legacy"
    parameters: dict[str, Any] = Field(default_factory=dict)


class ProcedureDocument(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: str = "0.9"
    device: ProcedureDevice
    task: ProcedureTask
    states: list[ProcedureState] = Field(min_length=1)

    @field_validator("states")
    @classmethod
    def validate_state_graph(cls, states: list[ProcedureState]) -> list[ProcedureState]:
        ids = [state.state_id for state in states]
        if len(ids) != len(set(ids)):
            raise ValueError("state_id values must be unique")

        known = set(ids)
        for state in states:
            if state.next_on_success is not None and state.next_on_success not in known:
                raise ValueError(
                    f"{state.state_id} points to unknown state "
                    f"{state.next_on_success}"
                )
        return states


class SlotTopology(BaseModel):
    slot_id: int = Field(ge=1, le=4)
    screen_position: Literal[
        "left_upper", "left_lower", "right_lower", "right_upper"
    ]
    counterclockwise_index: int = Field(ge=1, le=4)
    aliases: list[str] = Field(default_factory=list)


class GeneratedAsset(BaseModel):
    asset_id: str = Field(min_length=1)
    asset_type: Literal["missing_object_billboard"]
    subject: str = Field(min_length=1)
    transparent_background: bool = True
    generation_provider: str | None = None
    local_path: str | None = None
    review_status: Literal["pending", "approved", "rejected"] = "pending"
    runtime_generation_allowed: bool = False


class ManualTaskDefinition(BaseModel):
    task_template_id: str = Field(min_length=1)
    task_type: Literal[
        "load_spool", "unload_spool", "swap_spool", "recover_visible_jam"
    ]
    display_name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    parameter_names: list[str] = Field(default_factory=list)
    enabled: bool = True
    blocked_reason: str | None = None
    template_procedure: ProcedureDocument | None = None
    safety_boundary: list[str] = Field(default_factory=list)
    required_sources: list[ManualProvenance] = Field(default_factory=list)


class ManualTaskBundle(BaseModel):
    schema_version: str = "1.0"
    manual_id: str = Field(min_length=1)
    device_profile: str = Field(min_length=1)
    component_topology: list[SlotTopology] = Field(min_length=4, max_length=4)
    tasks: list[ManualTaskDefinition] = Field(min_length=1)
    generated_assets: list[GeneratedAsset] = Field(default_factory=list)
    manual_provenance: list[ManualProvenance] = Field(default_factory=list)
    compile_version: str = Field(min_length=1)
    human_review_status: Literal["pending", "approved", "rejected"] = "pending"

    @model_validator(mode="after")
    def validate_four_slot_topology(self) -> "ManualTaskBundle":
        slot_ids = [slot.slot_id for slot in self.component_topology]
        if sorted(slot_ids) != [1, 2, 3, 4]:
            raise ValueError("AMS Lite topology must define slots 1, 2, 3, and 4")
        positions = [slot.screen_position for slot in self.component_topology]
        if len(positions) != len(set(positions)):
            raise ValueError("AMS Lite slot positions must be unique")
        return self


class ManualTaskSelectionRequest(BaseModel):
    task_template_id: str = Field(min_length=1)
    selected_slot_id: int | None = Field(default=None, ge=1, le=4)
    source_slot_id: int | None = Field(default=None, ge=1, le=4)
    target_slot_id: int | None = Field(default=None, ge=1, le=4)
    required_material: str | None = None
    user_confirmed_slot: bool = False


class ManualTaskSelectionResult(BaseModel):
    procedure_id: str = Field(min_length=1)
    procedure: ProcedureDocument
    selected_slot_id: int | None = None
    source_slot_id: int | None = None
    target_slot_id: int | None = None
    required_material: str | None = None
    requires_user_confirmation: bool = False


class AmsSlotObservation(BaseModel):
    slot_id: int = Field(ge=1, le=4)
    occupied: Literal["yes", "no", "uncertain"] = "uncertain"
    spool_visible: Literal["yes", "no", "uncertain"] = "uncertain"
    feeder_inlet_visible: Literal["yes", "no", "uncertain"] = "uncertain"
    filament_inserted: Literal["yes", "no", "uncertain"] = "uncertain"
    ptfe_filament_visible: Literal["yes", "no", "uncertain"] = "uncertain"
    observed_color: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str = Field(min_length=1)
    bbox_0_1000: list[int] | None = None


class AmsOverviewScanRequest(BaseModel):
    image_base64: str
    image_rotation_degrees: int = 0
    task_type: Literal[
        "load_spool", "unload_spool", "swap_spool", "recover_visible_jam"
    ] = "load_spool"
    mode: Literal["mock", "ollama"] = "ollama"


class AmsOverviewScanResult(BaseModel):
    topology_valid: bool
    slots: list[AmsSlotObservation] = Field(min_length=4, max_length=4)
    suggested_slot_id: int | None = Field(default=None, ge=1, le=4)
    suggestion_reason: str = Field(min_length=1)
    requires_user_confirmation: bool = True
    unavailable_checks: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_slot_set(self) -> "AmsOverviewScanResult":
        if sorted(slot.slot_id for slot in self.slots) != [1, 2, 3, 4]:
            raise ValueError("overview scan must return slots 1, 2, 3, and 4")
        return self


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


MultiComponentId = Literal[
    "filament_spool",
    "empty_spool_holder",
    "build_plate",
]


class MultiComponentLocateRequest(BaseModel):
    image_base64: str = Field(min_length=32)
    component_ids: list[MultiComponentId] = Field(
        default_factory=lambda: [
            "filament_spool",
            "empty_spool_holder",
            "build_plate",
        ]
    )

    @model_validator(mode="after")
    def validate_component_ids(self) -> "MultiComponentLocateRequest":
        if not self.component_ids:
            raise ValueError("component_ids must not be empty")
        if len(self.component_ids) > 3:
            raise ValueError("at most three component_ids are supported")
        if len(set(self.component_ids)) != len(self.component_ids):
            raise ValueError("component_ids must be unique")
        return self


class SemanticComponentCandidate(BaseModel):
    component_id: MultiComponentId
    found: bool
    bbox_0_1000: list[int] | None = None
    target_point_0_1000: list[int] | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    visible_evidence: str = ""
    failure_reason: str | None = None

    @model_validator(mode="after")
    def validate_geometry(self) -> "SemanticComponentCandidate":
        if self.found:
            if self.bbox_0_1000 is None or len(self.bbox_0_1000) != 4:
                raise ValueError("found candidates require bbox_0_1000")
            x1, y1, x2, y2 = self.bbox_0_1000
            if not all(0 <= value <= 1000 for value in self.bbox_0_1000):
                raise ValueError("bbox coordinates must be in [0, 1000]")
            if x2 <= x1 or y2 <= y1:
                raise ValueError("bbox must have positive area")
            if self.target_point_0_1000 is None or len(self.target_point_0_1000) != 2:
                raise ValueError("found candidates require target_point_0_1000")
            px, py = self.target_point_0_1000
            if not (0 <= px <= 1000 and 0 <= py <= 1000):
                raise ValueError("target point coordinates must be in [0, 1000]")
        return self


class SemanticComponentCandidateBatch(BaseModel):
    components: list[SemanticComponentCandidate]


class EmptySpoolAxleLocateRequest(BaseModel):
    """One-image request for the narrow AMS Lite spindle-grounding demo.

    This deliberately does not contain a task graph or state-verification
    fields.  It is the stable entry point used to create evidence images for
    empty-spool-spindle localisation and segmentation.
    """

    image_base64: str = Field(min_length=32)
    preferred_slot_id: int | None = Field(default=None, ge=1, le=4)
    # Optional, photo-specific seed used only after a human has confirmed the
    # visible empty holder in the input image.  This is deliberately separate
    # from the VLM proposal: it lets a paper-figure workflow test SAM2's
    # visible-surface mask without pretending a VLM supplied exact pixels.
    verified_seed_bbox_0_1000: list[int] | None = None

    @field_validator("verified_seed_bbox_0_1000")
    @classmethod
    def validate_verified_seed(cls, box: list[int] | None) -> list[int] | None:
        # Unity JsonUtility serializes an unset array field as []. Treat that
        # representation as the optional field being absent; a non-empty seed
        # still has to pass the strict four-coordinate ComponentBox validator.
        if box is None or box == []:
            return None
        return ComponentBox(
            component_id="verified-empty-spool-spindle-seed",
            bbox_0_1000=box,
        ).bbox_0_1000


class EmptySpoolAxleCandidate(BaseModel):
    """Semantic proposal returned by the VLM before SAM2 segmentation."""

    found: bool
    slot_id: int | None = Field(default=None, ge=1, le=4)
    bbox_0_1000: list[int] | None = None
    target_point_0_1000: list[int] | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    visible_evidence: str = Field(default="")
    failure_reason: str | None = None
    # Current-frame direction in which the visible holder projects away from
    # the central support. This is semantic geometry from Qwen, not a fixed
    # screen ROI; it lets the prompt compiler discard the attachment column
    # regardless of camera rotation.
    extension_direction: Literal["left", "right", "up", "down", "unknown"] = (
        "unknown"
    )
    proposal_source: Literal[
        "qwen_flash",
        "qwen_flash_white_holder_repair",
        "qwen_flash_task_profile_exemplar",
        "verified_photo_seed",
    ] = "qwen_flash"

    @model_validator(mode="after")
    def validate_found_candidate(self) -> "EmptySpoolAxleCandidate":
        if not self.found:
            return self
        if self.slot_id is None:
            raise ValueError("found empty spindle requires slot_id")
        if self.bbox_0_1000 is None:
            raise ValueError("found empty spindle requires bbox_0_1000")
        ComponentBox(
            component_id="ams_lite_empty_spool_spindle",
            bbox_0_1000=self.bbox_0_1000,
        )
        if self.target_point_0_1000 is None or len(self.target_point_0_1000) != 2:
            raise ValueError("found empty spindle requires target_point_0_1000")
        if any(value < 0 or value > 1000 for value in self.target_point_0_1000):
            raise ValueError("target point must be in [0, 1000]")
        return self


class TrackingSessionRequest(BaseModel):
    image_base64: str
    component_id: str = Field(min_length=1)
    bbox_0_1000: list[int] = Field(min_length=4, max_length=4)
    procedure_id: str | None = None
    step_id: str | None = None
    run_id: str | None = None
    guidance_target: GuidanceTarget | None = None

    @field_validator("bbox_0_1000")
    @classmethod
    def validate_tracking_box(cls, box: list[int]) -> list[int]:
        return ComponentBox(
            component_id="tracking-prompt",
            bbox_0_1000=box,
        ).bbox_0_1000


class TrackingFrameRequest(BaseModel):
    image_base64: str
    world_anchor_status: Literal[
        "client_pending", "anchored", "lost", "relocalizing"
    ] | None = None
    client_drift_ratio: float | None = Field(default=None, ge=0.0)
    client_relocalization_count: int | None = Field(default=None, ge=0)


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


class LocatedComponentResult(BaseModel):
    component_id: MultiComponentId
    english_label: str
    found: bool
    candidate: SemanticComponentCandidate
    session_id: str | None = None
    tracked: TrackedComponent | None = None
    tracking_ready: bool = False
    error: str | None = None


class MultiComponentLocateResponse(BaseModel):
    results: list[LocatedComponentResult]
    provider: str = "qwen"
    model: str = ""


PlateInspectionValue = Literal["yes", "no", "uncertain"]
PlateAnomalyType = Literal["foreign_object", "residue"]


class BuildPlateInspectionRequest(BaseModel):
    """Live-frame request for the task-conditioned pre-print inspection."""

    image_base64: str = Field(min_length=32)
    image_rotation_degrees: int = 0
    profile_id: Literal["preprint_plate_inspection_v1"] = (
        "preprint_plate_inspection_v1"
    )
    start_tracking: bool = True

    @field_validator("image_rotation_degrees")
    @classmethod
    def validate_rotation(cls, value: int) -> int:
        normalized = value % 360
        if normalized not in {0, 90, 180, 270}:
            raise ValueError("image_rotation_degrees must be 0, 90, 180, or 270")
        return normalized


class BuildPlateObservation(BaseModel):
    present: PlateInspectionValue
    aligned: PlateInspectionValue
    fully_visible: PlateInspectionValue
    bbox_0_1000: list[int] | None = None
    target_point_0_1000: list[int] | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    visible_evidence: str = ""

    @model_validator(mode="after")
    def validate_geometry(self) -> "BuildPlateObservation":
        if self.present == "yes":
            if self.bbox_0_1000 is None:
                raise ValueError("a present build plate requires bbox_0_1000")
            ComponentBox(component_id="a1_mini_build_plate", bbox_0_1000=self.bbox_0_1000)
            if self.target_point_0_1000 is None or len(self.target_point_0_1000) != 2:
                raise ValueError("a present build plate requires target_point_0_1000")
        return self


class BuildPlateAnomalyCandidate(BaseModel):
    anomaly_id: str = Field(min_length=1)
    anomaly_type: PlateAnomalyType
    bbox_0_1000: list[int]
    target_point_0_1000: list[int]
    confidence: float = Field(ge=0.0, le=1.0)
    visible_evidence: str = ""
    correction_instruction: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_geometry(self) -> "BuildPlateAnomalyCandidate":
        ComponentBox(component_id=self.anomaly_id, bbox_0_1000=self.bbox_0_1000)
        if len(self.target_point_0_1000) != 2 or any(
            value < 0 or value > 1000 for value in self.target_point_0_1000
        ):
            raise ValueError("anomaly target point must contain two values in [0, 1000]")
        return self


class BuildPlateVisionResult(BaseModel):
    plate: BuildPlateObservation
    anomalies: list[BuildPlateAnomalyCandidate] = Field(default_factory=list)
    scene_evidence: str = ""


class InspectionPredicateResult(BaseModel):
    predicate_id: Literal[
        "plate_present", "plate_aligned", "surface_clear", "no_residue"
    ]
    passed: bool
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str


class InspectionRejectedCandidate(BaseModel):
    candidate: BuildPlateAnomalyCandidate
    reason: str
    benign_exclusion: bool = False


class InspectionMaskResult(BaseModel):
    object_id: str
    object_type: Literal["build_plate", "foreign_object", "residue"]
    semantic_box_0_1000: list[int]
    compiled_box_0_1000: list[int]
    target_point_0_1000: list[int]
    session_id: str | None = None
    tracked: TrackedComponent | None = None
    tracking_ready: bool = False
    mask_containment_in_plate: float = Field(default=1.0, ge=0.0, le=1.0)
    error: str | None = None


class BuildPlateInspectionResponse(BaseModel):
    profile_id: str
    profile_version: str
    prompt_version: str
    method_label: str
    exemplar_guided: bool = True
    provider: str
    model: str
    status: Literal["ready", "corrective_action", "uncertain"]
    safe_to_print: bool
    headline: str
    correction_instructions: list[str] = Field(default_factory=list)
    predicates: list[InspectionPredicateResult]
    plate: BuildPlateObservation
    plate_mask: InspectionMaskResult | None = None
    anomalies: list[InspectionMaskResult] = Field(default_factory=list)
    rejected_candidates: list[InspectionRejectedCandidate] = Field(default_factory=list)
    qwen_raw: dict[str, Any] = Field(default_factory=dict)
    reference_hashes: dict[str, str] = Field(default_factory=dict)


FilamentLoadingValue = Literal["yes", "no", "uncertain"]
FilamentLoadingState = Literal["loaded", "not_inserted", "uncertain"]


class FilamentLoadingInspectionRequest(BaseModel):
    image_base64: str = Field(min_length=32)
    image_rotation_degrees: int = 0
    profile_id: Literal["ams_lite_filament_loading_v1"] = (
        "ams_lite_filament_loading_v1"
    )
    start_tracking: bool = True

    @field_validator("image_rotation_degrees")
    @classmethod
    def validate_rotation(cls, value: int) -> int:
        normalized = value % 360
        if normalized not in {0, 90, 180, 270}:
            raise ValueError("image_rotation_degrees must be 0, 90, 180, or 270")
        return normalized


class FilamentRegionObservation(BaseModel):
    visible: FilamentLoadingValue
    bbox_0_1000: list[int] | None = None
    target_point_0_1000: list[int] | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    visible_evidence: str = ""

    @model_validator(mode="after")
    def validate_geometry(self) -> "FilamentRegionObservation":
        if self.visible == "yes":
            if self.bbox_0_1000 is None:
                raise ValueError("a visible filament region requires bbox_0_1000")
            ComponentBox(component_id="filament_region", bbox_0_1000=self.bbox_0_1000)
            if self.target_point_0_1000 is None or len(self.target_point_0_1000) != 2:
                raise ValueError("a visible filament region requires target_point_0_1000")
            if any(value < 0 or value > 1000 for value in self.target_point_0_1000):
                raise ValueError("filament region target point must be in [0, 1000]")
        return self


class FilamentLoadingVisionResult(BaseModel):
    proposed_state: FilamentLoadingState
    state_confidence: float = Field(ge=0.0, le=1.0)
    feeder_module: FilamentRegionObservation
    filament_inlet: FilamentRegionObservation
    loose_filament_tip: FilamentRegionObservation
    inserted_filament_at_inlet: FilamentRegionObservation
    filament_visible_in_ptfe: FilamentRegionObservation
    scene_evidence: str = ""


class FilamentConnectionVerification(BaseModel):
    """Focused tie-break result for visually ambiguous loading states."""

    connection_state: FilamentLoadingState
    confidence: float = Field(ge=0.0, le=1.0)
    feeder_module: FilamentRegionObservation
    inserted_filament_at_inlet: FilamentRegionObservation
    filament_visible_in_ptfe: FilamentRegionObservation
    free_filament_cut_end: FilamentRegionObservation
    evidence: str = ""


class LooseFilamentTipCheck(BaseModel):
    loose_tip_visible: FilamentLoadingValue
    bbox_0_1000: list[int] | None = None
    target_point_0_1000: list[int] | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    visible_evidence: str = ""

    @model_validator(mode="after")
    def validate_geometry(self) -> "LooseFilamentTipCheck":
        if self.loose_tip_visible == "yes":
            if self.bbox_0_1000 is None or self.target_point_0_1000 is None:
                raise ValueError("a visible loose tip requires crop geometry")
            ComponentBox(component_id="loose_filament_tip", bbox_0_1000=self.bbox_0_1000)
            if len(self.target_point_0_1000) != 2:
                raise ValueError("loose tip target point requires two values")
        return self


class FilamentLoadingPredicateResult(BaseModel):
    predicate_id: Literal[
        "feeder_visible",
        "inlet_visible",
        "filament_entered_feeder",
        "filament_visible_in_ptfe",
    ]
    passed: bool
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str


class FilamentLoadingMaskResult(BaseModel):
    object_id: str
    object_type: Literal[
        "feeder_module",
        "filament_tip",
        "inserted_filament",
        "ptfe_filament",
    ]
    semantic_box_0_1000: list[int]
    compiled_box_0_1000: list[int]
    target_point_0_1000: list[int]
    session_id: str | None = None
    tracked: TrackedComponent | None = None
    tracking_ready: bool = False
    error: str | None = None


class FilamentLoadingRejectedRegion(BaseModel):
    object_type: str
    reason: str


class FilamentLoadingInspectionResponse(BaseModel):
    profile_id: str
    profile_version: str
    prompt_version: str
    method_label: str
    exemplar_guided: bool = True
    provider: str
    model: str
    status: FilamentLoadingState
    headline: str
    primary_instruction: str
    secondary_instruction: str
    predicates: list[FilamentLoadingPredicateResult]
    feeder_module: FilamentRegionObservation
    filament_inlet: FilamentRegionObservation
    loose_filament_tip: FilamentRegionObservation
    inserted_filament_at_inlet: FilamentRegionObservation
    filament_visible_in_ptfe: FilamentRegionObservation
    masks: list[FilamentLoadingMaskResult] = Field(default_factory=list)
    rejected_regions: list[FilamentLoadingRejectedRegion] = Field(default_factory=list)
    qwen_raw: dict[str, Any] = Field(default_factory=dict)
    reference_hashes: dict[str, str] = Field(default_factory=dict)


class TrackingSessionResponse(BaseModel):
    session_id: str = Field(min_length=1)
    tracked: TrackedComponent


class EmptySpoolAxleLocateResponse(BaseModel):
    """Combined Qwen semantic proposal and SAM2 mask result."""

    found: bool
    candidate: EmptySpoolAxleCandidate
    session_id: str | None = None
    tracked: TrackedComponent | None = None
    provider: str = Field(default="qwen")
    model: str = Field(default="")
    tracking_ready: bool = False
    error: str | None = None


class PredicateEvidence(BaseModel):
    predicate_id: str = Field(min_length=1)
    status: VerificationStatus
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_region: list[ComponentBox] = Field(default_factory=list)
    visible_evidence: str = ""
    failure_reason: str | None = None
    correction_instruction: str | None = None
    necessary: bool = True


class VerificationResult(BaseModel):
    status: VerificationStatus
    matched_step_id: str
    evidence: str
    component_boxes_0_1000: list[ComponentBox] = Field(default_factory=list)
    manual_page: int = Field(ge=1)
    manual_section: str
    confidence: float = Field(ge=0.0, le=1.0)
    safe_to_advance: bool
    next_action: str
    # Action checkpoints must explicitly establish comparability and visible
    # change. The deterministic server gate consumes these fields; an overall
    # VLM confidence score cannot replace them.
    same_area_visible: bool = False
    expected_change_visible: bool = False
    inspection_id: str | None = None
    retained_inspection_ids: list[str] = Field(default_factory=list)
    visualization_type: Literal[
        "box", "mask", "arrow", "polyline", "none"
    ] = "none"
    predicates: list[PredicateEvidence] = Field(default_factory=list)
    safety_gate_reasons: list[str] = Field(default_factory=list)
    overlay_semantic: Literal[
        "next_action", "verified", "insufficient", "error"
    ] = "insufficient"


class VerificationRequest(BaseModel):
    procedure_id: str
    current_step_id: str
    history: list[str] = Field(default_factory=list)
    image_base64: str
    image_rotation_degrees: int = 0
    # Checkpoint mode compares a deliberately captured pre-action frame with
    # the post-action frame above.  Single-frame callers remain compatible.
    comparison_mode: Literal["single_frame", "before_after"] = "single_frame"
    before_image_base64: str | None = None
    before_image_rotation_degrees: int = 0
    mode: Literal["mock", "ollama"] = "ollama"
    mock_status: VerificationStatus = "completed"
    save_for_training: bool = False
    run_id: str | None = None
    # A large manual step may require several camera viewpoints.  Each request
    # verifies one visible condition only; the server allows state advancement
    # only when the final request carries the complete retained node prefix.
    inspection_id: str | None = None
    focus_component_ids: list[str] = Field(default_factory=list)
    focus_condition: str | None = None
    completed_inspection_ids: list[str] = Field(default_factory=list)
    expected_inspection_ids: list[str] = Field(default_factory=list)
    is_final_inspection: bool = True
    request_purpose: Literal[
        "state_verification", "guidance_localization", "start_audit"
    ] = "state_verification"

    @field_validator("comparison_mode", mode="before")
    @classmethod
    def normalize_blank_comparison_mode(cls, value: object) -> object:
        # Unity's JsonUtility serializes an unset public string as "".  Treat
        # that legacy payload as the documented single-frame default instead
        # of rejecting the request before it reaches the vision service.
        if value is None or not str(value).strip():
            return "single_frame"
        return value

    @field_validator("mock_status", mode="before")
    @classmethod
    def normalize_blank_mock_status(cls, value: object) -> object:
        # mock_status is irrelevant in live VLM mode, but older Unity builds
        # still serialize its unset string field as "".  Normalize it before
        # Literal validation so a live request is not rejected prematurely.
        if value is None or not str(value).strip():
            return "completed"
        return value

    @model_validator(mode="after")
    def validate_comparison_input(self) -> "VerificationRequest":
        if (
            self.comparison_mode == "before_after"
            and not str(self.before_image_base64 or "").strip()
        ):
            raise ValueError(
                "before_image_base64 is required for before_after comparison"
            )
        return self


class StateLocalizationRequest(BaseModel):
    procedure_id: str
    image_base64: str
    image_rotation_degrees: int = 0
    mode: Literal["mock", "ollama"] = "ollama"
    mock_recommended_step_id: str | None = None
    run_id: str | None = None


class StateLocalizationResult(BaseModel):
    observed_summary: str = Field(min_length=1)
    completed_step_ids: list[str] = Field(default_factory=list)
    recommended_step_id: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    requires_human_confirmation: bool = True
    unavailable_checks: list[str] = Field(default_factory=list)
    component_boxes_0_1000: list[ComponentBox] = Field(default_factory=list)
    device_identity: Literal[
        "a1_mini",
        "ams_lite",
        "a1_mini_ams_lite",
        "not_a1_mini",
        "not_ams_lite",
        "uncertain",
    ] = "uncertain"
    device_configuration: Literal[
        "external_spool", "ams_lite", "mixed", "uncertain"
    ] = "uncertain"
    procedure_compatible: Literal["true", "false", "uncertain"] = "uncertain"
    capture_mode: Literal["full_frame", "manual_roi"] = "manual_roi"


class StateStartConfirmationRequest(BaseModel):
    procedure_id: str
    recommended_step_id: str
    confidence: float = Field(ge=0.0, le=1.0)
    human_override: bool = False
    override_reason: str | None = None
    run_id: str | None = None
    device_identity: Literal[
        "a1_mini",
        "ams_lite",
        "a1_mini_ams_lite",
        "not_a1_mini",
        "not_ams_lite",
        "uncertain",
    ] = "uncertain"
    procedure_compatible: Literal["true", "false", "uncertain"] = "uncertain"

    @model_validator(mode="after")
    def validate_override_reason(self) -> "StateStartConfirmationRequest":
        if self.human_override and not (self.override_reason or "").strip():
            raise ValueError("override_reason is required for a human override")
        return self


class StateStartConfirmationResponse(BaseModel):
    accepted: bool
    audit_id: str = Field(min_length=1)


class ManualJobAccepted(BaseModel):
    job_id: str
    status: Literal["queued"]


class ManualJob(BaseModel):
    job_id: str
    status: Literal["queued", "running", "completed", "failed"]
    stage: Literal[
        "queued",
        "uploading",
        "reading_pages",
        "extracting_procedure",
        "building_constraints",
        "completed",
        "failed",
    ]
    progress: float = Field(ge=0.0, le=1.0)
    error: str | None = None
    procedure_id: str | None = None
    procedure: ProcedureDocument | None = None
    bundle_id: str | None = None
    bundle: ManualTaskBundle | None = None


class HealthResponse(BaseModel):
    status: Literal["ok"]
    ollama_url: str
    model: str
    vision_provider: str = "ollama"
    vision_ready: bool = True
    vision_configuration_error: str | None = None
    tracking_mode: str = "opencv"
    tracking_provider: str = "opencv-grabcut-lk-baseline"
    tracking_remote_available: bool = False
    tracking_remote_url: str | None = None
    tracking_last_error: str | None = None


class FieldCaptureResponse(BaseModel):
    capture_id: str
    case_id: str
    phase: Literal["raw", "before", "after", "overlay", "verification", "error"]
    revision: int = Field(ge=1)
    image_path: str
    metadata_path: str
    pair_complete: bool
