#!/usr/bin/env python3
"""Exercise the A1 mini profile through the same public API used by Unity.

The official page-12 drawing is deliberately an offline wiring sanity check,
not evidence of real-camera accuracy. Physical success rates come from the lab
protocol and human labels.
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


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANUAL = (
    ROOT / "examples/bambu_a1_mini_v1/manual/A1_mini_quick_start_zh.pdf"
)
DEFAULT_FRAME = (
    ROOT / "examples/bambu_a1_mini_v1/references/page_12_external_spool.png"
)
DEFAULT_OUTPUT = (
    ROOT / "backend/output/acceptance/a1_mini_offline_acceptance.json"
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def post_json(
    client: httpx.Client,
    path: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    response = client.post(path, json=payload)
    seconds = time.perf_counter() - started
    response.raise_for_status()
    return response.json(), seconds


def run(args: argparse.Namespace) -> dict[str, Any]:
    require(args.manual.is_file(), f"missing manual: {args.manual}")
    require(args.frame.is_file(), f"missing frame: {args.frame}")
    image = base64.b64encode(args.frame.read_bytes()).decode("ascii")

    with httpx.Client(base_url=args.base_url, timeout=args.timeout) as client:
        health = client.get("/health")
        health.raise_for_status()
        health_payload = health.json()
        require(health_payload["tracking_remote_available"], "SAM2 unavailable")

        started = time.perf_counter()
        upload = client.post(
            "/api/manuals?mode=ollama&device_profile=bambu_a1_mini",
            files=[
                (
                    "files",
                    (args.manual.name, args.manual.read_bytes(), "application/pdf"),
                )
            ],
        )
        upload.raise_for_status()
        job_id = upload.json()["job_id"]
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            job = client.get(f"/api/manuals/{job_id}").json()
            if job["status"] == "completed":
                break
            if job["status"] == "failed":
                raise AssertionError(job["error"])
            time.sleep(0.1)
        else:
            raise AssertionError("profile loading timed out")
        profile_seconds = time.perf_counter() - started
        procedure = job["procedure"]
        require(procedure["device"]["device_id"] == "bambu_a1_mini", "wrong device")
        require(len(procedure["states"]) == 7, "expected seven audited states")

        common = {
            "procedure_id": job_id,
            "image_base64": image,
            "image_rotation_degrees": 0,
            "mode": "ollama",
            "run_id": "a1-mini-offline-acceptance",
        }
        localized, locate_seconds = post_json(
            client,
            "/api/guidance/locate",
            common,
        )
        require(localized["recommended_step_id"] == "S6", "full path not localized")
        require(localized["completed_step_ids"] == ["S0", "S1", "S2", "S3", "S4", "S5"], "non-contiguous progress")

        verified, verify_seconds = post_json(
            client,
            "/api/guidance/verify",
            {
                **common,
                "current_step_id": "S3",
                "history": ["S0", "S1", "S2"],
                "save_for_training": False,
            },
        )
        require(verified["status"] == "completed", "S3 not completed")
        require(verified["safe_to_advance"] is True, "S3 safety gate failed")
        boxes = verified["component_boxes_0_1000"]
        source = next(
            (box for box in boxes if box["component_id"] == "source:最短PTFE管"),
            None,
        )
        target = next(
            (box for box in boxes if box["component_id"] == "target:工具头进料口"),
            None,
        )
        require(source is not None and target is not None, "missing arrow endpoints")

        tracking, mask_seconds = post_json(
            client,
            "/api/tracking/sessions",
            {
                "run_id": common["run_id"],
                "procedure_id": job_id,
                "step_id": "S3",
                "image_base64": image,
                "component_id": source["component_id"],
                "bbox_0_1000": source["bbox_0_1000"],
            },
        )
        tracked = tracking["tracked"]
        try:
            require(tracked["status"] == "tracking", "tracking did not start")
            require("sam2" in tracked["provider"].lower(), "SAM2 not selected")
            require(bool(tracked["overlay_png_base64"]), "pixel mask missing")
        finally:
            client.delete(f"/api/tracking/sessions/{tracking['session_id']}")

    return {
        "result": "PASS",
        "scope": "official-manual drawing offline wiring check; not real-camera accuracy",
        "backend": {
            "model": health_payload["model"],
            "tracking_provider": health_payload["tracking_provider"],
        },
        "profile": {
            "device": procedure["device"]["name"],
            "state_count": len(procedure["states"]),
            "load_seconds": round(profile_seconds, 3),
        },
        "localization": {
            "recommended_step_id": localized["recommended_step_id"],
            "completed_step_ids": localized["completed_step_ids"],
            "confidence": localized["confidence"],
            "seconds": round(locate_seconds, 3),
        },
        "verification": {
            "step_id": "S3",
            "status": verified["status"],
            "safe_to_advance": verified["safe_to_advance"],
            "box_ids": [box["component_id"] for box in boxes],
            "seconds": round(verify_seconds, 3),
        },
        "segmentation": {
            "provider": tracked["provider"],
            "quality": tracked["quality"],
            "polygon_points": len(tracked["polygon_0_1000"]),
            "seconds": round(mask_seconds, 3),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--manual", type=Path, default=DEFAULT_MANUAL)
    parser.add_argument("--frame", type=Path, default=DEFAULT_FRAME)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=float, default=180.0)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        result = run(args)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(
            json.dumps(
                {"result": "FAIL", "error": f"{type(exc).__name__}: {exc}"},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
