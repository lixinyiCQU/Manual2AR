from __future__ import annotations

from scripts.summarize_baseline_events import summarize_labeled


def test_labeled_summary_reports_research_metrics() -> None:
    predictions = [
        {
            "decision_id": "locate-1",
            "event": "located",
            "recommended_step_id": "S2",
        },
        {
            "decision_id": "verify-1",
            "event": "verified",
            "status": "wrong_operation",
            "safe_to_advance": False,
        },
        {
            "decision_id": "verify-2",
            "event": "verified",
            "status": "completed",
            "safe_to_advance": True,
        },
    ]
    labels = [
        {"decision_id": "locate-1", "expected_step_id": "S2"},
        {
            "decision_id": "verify-1",
            "expected_status": "wrong_operation",
            "should_advance": False,
        },
        {
            "decision_id": "verify-2",
            "expected_status": "wrong_operation",
            "should_advance": False,
        },
    ]

    summary = summarize_labeled(predictions, labels)
    assert summary["step_recall_at_1"] == 1.0
    assert summary["state_macro_f1"] == 0.6667
    assert summary["wrong_operation_recall"] == 0.5
    assert summary["unsafe_advance_rate"] == 0.5
    assert summary["coverage"] == 1.0
