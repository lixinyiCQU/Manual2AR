"""Guidance eligibility is independent from accepting an operation's result."""
from pathlib import Path

import pytest

from manual2ar_baseline.ar import Bindings
from manual2ar_baseline.gt import digest, encoded, load_bundle
from manual2ar_baseline.state import Session


BUNDLE = Path(__file__).resolve().parents[1] / "ground_truth/u7/v1/state-validation"


def session(*, target=None, policy="scene_guided"):
    _, task = load_bundle(BUNDLE)
    return Session(task, "guidance", "安装料盘支架", target_node_ids=target, guidance_policy=policy)


def event(value, kind, **fields):
    return value.apply(dict(id="event." + str(value.revision), **value.stamp(), kind=kind, **fields))


def photo(value, readings):
    return event(value, "observation", origin="controlled_annotation", frame_id=value.last_frame + 1,
                 source_sha256="a" * 64, values=readings)


def reading(value, reason="observed"):
    return dict(value=value, reason=reason)


def installed_base(value, holder=None):
    readings = {c: reading("true") for c in value.nodes["install_base"].completion_ids
                if value.conditions[c].channel == "vision"}
    readings.update(holder or {})
    photo(value, readings)
    for cid in value.nodes["install_base"].completion_ids:
        if value.conditions[cid].channel == "manual":
            event(value, "manual", origin="controlled_operator", statement="Controlled check", values={cid: "true"})
    return value.plan()


def bindings(value):
    return Bindings(task_sha256=value.task_sha, resources={"fixture": "a" * 64}, presentations=[
        dict(node_id=n.id, action_id="action." + n.id, presentation_id="presentation." + n.id) for n in value.task.nodes])


def test_base_confirmation_unlocks_holder_guidance_without_claiming_completion():
    value = session()
    unknown_holder = {c: reading("unknown", "unresolved_identity")
                      for c in value.nodes["install_holder"].completion_ids if value.conditions[c].channel == "vision"}
    plan = installed_base(value, unknown_holder)
    assert plan["mode"] == "operate" and plan["node_id"] == "install_holder"
    assert plan["completed_node_ids"] == ["install_base"]
    assert "尚未确认" in plan["reason"]
    assert all(value.facts[c].value == "unknown" for c in unknown_holder)
    execution = bindings(value).execution(value)
    assert execution["guidance_allowed"] and not execution["complete"]
    assert execution["steps"][1]["status"] == "unknown"
    assert execution["remaining_state_ids"] == ["install_holder"]


def test_unknown_root_needs_scene_evidence_and_manual_cannot_replace_vision():
    value = session()
    assert value.plan()["mode"] == "request_view"
    photo(value, {c: reading("unknown", "insufficient_detail") for c in value.nodes["install_base"].completion_ids
                  if value.conditions[c].channel == "vision"})
    assert value.plan()["mode"] == "request_view"
    before = value.plan()
    with pytest.raises(ValueError, match="visual/prerequisite"):
        event(value, "manual", origin="controlled_operator", statement="Not enough", values={"c.base.secure": "true"})
    assert value.plan() == before


def test_partial_holder_evidence_does_not_block_guidance_when_prerequisites_pass():
    value = session()
    installed_base(value)
    plan = photo(value, {"c.holder.connection": reading("true"),
                         "c.holder.appearance": reading("unknown", "insufficient_detail")})
    assert plan["mode"] == "operate" and plan["node_id"] == "install_holder"
    assert bindings(value).execution(value)["guidance_allowed"]
    assert not bindings(value).execution(value)["complete"]
    assert value.facts["c.holder.appearance"].value == "unknown"
    with pytest.raises(ValueError, match="visual/prerequisite"):
        event(value, "manual", origin="controlled_operator", statement="Cannot override detail", values={"c.holder.direction": "true"})


def test_partial_root_evidence_still_requires_remaining_visual_conditions():
    value = session()
    plan = photo(value, {"c.base.mount": reading("true"),
                         "c.base.screws": reading("unknown", "insufficient_detail")})
    assert plan["mode"] == "request_view" and plan["node_id"] == "install_base"
    assert not bindings(value).execution(value)["guidance_allowed"]


def test_negative_current_result_receives_guidance_and_still_needs_verification():
    value = session(target=["install_base"])
    plan = photo(value, {"c.base.mount": reading("false")})
    assert plan["mode"] == "operate" and plan["completed_node_ids"] == []
    assert value.facts["c.base.mount"].value == "false"
    assert not bindings(value).execution(value)["complete"]


def test_base_only_scope_finishes_without_instructing_holder_or_changing_task():
    value = session(target=["install_base"])
    _, original = load_bundle(BUNDLE)
    assert value.task_sha == digest(encoded(original.model_dump()))
    plan = installed_base(value, {"c.holder.connection": reading("false")})
    assert plan["mode"] == "complete" and plan["needed_node_ids"] == ["install_base"]
    execution = bindings(value).execution(value)
    assert execution["action_id"] == "action.install_base"
    assert execution["remaining_state_ids"] == []
    assert [s["node_id"] for s in execution["steps"]] == ["install_base"]


def test_slide_only_scope_includes_base_as_prerequisite():
    value = session(target=["install_holder"])
    execution = bindings(value).execution(value)
    assert execution["needed_node_ids"] == ["install_base", "install_holder"]
    assert execution["prerequisite_only"] and not execution["steps"][0]["is_target"]
    assert installed_base(value)["mode"] == "operate"
    assert not bindings(value).execution(value)["prerequisite_only"]


def test_new_context_removes_guidance_eligibility_and_original_policy_is_unchanged():
    value = session()
    assert installed_base(value)["mode"] == "operate"
    plan = event(value, "context_change", context_id="new-device", reason="Different setup")
    assert plan["mode"] == "request_view" and plan["completed_node_ids"] == []
    original = session(policy="strict")
    assert installed_base(original)["mode"] == "request_view"


@pytest.mark.parametrize("target", [[], ["unknown"], ["install_base", "install_base"]])
def test_invalid_scope_cannot_start(target):
    with pytest.raises(ValueError, match="scope"):
        session(target=target)
