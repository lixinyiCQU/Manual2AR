#!/usr/bin/env python3
"""Run the public Manual2AR pre-training baseline contract end to end.

This deliberately uses the HTTP API instead of importing the backend service.
It validates the same boundaries exercised by Unity: manual compilation,
closed-loop verification, source/target grounding, SAM2 session startup,
temporal update, and conservative loss under full occlusion.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from PIL import Image
import io


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANUAL = Path(
    ROOT / "output/pdf/TWO_OBJECT_BOOK_PEN_01_manual_v1.pdf"
)
DEFAULT_BOOK_FRAME = (
    ROOT
    / "backend/data/debug_captures/"
    "20260803T155607_849422Z_verify_72edc82a.jpg"
)
DEFAULT_PEN_FRAME = (
    ROOT
    / "backend/data/debug_captures/"
    "20260803T155623_973406Z_verify_cd73f80f.jpg"
)


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def validate_procedure(procedure: dict[str, Any]) -> dict[str, Any]:
    states = procedure.get("states")
    _assert(isinstance(states, list) and len(states) >= 3, "fewer than 3 states")
    state_ids = [state.get("state_id") for state in states]
    _assert(len(state_ids) == len(set(state_ids)), "duplicate state ids")
    _assert(state_ids == [f"S{index}" for index in range(len(states))], "non-canonical state ids")

    relationship_markers = (
        "打开",
        "左",
        "右",
        "上",
        "下",
        "水平",
        "竖直",
        "接触",
        "open",
        "left",
        "right",
        "horizontal",
        "vertical",
    )
    initial_post = " ".join(states[0].get("postconditions") or []).lower()
    _assert(
        any(marker in initial_post for marker in relationship_markers),
        "initial state contains component nouns but no observable relation",
    )

    for state in states:
        pre = state.get("preconditions") or []
        post = state.get("postconditions") or []
        wrong = state.get("wrong_states") or []
        targets = state.get("target_components") or []
        _assert(post, f"{state.get('state_id')} has no postconditions")
        _assert(pre != post, f"{state.get('state_id')} pre == post")
        _assert(wrong != post and wrong != pre, f"{state.get('state_id')} wrong state duplicates a valid state")
        _assert(targets, f"{state.get('state_id')} has no visual target")
        _assert(
            all(str(item).startswith(("source:", "target:")) for item in targets),
            f"{state.get('state_id')} has an untyped visual target",
        )
    return {
        "state_count": len(states),
        "state_ids": state_ids,
        "initial_postconditions": states[0]["postconditions"],
    }


def _image_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _blank_like(path: Path) -> str:
    with Image.open(path) as source:
        blank = Image.new("RGB", source.size, color=(225, 225, 225))
    buffer = io.BytesIO()
    blank.save(buffer, format="JPEG", quality=92)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _post_json(
    client: httpx.Client,
    path: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    response = client.post(path, json=payload)
    elapsed = time.perf_counter() - started
    response.raise_for_status()
    return response.json(), elapsed


def run(args: argparse.Namespace) -> dict[str, Any]:
    for path in (args.manual, args.book_frame, args.pen_frame):
        _assert(path.is_file(), f"missing input: {path}")

    with httpx.Client(base_url=args.base_url, timeout=args.timeout) as client:
        health = client.get("/health")
        health.raise_for_status()
        health_payload = health.json()
        _assert(health_payload.get("status") == "ok", "backend health is not ok")
        _assert(
            health_payload.get("tracking_remote_available") is True,
            "SAM2 tracking service is unavailable",
        )

        started = time.perf_counter()
        response = client.post(
            "/api/manuals?mode=ollama",
            files=[
                (
                    "files",
                    (args.manual.name, args.manual.read_bytes(), "application/pdf"),
                )
            ],
        )
        response.raise_for_status()
        job_id = response.json()["job_id"]
        deadline = time.monotonic() + args.job_timeout
        stages: list[dict[str, Any]] = []
        last_stage: tuple[str, float] | None = None
        while time.monotonic() < deadline:
            job_response = client.get(f"/api/manuals/{job_id}")
            job_response.raise_for_status()
            job = job_response.json()
            marker = (str(job.get("stage")), float(job.get("progress", 0.0)))
            if marker != last_stage:
                stages.append({"stage": marker[0], "progress": marker[1]})
                last_stage = marker
            if job.get("status") == "completed":
                break
            if job.get("status") == "failed":
                raise AssertionError(f"manual job failed: {job.get('error')}")
            time.sleep(args.poll_interval)
        else:
            raise AssertionError("manual parsing job timed out")
        manual_seconds = time.perf_counter() - started
        procedure_id = job["procedure_id"]
        procedure_summary = validate_procedure(job["procedure"])

        common = {
            "procedure_id": procedure_id,
            "image_rotation_degrees": 0,
            "mode": "ollama",
            "save_for_training": False,
            "run_id": "pretraining-acceptance",
        }
        completed, completed_seconds = _post_json(
            client,
            "/api/guidance/verify",
            {
                **common,
                "current_step_id": "S1",
                "history": ["S0"],
                "image_base64": _image_base64(args.book_frame),
                "mock_status": "completed",
            },
        )
        _assert(completed["status"] == "completed", "S1 was not completed")
        _assert(completed["safe_to_advance"] is True, "S1 did not pass the safety gate")
        _assert(completed["matched_step_id"] == "S1", "S1 matched another step")
        _assert(
            any(box["component_id"].startswith("source:") for box in completed["component_boxes_0_1000"]),
            "S1 returned no source box",
        )

        wrong, wrong_seconds = _post_json(
            client,
            "/api/guidance/verify",
            {
                **common,
                "current_step_id": "S2",
                "history": ["S0", "S1"],
                "image_base64": _image_base64(args.pen_frame),
                "mock_status": "wrong_operation",
            },
        )
        _assert(wrong["status"] == "wrong_operation", "S2 did not detect the wrong placement")
        _assert(wrong["safe_to_advance"] is False, "wrong S2 was allowed to advance")
        boxes = wrong["component_boxes_0_1000"]
        source = next((box for box in boxes if box["component_id"].startswith("source:")), None)
        target = next((box for box in boxes if box["component_id"].startswith("target:")), None)
        _assert(source is not None and target is not None, "S2 did not return both arrow endpoints")

        tracking, first_mask_seconds = _post_json(
            client,
            "/api/tracking/sessions",
            {
                "run_id": "pretraining-acceptance",
                "procedure_id": procedure_id,
                "step_id": "S2",
                "image_base64": _image_base64(args.pen_frame),
                "component_id": source["component_id"],
                "bbox_0_1000": source["bbox_0_1000"],
            },
        )
        session_id = tracking["session_id"]
        tracked = tracking["tracked"]
        try:
            _assert(tracked["status"] == "tracking", "SAM2 did not initialize tracking")
            _assert("sam2" in tracked["provider"].lower(), "tracking provider is not SAM2")
            _assert(bool(tracked["overlay_png_base64"]), "SAM2 returned no pixel mask")

            stable, stable_seconds = _post_json(
                client,
                f"/api/tracking/sessions/{session_id}/frames",
                {"image_base64": _image_base64(args.pen_frame)},
            )
            _assert(stable["status"] == "tracking", "same-frame temporal update was lost")

            occluded, occluded_seconds = _post_json(
                client,
                f"/api/tracking/sessions/{session_id}/frames",
                {"image_base64": _blank_like(args.pen_frame)},
            )
            _assert(occluded["status"] == "lost", "full occlusion did not stop tracking")
            _assert(occluded["requires_redetection"] is True, "full occlusion did not request re-detection")
            _assert(float(occluded["quality"]) == 0.0, "full occlusion retained non-zero quality")
        finally:
            client.delete(f"/api/tracking/sessions/{session_id}")

    return {
        "result": "PASS",
        "backend": {
            "model": health_payload.get("model"),
            "tracking_provider": health_payload.get("tracking_provider"),
        },
        "manual": {
            **procedure_summary,
            "seconds": round(manual_seconds, 3),
            "stages": stages,
        },
        "closed_loop": {
            "S1": {
                "status": completed["status"],
                "safe_to_advance": completed["safe_to_advance"],
                "seconds": round(completed_seconds, 3),
            },
            "S2": {
                "status": wrong["status"],
                "safe_to_advance": wrong["safe_to_advance"],
                "arrow_endpoints": [source["component_id"], target["component_id"]],
                "seconds": round(wrong_seconds, 3),
            },
        },
        "segmentation_tracking": {
            "provider": tracked["provider"],
            "first_mask_seconds": round(first_mask_seconds, 3),
            "stable_update_seconds": round(stable_seconds, 3),
            "occlusion_update_seconds": round(occluded_seconds, 3),
            "occlusion_status": occluded["status"],
            "requires_redetection": occluded["requires_redetection"],
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--manual", type=Path, default=DEFAULT_MANUAL)
    parser.add_argument("--book-frame", type=Path, default=DEFAULT_BOOK_FRAME)
    parser.add_argument("--pen-frame", type=Path, default=DEFAULT_PEN_FRAME)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--job-timeout", type=float, default=240.0)
    parser.add_argument("--poll-interval", type=float, default=0.5)
    return parser.parse_args()


if __name__ == "__main__":
    try:
        print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2))
    except Exception as exc:  # acceptance entrypoint must fail loudly and non-zero
        print(
            json.dumps(
                {"result": "FAIL", "error": f"{type(exc).__name__}: {exc}"},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
