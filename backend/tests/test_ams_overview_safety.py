from __future__ import annotations

import base64
import io

from PIL import Image

from app.manual_service import ManualService
from app.models import AmsOverviewScanRequest


def _image_base64() -> str:
    buffer = io.BytesIO()
    Image.new("RGB", (160, 120), color=(220, 220, 220)).save(buffer, "JPEG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _slot(slot_id: int, occupied: str, spool_visible: str) -> dict:
    return {
        "slot_id": slot_id,
        "occupied": occupied,
        "spool_visible": spool_visible,
        "feeder_inlet_visible": "yes",
        "filament_inserted": "no",
        "ptfe_filament_visible": "no",
        "confidence": 0.93,
        "evidence": f"direct visible evidence for slot {slot_id}",
    }


def test_overview_never_recommends_an_occupied_slot() -> None:
    service = ManualService()
    service.ollama.chat_structured = lambda **_kwargs: {
        "topology_valid": True,
        "slots": [
            _slot(1, "no", "yes"),
            _slot(2, "yes", "yes"),
            _slot(3, "no", "no"),
            _slot(4, "no", "no"),
        ],
        "suggested_slot_id": 1,
        "suggestion_reason": "model guessed slot 1",
        "requires_user_confirmation": True,
    }

    result = service.scan_ams_overview(
        AmsOverviewScanRequest(
            image_base64=_image_base64(),
            task_type="load_spool",
            mode="ollama",
        )
    )

    assert result.slots[0].occupied == "yes"
    assert result.suggested_slot_id == 3
    assert result.requires_user_confirmation is True


def test_overview_returns_no_suggestion_without_direct_empty_evidence() -> None:
    service = ManualService()
    service.ollama.chat_structured = lambda **_kwargs: {
        "topology_valid": True,
        "slots": [
            _slot(1, "uncertain", "uncertain"),
            _slot(2, "yes", "yes"),
            _slot(3, "uncertain", "no"),
            _slot(4, "no", "uncertain"),
        ],
        "suggested_slot_id": 3,
        "suggestion_reason": "model guessed slot 3",
        "requires_user_confirmation": True,
    }

    result = service.scan_ams_overview(
        AmsOverviewScanRequest(
            image_base64=_image_base64(),
            task_type="load_spool",
            mode="ollama",
        )
    )

    assert result.suggested_slot_id is None
    assert "换角度" in result.suggestion_reason
