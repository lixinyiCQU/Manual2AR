from __future__ import annotations

from app.ams_lite_tasks import build_ams_lite_bundle, instantiate_ams_task
from app.models import ManualTaskSelectionRequest


def _load_spool_procedure(slot_id: int = 3):
    return instantiate_ams_task(
        build_ams_lite_bundle(),
        ManualTaskSelectionRequest(
            task_template_id="load_spool",
            selected_slot_id=slot_id,
            user_confirmed_slot=True,
        ),
    ).procedure


def test_load_spool_does_not_finish_when_only_the_spool_is_mounted() -> None:
    procedure = _load_spool_procedure()
    states = {state.state_id: state for state in procedure.states}

    assert procedure.task.terminal_states == ["S3"]
    assert states["S1"].next_on_success == "S2"
    assert "先不要插料" in states["S1"].instruction
    assert "送料器" in states["S2"].instruction
    assert states["S2"].next_on_success == "S3"
    assert "PTFE" in states["S3"].instruction
    assert states["S3"].next_on_success is None


def test_slot_parameterization_preserves_selected_slot_and_no_color_constraint() -> None:
    procedure = _load_spool_procedure(slot_id=3)

    assert procedure.task.parameters["selected_slot_id"] == 3
    assert procedure.task.parameters["color_is_hard_constraint"] is False
    assert all("1号" not in state.instruction for state in procedure.states)
    assert any("3号" in state.instruction for state in procedure.states)
