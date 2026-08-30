from __future__ import annotations

import json

import pytest
from PIL import Image

from scripts.prepare_paper_package import prepare


def test_prepare_renders_recorded_geometry_audits_and_exports(tmp_path) -> None:
    Image.new("RGB", (320, 240), "white").save(tmp_path / "raw.png")
    (tmp_path / "evidence.json").write_text(
        json.dumps(
            {
                "components": [
                    {
                        "component_id": "build_plate",
                        "polygon_0_1000": [[100, 100], [900, 100], [900, 800], [100, 800]],
                        "mask_quality_passed": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "result.json").write_text(
        json.dumps(
            {
                "safe_to_advance": True,
                "predicates": [
                    {
                        "predicate_id": predicate_id,
                        "status": "completed",
                        "necessary": True,
                    }
                    for predicate_id in (
                        "plate_present",
                        "plate_aligned",
                        "surface_clear",
                        "no_residue",
                    )
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
                        "figure_id": "e",
                        "run_id": "e1",
                        "title": "Build plate inspection",
                        "caption": "Visible plate state.",
                        "claim": "Visible state only.",
                        "raw_image": "raw.png",
                            "evidence_json": "evidence.json",
                            "result_json": "result.json",
                            "required_predicate_ids": [
                                "plate_present",
                                "plate_aligned",
                                "surface_clear",
                                "no_residue",
                            ],
                            "overlay_image": None,
                        "paper_use_allowed": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    manifest = prepare(spec, tmp_path / "paper")

    assert len(manifest["panels"]) == 1
    assert (tmp_path / "paper" / "paper_evidence_audit.json").is_file()
    assert (tmp_path / "paper" / "figures_300dpi" / "figure_e.png").is_file()


def test_prepare_stops_before_export_when_paper_use_is_not_approved(tmp_path) -> None:
    Image.new("RGB", (320, 240), "white").save(tmp_path / "raw.png")
    Image.new("RGB", (320, 240), "white").save(tmp_path / "overlay.png")
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps(
            {
                "panels": [
                    {
                        "figure_id": "a",
                        "title": "Component grounding",
                        "caption": "test",
                        "claim": "test",
                        "raw_image": "raw.png",
                        "overlay_image": "overlay.png",
                        "paper_use_allowed": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="audit failed"):
        prepare(spec, tmp_path / "paper")

    report = json.loads(
        (tmp_path / "paper" / "paper_evidence_audit.json").read_text(encoding="utf-8")
    )
    assert report["passed"] is False
