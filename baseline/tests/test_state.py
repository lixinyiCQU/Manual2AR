from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from manual2ar_baseline.gt import TaskDefinition, digest, encoded, load_bundle, normalize
from manual2ar_baseline.state import Reading, Session
from manual2ar_baseline.validation import Case, replay, run


BASELINE = Path(__file__).resolve().parents[1]
GT = BASELINE / "ground_truth/u7/v1"
BUNDLE = GT / "state-validation"
CASES = BASELINE / "validation/u7/state-cases.json"
FIXTURES = json.loads(CASES.read_bytes())["cases"]


@pytest.mark.parametrize("case", FIXTURES, ids=[r["id"] for r in FIXTURES])
def test_independent_controlled_cases(case):
    assert replay(BUNDLE, Case.model_validate(case))["status"] == "passed"


def test_review_is_delegated_and_limited_to_state_validation():
    _, task = load_bundle(BUNDLE)
    review = json.loads((BUNDLE / "review.json").read_bytes())
    receipt = json.loads((BUNDLE / "human-review.json").read_bytes())
    assert review["status"] == "approved_for_state_validation"
    assert review["validation_scope"] == "controlled_facts_only"
    assert review["scene_labels"] == review["spatial_labels"] == "not_provided"
    assert not task.review_items
    manual = {c.id for c in task.conditions if c.channel == "manual"}
    assert manual == {"c.base.direction", "c.base.secure", "c.holder.direction"}
    assert receipt["delegation"]["reviewer"] == "assistant_under_user_delegation"
    for row in receipt["decisions"]:
        if row["id"] in receipt["delegation"]["decision_ids"]:
            assert row["user_statement"] == receipt["delegation"]["authorization_quote"]
    assert receipt["reviewed_task_sha256"] == digest((GT / "candidate-v2/task.json").read_bytes())


def test_state_bundle_rebuild_preserves_exact_bytes(tmp_path):
    normalize(GT / "sources.json", GT / "state-validation-input/mapping.json", tmp_path / "bundle",
              GT / "state-validation-input/review-decisions.json")
    for path in BUNDLE.iterdir():
        assert path.read_bytes() == (tmp_path / "bundle" / path.name).read_bytes()


@pytest.mark.parametrize("folder", ["candidate", "candidate-v2"])
def test_unapproved_candidate_cannot_start_session(folder):
    with pytest.raises(ValueError, match="approved for state validation"):
        Session.from_bundle(GT / folder, "test", "安装支架")


def test_review_without_delegation_does_not_gain_state_approval(tmp_path):
    receipt = json.loads((BUNDLE / "human-review.json").read_bytes())
    del receipt["delegation"]
    path = tmp_path / "review.json"
    path.write_bytes(encoded(receipt))
    normalize(GT / "sources.json", GT / "state-validation-input/mapping.json", tmp_path / "bundle", path)
    with pytest.raises(ValueError, match="approved for state validation"):
        Session.from_bundle(tmp_path / "bundle", "test", "安装支架")


def test_claim_and_no_claim_choose_identical_next_work():
    results = []
    for name in ("claim_same_verified_base", "no_claim_same_verified_base"):
        case = next(row for row in FIXTURES if row["id"] == name)
        plan = replay(BUNDLE, Case.model_validate(case))["trace"][-1]["plan"]
        results.append({k: plan[k] for k in ("mode", "node_id", "condition_ids", "completed_node_ids", "node_states")})
    assert results[0] == results[1]


@pytest.mark.parametrize("reading", [dict(value="unknown", reason="observed"), dict(value="true", reason="occluded")])
def test_unobserved_conclusions_are_rejected(reading):
    with pytest.raises(ValueError):
        Reading.model_validate(reading)


def generic_task():
    value = dict(schema_version="baseline-task-v1", id="other_device.assembly", version="1", device_id="other_device",
                 title="Other assembly", scope="Controlled contract test",
                 objects=[dict(id="part", name="Part", source_ids=["source"])],
                 requirements=[], conditions=[], nodes=[], goal_condition_ids=["done3"])
    for i in range(1, 4):
        value["requirements"].append(dict(id=f"r{i}", kind="outcome", source_id="source", quote="Connected"))
        value["conditions"].append(dict(id=f"done{i}", statement="Connection checked", object_ids=["part"],
                                        requirement_ids=[f"r{i}"], channel="manual", scope="nonvisual_confirmation",
                                        basis="direct_reference", standard_status="manual_definition", definition="Explicit check"))
        value["nodes"].append(dict(id=f"n{i}", instruction="Connect", object_ids=["part"], requirement_ids=[f"r{i}"],
                                   depends_on=[f"n{i-1}"] if i > 1 else [], completion_ids=[f"done{i}"]))
    return value


def send(session, kind, **fields):
    return session.apply({"id": "event." + str(session.revision), **session.stamp(), "kind": kind, **fields})


