from __future__ import annotations

import json

import pytest
from PIL import Image

from scripts.export_paper_evidence import export


def _image(path, color) -> None:
    Image.new("RGB", (180, 120), color=color).save(path)


def test_export_keeps_real_evidence_and_writes_300_dpi_manifest(tmp_path) -> None:
    _image(tmp_path / "raw.png", (230, 230, 230))
    _image(tmp_path / "overlay.png", (20, 190, 210))
    (tmp_path / "result.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "safe_to_advance": True,
                "predicate_evidence": [
                    {"predicate_id": "slot_correct", "status": "passed", "necessary": True}
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "tracking.jsonl").write_text(
        '{"drift_ratio": 0.012, "world_anchor_status": "tracking"}\n',
        encoding="utf-8",
    )
    spec = {
        "panels": [
            {
                "figure_id": "b",
                "run_id": "B_RUN_001",
                "title": "Guided spool placement",
                "caption": "Recorded segmentation and world-anchored guidance.",
                "claim": "Text-to-spatial guidance for one confirmed AMS Lite slot.",
                "raw_image": "raw.png",
                "overlay_image": "overlay.png",
                "result_json": "result.json",
                "tracking_log": "tracking.jsonl",
                "paper_use_allowed": True,
                "model_version": "test-model",
            }
        ]
    }
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    manifest = export(spec_path, tmp_path / "export")

    exported = Image.open(tmp_path / "export" / "figures_300dpi" / "figure_b.png")
    assert exported.width == 3600
    assert round(exported.info["dpi"][0]) == 300
    panel = manifest["panels"][0]
    assert panel["raw_sha256"]
    assert panel["overlay_sha256"]
    assert panel["tracking_log_sha256"]
    assert panel["paper_use_allowed"] is True
    assert manifest["layout_only"] is True


def test_export_refuses_missing_recorded_overlay(tmp_path) -> None:
    _image(tmp_path / "raw.png", (230, 230, 230))
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(
        json.dumps(
            {
                "panels": [
                    {
                        "figure_id": "a",
                        "title": "Component grounding",
                        "caption": "test",
                        "claim": "test",
                        "raw_image": "raw.png",
                        "overlay_image": "missing.png",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(FileNotFoundError, match="overlay_image"):
        export(spec_path, tmp_path / "export")
