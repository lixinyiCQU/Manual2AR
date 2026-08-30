from __future__ import annotations

"""Exercise the before/after checkpoint contract without claiming VLM accuracy."""

import base64
import io
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app


BACKEND_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = (
    BACKEND_ROOT
    / "output"
    / "acceptance"
    / "before_after_checkpoint_acceptance.json"
)


def frame(color: tuple[int, int, int]) -> str:
    image = Image.new("RGB", (120, 90), color=color)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def main() -> None:
    client = TestClient(app)
    created = client.post(
        "/api/manuals?mode=ollama&device_profile=bambu_a1_mini_ams_lite",
        files=[
            (
                "files",
                (
                    "A1_mini_quick_start_zh.pdf",
                    b"%PDF-checkpoint-acceptance",
                    "application/pdf",
                ),
            )
        ],
    )
    created.raise_for_status()
    procedure_id = created.json()["job_id"]
    job = client.get(f"/api/manuals/{procedure_id}")
    job.raise_for_status()
    task_id = job.json()["procedure"]["task"]["task_id"]

    cases = []
    for status in ("completed", "wrong_operation", "uncertain"):
        response = client.post(
            "/api/guidance/verify",
            json={
                "procedure_id": procedure_id,
                "current_step_id": "S1",
                "history": ["S0"],
                "comparison_mode": "before_after",
                "before_image_base64": frame((70, 80, 90)),
                "image_base64": frame((90, 110, 130)),
                "mode": "mock",
                "mock_status": status,
            },
        )
        response.raise_for_status()
        result = response.json()
        expected_advance = status == "completed"
        cases.append(
            {
                "status": status,
                "safe_to_advance": result["safe_to_advance"],
                "expected_safe_to_advance": expected_advance,
                "passed": result["safe_to_advance"] is expected_advance,
            }
        )

    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": "API and deterministic safety-gate acceptance only",
        "does_not_prove": "real A1 mini visual-state accuracy",
        "task_id": task_id,
        "cases": cases,
        "result": "PASS" if all(case["passed"] for case in cases) else "FAIL",
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if payload["result"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
