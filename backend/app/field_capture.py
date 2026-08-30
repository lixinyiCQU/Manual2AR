from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ALLOWED_PHASES = {"raw", "before", "after", "overlay", "verification", "error"}
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
}
MAX_IMAGE_BYTES = 20 * 1024 * 1024


def capture_root() -> Path:
    configured = os.getenv("MANUAL2AR_FIELD_CAPTURE_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "data" / "field_captures"


def save_field_capture(
    *,
    case_id: str,
    phase: str,
    image_bytes: bytes,
    content_type: str,
    labels: dict[str, Any],
) -> dict[str, Any]:
    if not CASE_ID_PATTERN.fullmatch(case_id):
        raise ValueError("case_id 只能包含字母、数字、下划线和短横线")
    if phase not in ALLOWED_PHASES:
        raise ValueError(
            "phase 必须是 raw、before、after、overlay、verification 或 error"
        )
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise ValueError("只接受 JPEG 或 PNG 图片")
    if not image_bytes:
        raise ValueError("图片为空")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError("图片超过 20 MB")

    case_dir = capture_root() / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    revision = 1
    extension = ALLOWED_IMAGE_TYPES[content_type]
    while (case_dir / f"{phase}_{revision:03d}{extension}").exists():
        revision += 1

    image_name = f"{phase}_{revision:03d}{extension}"
    image_path = case_dir / image_name
    image_path.write_bytes(image_bytes)
    captured_at = datetime.now(timezone.utc).isoformat()
    capture_id = f"{case_id}_{phase}_{revision:03d}"
    metadata = {
        "capture_id": capture_id,
        "case_id": case_id,
        "phase": phase,
        "revision": revision,
        "captured_at_utc": captured_at,
        "image_file": image_name,
        "content_type": content_type,
        "bytes": len(image_bytes),
        "sha256": hashlib.sha256(image_bytes).hexdigest(),
        "consent": True,
        "labels": labels,
        "paper_evidence": labels.get("paper_evidence", {}),
    }
    metadata_path = case_dir / f"{phase}_{revision:03d}.json"
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    before_exists = any(case_dir.glob("before_*.json"))
    after_exists = any(case_dir.glob("after_*.json"))
    return {
        "capture_id": capture_id,
        "case_id": case_id,
        "phase": phase,
        "revision": revision,
        "image_path": str(image_path),
        "metadata_path": str(metadata_path),
        "pair_complete": before_exists and after_exists,
    }
