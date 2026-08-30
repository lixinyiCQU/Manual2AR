from __future__ import annotations

from scripts.evaluate_paper_static import (
    PlateInspectionResult,
    plate_server_gate,
)


def _plate_result(*, residue_status: str = "completed") -> PlateInspectionResult:
    return PlateInspectionResult.model_validate(
        {
            "device_match": True,
            "predicates": [
                {
                    "predicate_id": predicate_id,
                    "status": residue_status if predicate_id == "no_residue" else "completed",
                    "confidence": 0.91,
                    "bbox_0_1000": [100, 200, 800, 700],
                    "visible_evidence": "visible plate region",
                    "failure_reason": "visible residue" if predicate_id == "no_residue" else "",
                    "correction_instruction": "remove residue" if predicate_id == "no_residue" else "",
                }
                for predicate_id in (
                    "plate_present",
                    "plate_aligned",
                    "surface_clear",
                    "no_residue",
                )
            ],
        }
    )


def test_plate_server_gate_requires_all_four_visible_predicates() -> None:
    safe, reasons = plate_server_gate(_plate_result())

    assert safe is True
    assert reasons == []


def test_plate_server_gate_rejects_visible_residue() -> None:
    safe, reasons = plate_server_gate(_plate_result(residue_status="failed"))

    assert safe is False
    assert any("no_residue is failed" in reason for reason in reasons)
