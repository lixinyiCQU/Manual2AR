from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from .models import (
    GeneratedAsset,
    ManualProvenance,
    ManualTaskBundle,
    ManualTaskDefinition,
    ManualTaskSelectionRequest,
    ManualTaskSelectionResult,
    ObservationNode,
    ProcedureDocument,
    ProcedureState,
    ProcedureTask,
    SlotTopology,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
AMS_ROOT = PROJECT_ROOT / "examples" / "bambu_a1_mini_ams_lite_v1"
AMS_MANUAL_ID = "bambu_ams_lite_quick_start_2026"
AMS_COMPILE_VERSION = "manual-task-bundle-1.0.0"


SLOT_TOPOLOGY = [
    SlotTopology(
        slot_id=1,
        screen_position="left_upper",
        counterclockwise_index=1,
        aliases=["左上", "slot 1", "一号槽"],
    ),
    SlotTopology(
        slot_id=2,
        screen_position="left_lower",
        counterclockwise_index=2,
        aliases=["左下", "slot 2", "二号槽"],
    ),
    SlotTopology(
        slot_id=3,
        screen_position="right_lower",
        counterclockwise_index=3,
        aliases=["右下", "slot 3", "三号槽"],
    ),
    SlotTopology(
        slot_id=4,
        screen_position="right_upper",
        counterclockwise_index=4,
        aliases=["右上", "slot 4", "四号槽"],
    ),
]


def _load_audited_load_template() -> ProcedureDocument:
    payload = json.loads((AMS_ROOT / "procedure.json").read_text(encoding="utf-8"))
    return ProcedureDocument.model_validate(payload)


def _visible_jam_template() -> ProcedureDocument:
    provenance = ManualProvenance(
        page=20,
        section="上料注意事项",
        source_text="如果耗材卡住，按下释放按钮可分离驱动电机。",
    )
    states = [
        ProcedureState(
            state_id="J0",
            step_index=0,
            state_type="initial_state",
            instruction=(
                "先不要拆管或拉扯耗材；近拍目标槽送料口、可见耗材和黄色释放按钮，"
                "确认问题仅位于AMS Lite外部可见区域"
            ),
            preconditions=["打印机空闲且用户已停止继续送料"],
            postconditions=["可见卡料位于目标槽送料口附近，未涉及拆PTFE管、集线器、挤出机或热端"],
            wrong_states=[
                "卡料位置不可见",
                "需要拆PTFE管、集线器、挤出机或热端",
                "打印机正在打印、加热或自动运动",
            ],
            target_components=[
                "target:AMS Lite 1号送料口",
                "source:1号槽可见耗材",
                "target:AMS Lite 1号黄色释放按钮",
            ],
            warnings=["超出AMS Lite外部可见区域时立即停止并进入独立维护任务"],
            manual_provenance=provenance,
            verification="卡料位置外部可见且黄色释放按钮适用",
            next_on_success="J1",
            observation_nodes=[
                ObservationNode(
                    inspection_id="J0-C1",
                    condition="可见卡料位于目标槽送料口附近，未涉及拆PTFE管、集线器、挤出机或热端",
                    component_ids=[
                        "target:AMS Lite 1号送料口",
                        "source:1号槽可见耗材",
                        "target:AMS Lite 1号黄色释放按钮",
                    ],
                    viewpoint="bottom",
                    capture_instruction="从送料单元下方斜向上近拍送料口、可见耗材和黄色释放按钮",
                    evidence_type="relation",
                    visualization="box",
                    manual_provenance=provenance,
                    requires_same_frame=True,
                )
            ],
        ),
        ProcedureState(
            state_id="J1",
            step_index=1,
            instruction=(
                "按住目标槽黄色释放按钮，使驱动电机分离；只在外部可见且无阻力时轻柔退出耗材。"
                "若需要拆管或明显用力，立即停止"
            ),
            preconditions=["J0已确认黄色释放按钮适用且问题仅在外部可见区域"],
            postconditions=["耗材已从目标送料口安全退出，送料口附近无可见缠绕或折弯"],
            wrong_states=["耗材仍被卡住", "需要拆管", "需要明显用力", "出现新的折弯或缠绕"],
            target_components=[
                "target:AMS Lite 1号黄色释放按钮",
                "source:1号槽可见耗材",
                "target:AMS Lite 1号送料口",
            ],
            warnings=["正常上料任务绝不能把该按钮作为操作目标"],
            manual_provenance=provenance,
            verification="目标送料口已安全释放且外部可见路径无缠绕",
            next_on_success=None,
            observation_nodes=[
                ObservationNode(
                    inspection_id="J1-C1",
                    condition="耗材已从目标送料口安全退出，送料口附近无可见缠绕或折弯",
                    component_ids=[
                        "target:AMS Lite 1号送料口",
                        "source:1号槽可见耗材",
                    ],
                    viewpoint="bottom",
                    capture_instruction="操作后从同一局部近拍送料口和退出后的耗材路径",
                    evidence_type="relation",
                    visualization="box",
                    manual_provenance=provenance,
                    requires_same_frame=True,
                )
            ],
        ),
    ]
    return ProcedureDocument(
        schema_version="0.9",
        device={
            "device_id": "bambu_a1_mini_ams_lite",
            "name": "Bambu Lab AMS Lite",
            "role": "manual_defined_equipment",
        },
        task=ProcedureTask(
            task_id="ams_lite_recover_visible_jam_slot1_v1",
            manual_id=AMS_MANUAL_ID,
            initial_state="J0",
            terminal_states=["J1"],
            task_type="recover_visible_jam",
            parameters={"selected_slot_id": 1},
        ),
        states=states,
    )


def build_ams_lite_bundle() -> ManualTaskBundle:
    load_template = _load_audited_load_template()
    provenance = [
        ManualProvenance(
            page=18,
            section="安装料盘",
            source_text="根据耗材绕线方向安装料盘。",
        ),
        ManualProvenance(
            page=20,
            section="上料",
            source_text="通过进料口上料；卡住时按释放按钮分离驱动电机。",
        ),
    ]
    unavailable = "缺少经人工审核的官方维护来源，当前版本不允许执行"
    return ManualTaskBundle(
        manual_id=AMS_MANUAL_ID,
        device_profile="bambu_a1_mini_ams_lite",
        component_topology=SLOT_TOPOLOGY,
        tasks=[
            ManualTaskDefinition(
                task_template_id="load_spool",
                task_type="load_spool",
                display_name="选槽上料",
                description="选择或接受系统建议的空槽，安装料盘并将耗材送入同槽送料口。",
                parameter_names=["selected_slot_id", "required_material"],
                template_procedure=load_template,
                safety_boundary=[
                    "正常上料不按黄色释放按钮",
                    "不拆PTFE管",
                    "必要观察缺失时不得推进",
                ],
                required_sources=provenance,
            ),
            ManualTaskDefinition(
                task_template_id="unload_spool",
                task_type="unload_spool",
                display_name="正常退料",
                description="从用户确认的槽位执行官方正常退料流程。",
                parameter_names=["selected_slot_id"],
                enabled=False,
                blocked_reason=unavailable,
                safety_boundary=["不得以可见卡料恢复流程代替正常退料"],
            ),
            ManualTaskDefinition(
                task_template_id="swap_spool",
                task_type="swap_spool",
                display_name="同槽或跨槽换料",
                description="复用退料子图与上料子图，不复制独立流程。",
                parameter_names=["source_slot_id", "target_slot_id", "required_material"],
                enabled=False,
                blocked_reason="依赖尚未开放的正常退料子图",
                safety_boundary=["打印机必须空闲", "退料子图通过后才能进入上料子图"],
            ),
            ManualTaskDefinition(
                task_template_id="recover_visible_jam",
                task_type="recover_visible_jam",
                display_name="AMS可见区域卡料恢复",
                description="仅处理送料口附近外部可见卡料，黄色释放按钮只在本任务中可操作。",
                parameter_names=["selected_slot_id"],
                template_procedure=_visible_jam_template(),
                safety_boundary=[
                    "不拆PTFE管",
                    "不拆集线器",
                    "不拆挤出机或热端",
                    "需要用力时立即停止",
                ],
                required_sources=[provenance[1]],
            ),
        ],
        generated_assets=[
            GeneratedAsset(
                asset_id="ams-lite-compatible-spool-billboard-v1",
                asset_type="missing_object_billboard",
                subject="兼容AMS Lite料卷",
                generation_provider=None,
                local_path=None,
                review_status="pending",
                runtime_generation_allowed=False,
            )
        ],
        manual_provenance=provenance,
        compile_version=AMS_COMPILE_VERSION,
        human_review_status="approved",
    )


def _replace_slot(value: str, slot_id: int) -> str:
    return re.sub(r"(?<![234])1号", f"{slot_id}号", value)


def _parameterize_procedure(
    template: ProcedureDocument,
    task_type: str,
    slot_id: int,
    required_material: str | None,
) -> ProcedureDocument:
    payload = template.model_dump()
    serialized = json.dumps(payload, ensure_ascii=False)
    serialized = _replace_slot(serialized, slot_id)
    procedure = ProcedureDocument.model_validate(json.loads(serialized))
    procedure.task.task_id = f"ams_lite_{task_type}_slot{slot_id}_v1"
    procedure.task.task_type = task_type  # type: ignore[assignment]
    procedure.task.parameters = {
        "selected_slot_id": slot_id,
        "required_material": required_material,
        "color_is_hard_constraint": False,
    }
    if required_material:
        procedure.task.parameters["material_is_hard_constraint"] = True
        for state in procedure.states:
            state.preconditions.append(f"用户要求材料为：{required_material}")
    else:
        procedure.task.parameters["material_is_hard_constraint"] = False
    return procedure


def instantiate_ams_task(
    bundle: ManualTaskBundle,
    request: ManualTaskSelectionRequest,
) -> ManualTaskSelectionResult:
    definition = next(
        (task for task in bundle.tasks if task.task_template_id == request.task_template_id),
        None,
    )
    if definition is None:
        raise ValueError("Unknown AMS Lite task template")
    if not definition.enabled or definition.template_procedure is None:
        raise ValueError(definition.blocked_reason or "Task is not available")
    if not request.user_confirmed_slot:
        raise ValueError("The target AMS Lite slot must be confirmed by the user")
    slot_id = request.selected_slot_id
    if slot_id is None:
        raise ValueError("selected_slot_id is required for this task")
    procedure = _parameterize_procedure(
        definition.template_procedure,
        definition.task_type,
        slot_id,
        request.required_material,
    )
    procedure_id = f"ams-{definition.task_type}-s{slot_id}-{uuid.uuid4().hex[:12]}"
    return ManualTaskSelectionResult(
        procedure_id=procedure_id,
        procedure=procedure,
        selected_slot_id=slot_id,
        required_material=request.required_material,
        requires_user_confirmation=False,
    )
