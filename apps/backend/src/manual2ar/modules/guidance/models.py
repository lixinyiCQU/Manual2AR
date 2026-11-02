from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class ManualProvenance(BaseModel):
    # Wiki evidence has a section and immutable block IDs, rather than PDF pages.
    # Existing PDF procedures continue to require a positive page number.
    page: int | None = Field(default=None, ge=1)
    section: str = Field(min_length=1)
    source_text: str | None = None
    source_type: Literal["pdf", "wiki"] = "pdf"
    source_url: str | None = None
    citation_ids: list[str] = Field(default_factory=list)
    snapshot_id: str | None = None

    @model_validator(mode="after")
    def validate_source_location(self) -> "ManualProvenance":
        if self.source_type == "pdf" and self.page is None:
            raise ValueError("PDF provenance requires a page number")
        if self.source_type == "wiki":
            if self.page is not None:
                raise ValueError("Wiki provenance must not invent a PDF page number")
            if not self.source_url or not self.source_url.startswith("https://"):
                raise ValueError("Wiki provenance requires an HTTPS source URL")
            if not self.citation_ids or not self.snapshot_id:
                raise ValueError("Wiki provenance requires citation IDs and a snapshot ID")
        return self

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
