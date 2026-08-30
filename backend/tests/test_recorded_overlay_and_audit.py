from __future__ import annotations

import json

from PIL import Image

from scripts.audit_paper_evidence import audit
from scripts.render_recorded_overlay import render


def test_overlay_uses_recorded_polygon_and_writes_provenance(tmp_path) -> None:
    raw = tmp_path / "raw.png"
    Image.new("RGB", (1000, 600), "white").save(raw)
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        json.dumps(
            {
                "components": [
                    {
                        "component_id": "target:spool_holder_3",
                        "display_label": "3号空轴",
                        "polygon_0_1000": [[200, 250], [500, 250], [520, 700], [180, 700]],
                        "mask_quality_passed": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    overlay = tmp_path / "overlay.png"
    provenance = tmp_path / "overlay.provenance.json"

    result = render(
        raw_path=raw,
        evidence_path=evidence,
        output_path=overlay,
        provenance_path=provenance,
    )

    assert overlay.is_file()
    assert provenance.is_file()
    assert result["rendered_components"][0]["geometry_kind"] == "polygon"
    assert result["evidence_geometry_modified"] is False


def test_audit_checks_tracking_and_safe_gate(tmp_path) -> None:
    tracking = tmp_path / "tracking.jsonl"
    tracking.write_text(
        json.dumps(
            {
                "event": "updated",
                "polygon_0_1000": [[100, 100], [200, 100], [200, 200]],
                "mask_quality_passed": True,
                "world_anchor_status": "anchored",
                "drift_ratio": 0.03,
                "requires_redetection": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    safe = tmp_path / "safe.json"
    safe.write_text(
        json.dumps(
            {
                "safe_to_advance": True,
                "predicate_evidence": [
                    {"predicate_id": "slot", "status": "passed", "necessary": True}
                ],
            }
        ),
        encoding="utf-8",
    )
    unsafe = tmp_path / "unsafe.json"
    unsafe.write_text(
        json.dumps(
            {
                "safe_to_advance": False,
                "predicate_evidence": [
                    {"predicate_id": "path", "status": "failed", "necessary": True}
                ],
            }
        ),
        encoding="utf-8",
    )
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps(
            {
                "panels": [
                    {
                        "figure_id": "b",
                        "run_id": "b1",
                        "tracking_log": "tracking.jsonl",
                        "paper_use_allowed": True,
                    },
                    {
                        "figure_id": "d",
                        "run_id": "d1",
                        "result_json": "safe.json",
                        "paper_use_allowed": True,
                    },
                    {
                        "figure_id": "f",
                        "run_id": "f1",
                        "result_json": "unsafe.json",
                        "paper_use_allowed": True,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    report = audit(spec)

    assert report["passed"] is True


def test_audit_rejects_drift_and_false_completion(tmp_path) -> None:
    tracking = tmp_path / "tracking.jsonl"
    tracking.write_text(
        json.dumps(
            {
                "event": "updated",
                "polygon_0_1000": [[100, 100], [200, 100], [200, 200]],
                "mask_quality_passed": True,
                "world_anchor_status": "anchored",
                "drift_ratio": 0.09,
                "requires_redetection": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    unsafe = tmp_path / "result.json"
    unsafe.write_text(
        json.dumps(
            {
                "safe_to_advance": False,
                "predicate_evidence": [
                    {"predicate_id": "ptfe", "status": "failed", "necessary": True}
                ],
            }
        ),
        encoding="utf-8",
    )
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps(
            {
                "panels": [
                    {
                        "figure_id": "b",
                        "tracking_log": "tracking.jsonl",
                        "paper_use_allowed": True,
                    },
                    {
                        "figure_id": "d",
                        "result_json": "result.json",
                        "paper_use_allowed": True,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    report = audit(spec)

    assert report["passed"] is False
    assert any("maximum drift" in item for item in report["panels"][0]["failures"])
    assert any("safe_to_advance" in item for item in report["panels"][1]["failures"])


def test_audit_rejects_safe_result_missing_required_predicate_ids(tmp_path) -> None:
    result = tmp_path / "result.json"
    result.write_text(
        json.dumps(
            {
                "safe_to_advance": True,
                "predicates": [
                    {
                        "predicate_id": "spool_stably_installed",
                        "status": "completed",
                        "necessary": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps(
            {
                "panels": [
                    {
                        "figure_id": "d",
                        "result_json": "result.json",
                        "expected_safe_to_advance": True,
                        "required_predicate_ids": [
                            "spool_stably_installed",
                            "filament_entered_selected_slot_feeder",
                        ],
                        "paper_use_allowed": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = audit(spec)

    assert report["passed"] is False
    assert any(
        "filament_entered_selected_slot_feeder" in failure
        for failure in report["panels"][0]["failures"]
    )


def test_audit_requires_all_component_grounding_geometry(tmp_path) -> None:
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        json.dumps(
            {
                "components": [
                    {
                        "component_id": "build_plate",
                        "bbox_0_1000": [100, 100, 800, 700],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps(
            {
                "panels": [
                    {
                        "figure_id": "a",
                        "evidence_json": "evidence.json",
                        "required_component_ids": ["build_plate", "touchscreen"],
                        "paper_use_allowed": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = audit(spec)

    assert report["passed"] is False
    assert any(
        "touchscreen" in failure for failure in report["panels"][0]["failures"]
    )
