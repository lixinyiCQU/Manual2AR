"""Replay independently specified symbolic cases; never label them as camera GT."""
import json
import platform
from pathlib import Path

import pydantic
from pydantic import Field

from .gt import Identity, Strict, Text, digest, encoded
from .state import Session


class Step(Strict):
    event: dict
    expect: dict = Field(default_factory=dict)
    expect_error: str | None = None


class Case(Strict):
    id: Identity
    intent: Text
    initial_expect: dict = Field(default_factory=dict)
    steps: list[Step] = Field(min_length=1)


def assert_subset(actual, expected):
    for key, value in expected.items():
        if key not in actual:
            raise AssertionError("Missing result field: " + key)
        if isinstance(value, dict):
            assert_subset(actual[key], value)
        elif actual[key] != value:
            raise AssertionError(f"{key}: expected {value!r}, got {actual[key]!r}")


def replay(bundle: Path, case: Case):
    session = Session.from_bundle(bundle, "case." + case.id, case.intent)
    assert_subset(session.plan(), case.initial_expect)
    trace = []
    for i, step in enumerate(case.steps, 1):
        command = {"id": case.id + ".e" + str(i), **session.stamp(), **step.event}
        if command["kind"] == "observation":
            command.setdefault("origin", "controlled_annotation")
            command.setdefault("frame_id", session.last_frame + 1)
            command["values"] = {cid: value if isinstance(value, dict) else
                                 dict(value=value, reason="insufficient_detail" if value == "unknown" else "observed")
                                 for cid, value in command["values"].items()}
            command.setdefault("source_sha256", digest(encoded(dict(case=case.id, step=i, annotation=command["values"]))))
        elif command["kind"] == "manual":
            command.setdefault("origin", "controlled_operator")
            command.setdefault("statement", "受控测试中逐项提供的人工确认；并非实物操作记录。")
        before = session.plan()
        try:
            plan = session.apply(command)
        except ValueError as error:
            if not step.expect_error or step.expect_error not in str(error):
                raise
            if session.plan() != before:
                raise AssertionError("Rejected event changed the session")
            plan = session.plan()
            trace.append(dict(step=i, result="expected_rejection", error=str(error), plan=plan))
        else:
            if step.expect_error:
                raise AssertionError("Invalid event was accepted at step " + str(i))
            trace.append(dict(step=i, result="accepted", plan=plan))
        assert_subset(plan, step.expect)
    return dict(id=case.id, status="passed", trace=trace, events=session.events)


def run(bundle: Path, cases_path: Path, output: Path):
    data = json.loads(cases_path.read_bytes())
    if data.get("schema_version") != "baseline-state-cases-v1" or data.get("evidence_kind") != "controlled_symbolic_facts":
        raise ValueError("Expected explicitly controlled symbolic cases")
    cases = [Case.model_validate(row) for row in data["cases"]]
    if not cases or len({c.id for c in cases}) != len(cases):
        raise ValueError("Case identities must be nonempty and unique")
    Session.from_bundle(bundle, "validation.preflight", "核对状态验证输入")
    output.mkdir(parents=True, exist_ok=False)
    results = []
    for case in cases:
        try:
            result = replay(bundle, case)
        except (ValueError, AssertionError) as error:
            result = dict(id=case.id, status="failed", error=str(error))
        results.append(result)
    report = dict(schema_version="baseline-state-results-v1", evidence_kind="controlled_symbolic_facts",
                  task_sha256=digest((bundle / "task.json").read_bytes()), cases_sha256=digest(cases_path.read_bytes()),
                  implementation_sha256=digest(encoded({p.name: digest(p.read_bytes()) for p in Path(__file__).parent.glob("*.py")})),
                  python_version=platform.python_version(), pydantic_version=pydantic.__version__,
                  real_model_calls=0, physical_camera_tested=False, ar_tested=False,
                  passed=sum(r["status"] == "passed" for r in results), total=len(results), results=results)
    (output / "results.json").write_bytes(encoded(report))
    (output / "cases.json").write_bytes(cases_path.read_bytes())
    lines = ["# 状态与调度验证", "", f"{report['passed']} / {report['total']} 个受控符号场景通过。", "",
             "本报告只验证给定事实后的规则和调度，不包含真实图像、模型、相机或 AR 结果。", ""]
    lines += [f"- {r['id']}：{r['status']}" + ("；" + r["error"] if r["status"] == "failed" else "") for r in results]
    (output / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
