from __future__ import annotations

import json

from app.guidance_events import GuidanceEventLogger
from app.models import (
    ComponentBox,
    StateLocalizationRequest,
    StateLocalizationResult,
    VerificationRequest,
    VerificationResult,
)


def test_guidance_telemetry_is_image_free_and_correlates_one_run(tmp_path) -> None:
    logger = GuidanceEventLogger(tmp_path, "baseline-model")
    locate_request = StateLocalizationRequest(
        run_id="run-1",
        procedure_id="procedure-1",
        image_base64="never-written",
        mode="ollama",
    )
    locate_result = StateLocalizationResult(
        observed_summary="private scene description",
        completed_step_ids=["S0"],
        recommended_step_id="S1",
        evidence="private evidence",
        confidence=0.8,
        requires_human_confirmation=True,
        unavailable_checks=[],
        component_boxes_0_1000=[],
    )
    logger.located(locate_request, locate_result, 1234.567)

    verify_request = VerificationRequest(
        run_id="run-1",
        procedure_id="procedure-1",
        current_step_id="S1",
        history=["S0"],
        image_base64="never-written",
        mode="ollama",
    )
    verify_result = VerificationResult(
        status="completed",
        matched_step_id="S1",
        evidence="private evidence",
        component_boxes_0_1000=[
            ComponentBox(
                component_id="source:object",
                bbox_0_1000=[100, 100, 200, 200],
            )
        ],
        manual_page=1,
        manual_section="step",
        confidence=0.8,
        safe_to_advance=True,
        next_action="private instruction",
    )
    logger.verified(verify_request, verify_result, 500.0)

    path = next(tmp_path.glob("*.jsonl"))
    text = path.read_text(encoding="utf-8")
    rows = [json.loads(line) for line in text.splitlines()]
    assert [row["event"] for row in rows] == ["located", "verified"]
    assert all(len(row["decision_id"]) == 32 for row in rows)
    assert rows[0]["decision_id"] != rows[1]["decision_id"]
    assert all(row["run_id"] == "run-1" for row in rows)
    assert rows[1]["safe_to_advance"] is True
    assert rows[1]["safety_invariant_violation"] is False
    assert rows[0]["latency_ms"] == 1234.57
    assert "image_base64" not in text
    assert "private scene description" not in text
    assert "private evidence" not in text
    assert "private instruction" not in text


def test_guidance_telemetry_flags_an_unsafe_advance_invariant(tmp_path) -> None:
    logger = GuidanceEventLogger(tmp_path, "baseline-model")
    request = VerificationRequest(
        run_id="run-unsafe",
        procedure_id="procedure-1",
        current_step_id="S2",
        image_base64="never-written",
    )
    result = VerificationResult(
        status="wrong_operation",
        matched_step_id="S2",
        evidence="",
        component_boxes_0_1000=[],
        manual_page=1,
        manual_section="step",
        confidence=0.9,
        safe_to_advance=True,
        next_action="recover",
    )
    logger.verified(request, result, 1.0)

    row = json.loads(next(tmp_path.glob("*.jsonl")).read_text())
    assert row["safety_invariant_violation"] is True
