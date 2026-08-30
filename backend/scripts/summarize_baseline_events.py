#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def read_rows(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not root.exists():
        return rows
    for path in sorted(root.glob("*.jsonl")):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{line_number}") from exc
    return rows


def latency_summary(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "median_ms": None, "p95_ms": None}
    ordered = sorted(values)
    p95_index = max(0, min(len(ordered) - 1, round(0.95 * len(ordered) + 0.5) - 1))
    return {
        "count": len(ordered),
        "median_ms": round(statistics.median(ordered), 2),
        "p95_ms": round(ordered[p95_index], 2),
    }


def summarize_guidance(rows: list[dict[str, Any]]) -> dict[str, Any]:
    located = [row for row in rows if row.get("event") == "located"]
    verified = [row for row in rows if row.get("event") == "verified"]
    failed = [row for row in rows if str(row.get("event", "")).endswith("_failed")]
    unsafe = [
        row
        for row in verified
        if row.get("safety_invariant_violation")
        or (
            row.get("safe_to_advance")
            and (
                row.get("status") != "completed"
                or row.get("matched_step_id") != row.get("current_step_id")
            )
        )
    ]
    blocked_statuses = {"wrong_operation", "uncertain", "in_progress", "not_started"}
    blocked_advance = [
        row
        for row in verified
        if row.get("status") in blocked_statuses and row.get("safe_to_advance")
    ]
    run_ids = {row.get("run_id") for row in rows if row.get("run_id")}
    return {
        "runs": len(run_ids),
        "located": len(located),
        "verified": len(verified),
        "failed": len(failed),
        "status_counts": dict(sorted(Counter(row.get("status") for row in verified).items())),
        "safe_advances": sum(bool(row.get("safe_to_advance")) for row in verified),
        "safety_invariant_violations": len(unsafe),
        "blocked_status_advances": len(blocked_advance),
        "missing_grounding_on_verify": sum(
            int(row.get("grounded_component_count", 0)) == 0 for row in verified
        ),
        "latency": latency_summary(
            [float(row["latency_ms"]) for row in rows if row.get("latency_ms") is not None]
        ),
    }


def summarize_tracking(rows: list[dict[str, Any]]) -> dict[str, Any]:
    observations = [row for row in rows if row.get("status") is not None]
    sessions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("session_id"):
            sessions[str(row["session_id"])].append(row)
    lost = [row for row in observations if row.get("status") == "lost"]
    qualities = [float(row["quality"]) for row in observations if row.get("quality") is not None]
    return {
        "sessions": len(sessions),
        "observations": len(observations),
        "provider_counts": dict(sorted(Counter(row.get("provider") for row in observations).items())),
        "lost_observations": len(lost),
        "lost_observation_rate": round(len(lost) / len(observations), 4) if observations else None,
        "redetection_requests": sum(bool(row.get("requires_redetection")) for row in observations),
        "contextualized_sessions": sum(
            any(event.get("run_id") and event.get("step_id") for event in events)
            for events in sessions.values()
        ),
        "quality_mean": round(statistics.mean(qualities), 4) if qualities else None,
        "quality_min": round(min(qualities), 4) if qualities else None,
    }


def _safe_divide(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _macro_f1(expected: list[str], predicted: list[str]) -> float | None:
    labels = sorted(set(expected))
    if not labels:
        return None
    scores: list[float] = []
    for label in labels:
        true_positive = sum(
            target == label and guess == label
            for target, guess in zip(expected, predicted)
        )
        false_positive = sum(
            target != label and guess == label
            for target, guess in zip(expected, predicted)
        )
        false_negative = sum(
            target == label and guess != label
            for target, guess in zip(expected, predicted)
        )
        denominator = 2 * true_positive + false_positive + false_negative
        scores.append(2 * true_positive / denominator if denominator else 0.0)
    return round(statistics.mean(scores), 4)


def summarize_labeled(
    guidance_rows: list[dict[str, Any]],
    labels: list[dict[str, Any]],
) -> dict[str, Any]:
    by_id = {
        str(row["decision_id"]): row
        for row in guidance_rows
        if row.get("decision_id")
    }
    joined = [
        (label, by_id[str(label["decision_id"])])
        for label in labels
        if label.get("decision_id") and str(label["decision_id"]) in by_id
    ]
    locate_pairs = [
        (label, prediction)
        for label, prediction in joined
        if prediction.get("event") == "located" and label.get("expected_step_id")
    ]
    verify_pairs = [
        (label, prediction)
        for label, prediction in joined
        if prediction.get("event") == "verified" and label.get("expected_status")
    ]

    correct_steps = sum(
        prediction.get("recommended_step_id") == label.get("expected_step_id")
        for label, prediction in locate_pairs
    )
    expected_statuses = [str(label["expected_status"]) for label, _ in verify_pairs]
    predicted_statuses = [str(prediction.get("status")) for _, prediction in verify_pairs]
    wrong_pairs = [
        (label, prediction)
        for label, prediction in verify_pairs
        if label.get("expected_status") == "wrong_operation"
    ]
    wrong_hits = sum(
        prediction.get("status") == "wrong_operation"
        for _, prediction in wrong_pairs
    )
    unsafe_advances = sum(
        bool(prediction.get("safe_to_advance"))
        and not bool(label.get("should_advance", False))
        for label, prediction in verify_pairs
    )
    covered = sum(
        prediction.get("status") != "uncertain"
        for _, prediction in verify_pairs
    )
    return {
        "labels_total": len(labels),
        "labels_joined": len(joined),
        "labels_missing_prediction": len(labels) - len(joined),
        "step_recall_at_1": _safe_divide(correct_steps, len(locate_pairs)),
        "step_samples": len(locate_pairs),
        "state_macro_f1": _macro_f1(expected_statuses, predicted_statuses),
        "state_samples": len(verify_pairs),
        "wrong_operation_recall": _safe_divide(wrong_hits, len(wrong_pairs)),
        "wrong_operation_samples": len(wrong_pairs),
        "unsafe_advance_rate": _safe_divide(unsafe_advances, len(verify_pairs)),
        "unsafe_advances": unsafe_advances,
        "coverage": _safe_divide(covered, len(verify_pairs)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize image-free Manual2AR baseline telemetry.",
    )
    backend_root = Path(__file__).resolve().parents[1]
    parser.add_argument(
        "--guidance-dir",
        type=Path,
        default=backend_root / "data" / "guidance_events",
    )
    parser.add_argument(
        "--tracking-dir",
        type=Path,
        default=backend_root / "data" / "tracking_events",
    )
    parser.add_argument(
        "--labels",
        type=Path,
        default=backend_root / "data" / "ground_truth" / "labels.jsonl",
    )
    args = parser.parse_args()
    guidance_rows = read_rows(args.guidance_dir)
    labels: list[dict[str, Any]] = []
    if args.labels.exists():
        labels = [
            json.loads(line)
            for line in args.labels.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    result = {
        "guidance": summarize_guidance(guidance_rows),
        "tracking": summarize_tracking(read_rows(args.tracking_dir)),
        "labeled_accuracy": summarize_labeled(guidance_rows, labels),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
