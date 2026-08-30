from __future__ import annotations

import json

from app.models import TrackedComponent, TrackingSessionRequest
from app.tracking_events import TrackingEventLogger


def _tracked(status: str = "tracking") -> TrackedComponent:
    return TrackedComponent(
        component_id="source:蓝色笔",
        status=status,
        quality=0.82 if status == "tracking" else 0.1,
        bbox_0_1000=[100, 200, 300, 400],
        polygon_0_1000=[[100, 200], [300, 200], [300, 400]],
        centroid_0_1000=[200, 300],
        provider="opencv-grabcut-lk-baseline",
        requires_redetection=status == "lost",
    )


def test_tracking_telemetry_is_image_free_and_keeps_step_context(tmp_path) -> None:
    logger = TrackingEventLogger(tmp_path)
    request = TrackingSessionRequest(
        image_base64="never-written",
        component_id="source:蓝色笔",
        bbox_0_1000=[100, 200, 300, 400],
        procedure_id="procedure-1",
        step_id="S2",
    )
    logger.started("public-session", request, _tracked())
    logger.updated("public-session", _tracked("lost"))
    logger.closed("public-session")

    paths = list(tmp_path.glob("*.jsonl"))
    assert len(paths) == 1
    rows = [json.loads(line) for line in paths[0].read_text().splitlines()]
    assert [row["event"] for row in rows] == ["started", "updated", "closed"]
    assert all(row["procedure_id"] == "procedure-1" for row in rows)
    assert all(row["step_id"] == "S2" for row in rows)
    assert rows[1]["requires_redetection"] is True
    assert "image_base64" not in paths[0].read_text()
    assert not list(tmp_path.glob("*.jpg"))