def test_other_device_repeated_actions_and_three_nodes():
    session = Session(TaskDefinition.model_validate(generic_task()), "other_session", "Connect parts")
    assert session.plan()["node_id"] == "n1"
    for i in range(1, 4):
        plan = send(session, "manual", origin="controlled_operator", statement="Explicit controlled check", values={f"done{i}": "true"})
        assert plan["completed_node_ids"] == [f"n{j}" for j in range(1, i + 1)]
    assert plan["mode"] == "complete"


def test_external_precondition_is_an_operation_guard_not_a_permanent_goal():
    value = generic_task()
    value["nodes"] = value["nodes"][:1]
    value["conditions"] = value["conditions"][:1]
    value["requirements"] = value["requirements"][:1]
    value["goal_condition_ids"] = ["done1"]
    value["conditions"].append(dict(id="available", statement="Material available", object_ids=["part"], requirement_ids=["r1"],
                                    channel="vision", scope="visible_state", basis="direct_reference",
                                    standard_status="needs_visual_standard", definition="Controlled material availability"))
    value["nodes"][0]["precondition_ids"] = ["available"]
    session = Session(TaskDefinition.model_validate(value), "external", "Connect")
    assert session.plan()["condition_ids"] == ["available"]
    send(session, "observation", origin="controlled_annotation", frame_id=1, source_sha256="a" * 64,
         values={"available": dict(value="true", reason="observed")})
    assert session.plan()["mode"] == "ask_manual"
    send(session, "manual", origin="controlled_operator", statement="Controlled connection confirmed", values={"done1": "true"})
    plan = send(session, "observation", origin="controlled_annotation", frame_id=2, source_sha256="b" * 64,
                values={"available": dict(value="false", reason="observed")})
    assert plan["mode"] == "complete"


def test_condition_producer_edges_are_ordered_and_cycles_rejected():
    value = generic_task()
    value["nodes"][1]["depends_on"] = []
    value["nodes"][1]["precondition_ids"] = ["done1"]
    value["nodes"].reverse()
    session = Session(TaskDefinition.model_validate(value), "implicit", "Connect")
    assert session.order == ["n1", "n2", "n3"]
    value["nodes"][2]["precondition_ids"] = ["done2"]
    with pytest.raises(ValueError, match="dependency cycle"):
        Session(TaskDefinition.model_validate(value), "cycle", "Connect")


def test_manual_batch_is_atomic_when_one_item_has_unmet_dependencies():
    session = Session(TaskDefinition.model_validate(generic_task()), "atomic", "Connect")
    before = session.plan()
    with pytest.raises(ValueError, match="prerequisite"):
        send(session, "manual", origin="controlled_operator", statement="Controlled check", values={"done1": "true", "done3": "true"})
    assert session.plan() == before and session.events == []
    assert send(session, "manual", origin="controlled_operator", statement="Controlled check", values={"done1": "true"})["completed_node_ids"] == ["n1"]


def test_session_copies_definition_and_detects_internal_mutation():
    task = TaskDefinition.model_validate(generic_task())
    session = Session(task, "identity", "Connect")
    task.title = "External edit"
    assert session.task.title != task.title
    session.task.scope = "Changed after binding"
    with pytest.raises(ValueError, match="definition changed"):
        send(session, "manual", origin="controlled_operator", statement="Controlled check", values={"done1": "true"})
    assert session.revision == 0


def test_batch_report_retains_expected_and_actual_trace(tmp_path):
    report = run(BUNDLE, CASES, tmp_path / "report")
    assert report["passed"] == report["total"] == 32
    assert report["evidence_kind"] == "controlled_symbolic_facts"
    assert report["real_model_calls"] == 0 and not report["physical_camera_tested"] and not report["ar_tested"]
    assert (tmp_path / "report/cases.json").read_bytes() == CASES.read_bytes()
    assert len(report["results"][0]["trace"]) == len(FIXTURES[0]["steps"])
    with pytest.raises(FileExistsError):
        run(BUNDLE, CASES, tmp_path / "report")


def test_cli_returns_failure_when_expected_decision_is_wrong(tmp_path):
    data = json.loads(CASES.read_bytes())
    data["cases"] = [deepcopy(data["cases"][0])]
    data["cases"][0]["steps"][0]["expect"]["mode"] = "complete"
    path = tmp_path / "cases.json"
    path.write_bytes(encoded(data))
    process = subprocess.run([sys.executable, "-B", "-m", "manual2ar_baseline", "validate-state", "--bundle", str(BUNDLE),
                              "--cases", str(path), "--output", str(tmp_path / "report")],
                             env={**os.environ, "PYTHONPATH": str(BASELINE / "src")}, capture_output=True, text=True)
    assert process.returncode == 1 and "State validation failed" in process.stderr
    report = json.loads((tmp_path / "report/results.json").read_bytes())
    assert report["passed"] == 0 and report["results"][0]["status"] == "failed"
