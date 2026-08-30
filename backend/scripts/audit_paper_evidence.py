#!/usr/bin/env python3
"""Audit a Manual2AR paper-evidence export against panel-specific gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _tracking_events(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def _predicate_gate(
    result: dict[str, Any],
    expected_safe: bool,
    required_predicate_ids: list[str] | None = None,
) -> list[str]:
    failures: list[str] = []
    if result.get("safe_to_advance") is not expected_safe:
        failures.append(
            f"safe_to_advance must be {expected_safe}, got {result.get('safe_to_advance')!r}"
        )
    predicates = result.get("predicate_evidence") or result.get("predicates") or []
    necessary = [item for item in predicates if item.get("necessary", True)]
    if not necessary:
        failures.append("no necessary predicate evidence was recorded")
        return failures
    recorded_ids = {
        str(item.get("predicate_id") or "") for item in necessary
    }
    missing_ids = sorted(set(required_predicate_ids or []) - recorded_ids)
    if missing_ids:
        failures.append(
            "missing required predicate evidence: " + ", ".join(missing_ids)
        )
    for item in necessary:
        status = str(item.get("status") or "").lower()
        if expected_safe and status not in {"passed", "completed", "verified", "true"}:
            failures.append(f"necessary predicate {item.get('predicate_id')} did not pass: {status}")
        if not expected_safe and status in {"failed", "false", "error", "incorrect"}:
            break
    else:
        if not expected_safe:
            failures.append("unsafe panel contains no failed necessary predicate")
    return failures


def _tracking_gate(events: list[dict[str, Any]], max_drift: float = 0.05) -> list[str]:
    failures: list[str] = []
    active = [item for item in events if item.get("event") in {"started", "updated"}]
    if not active:
        return ["no active tracking events were recorded"]
    if not any(item.get("polygon_0_1000") for item in active):
        failures.append("tracking contains no recorded polygon")
    if not any(
        item.get("world_anchor_status") in {"anchored", "tracking"}
        for item in active
    ):
        failures.append("no frame records a stable client world anchor")
    bad_quality = [
        item for item in active if item.get("mask_quality_passed") is not True
    ]
    if bad_quality:
        failures.append(f"{len(bad_quality)} tracking frames failed the mask quality gate")
    drift_values = [float(item.get("drift_ratio") or 0.0) for item in active]
    if max(drift_values, default=0.0) > max_drift:
        failures.append(
            f"maximum drift {max(drift_values):.4f} exceeds the {max_drift:.2f} limit"
        )
    if any(item.get("requires_redetection") is True for item in active):
        failures.append("tracking required redetection during the recorded evidence window")
    return failures


def _component_gate(
    evidence: dict[str, Any], required_component_ids: list[str]
) -> list[str]:
    failures: list[str] = []
    components = evidence.get("components") or []
    recorded = {
        str(item.get("component_id") or "")
        for item in components
        if isinstance(item, dict)
    }
    missing = sorted(set(required_component_ids) - recorded)
    if missing:
        failures.append("missing required component geometry: " + ", ".join(missing))
    for item in components:
        if not isinstance(item, dict):
            failures.append("component evidence contains a non-object entry")
            continue
        if not (
            item.get("polygon_0_1000")
            or item.get("mask_file")
            or item.get("bbox_0_1000")
            or item.get("mask_bbox_0_1000")
        ):
            failures.append(
                f"component {item.get('component_id')!r} has no recorded geometry"
            )
    return failures


def audit(spec_path: Path) -> dict[str, Any]:
    spec = _read_json(spec_path)
    panels = spec.get("panels") or []
    report_panels: list[dict[str, Any]] = []
    for panel in panels:
        figure_id = str(panel["figure_id"]).lower()
        failures: list[str] = []
        if panel.get("paper_use_allowed") is not True:
            failures.append("paper_use_allowed is not true")

        result_path = None
        if panel.get("result_json"):
            result_path = Path(panel["result_json"]).expanduser()
            if not result_path.is_absolute():
                result_path = (spec_path.parent / result_path).resolve()
            if not result_path.is_file():
                failures.append(f"result_json does not exist: {result_path}")
                result_path = None

        tracking_path = None
        if panel.get("tracking_log"):
            tracking_path = Path(panel["tracking_log"]).expanduser()
            if not tracking_path.is_absolute():
                tracking_path = (spec_path.parent / tracking_path).resolve()
            if not tracking_path.is_file():
                failures.append(f"tracking_log does not exist: {tracking_path}")
                tracking_path = None

        evidence_path = None
        if panel.get("evidence_json"):
            evidence_path = Path(panel["evidence_json"]).expanduser()
            if not evidence_path.is_absolute():
                evidence_path = (spec_path.parent / evidence_path).resolve()
            if not evidence_path.is_file():
                failures.append(f"evidence_json does not exist: {evidence_path}")
                evidence_path = None

        required_components = list(panel.get("required_component_ids") or [])
        if required_components:
            if evidence_path is None:
                failures.append(
                    f"figure {figure_id} requires evidence_json for component audit"
                )
            else:
                failures.extend(
                    _component_gate(_read_json(evidence_path), required_components)
                )

        if figure_id in {"b", "c"}:
            failures.extend(_tracking_gate(_tracking_events(tracking_path)))
        expected_safe = panel.get("expected_safe_to_advance")
        if figure_id == "d" and expected_safe is None:
            expected_safe = True
        if figure_id == "e" and expected_safe is None:
            expected_safe = True
        if figure_id == "f" and expected_safe is None:
            expected_safe = False
        if expected_safe is not None:
            if result_path is None:
                failures.append(
                    f"figure {figure_id} requires a result_json for predicate audit"
                )
            else:
                failures.extend(
                    _predicate_gate(
                        _read_json(result_path),
                        expected_safe=bool(expected_safe),
                        required_predicate_ids=list(
                            panel.get("required_predicate_ids") or []
                        ),
                    )
                )

        report_panels.append(
            {
                "figure_id": figure_id,
                "run_id": panel.get("run_id"),
                "passed": not failures,
                "failures": failures,
            }
        )

    return {
        "schema_version": "paper-evidence-audit-1.0",
        "passed": bool(report_panels) and all(item["passed"] for item in report_panels),
        "panels": report_panels,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit(args.spec.resolve())
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    raise SystemExit(0 if report["passed"] else 2)


if __name__ == "__main__":
    main()
