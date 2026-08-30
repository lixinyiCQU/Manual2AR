from __future__ import annotations

import cv2
import numpy as np

from app.grounding import DemoGrounder
from app.tracking import OpenCvMaskTracker


def _split_pen_image() -> bytes:
    image = np.full((420, 640, 3), 235, dtype=np.uint8)
    cv2.rectangle(image, (120, 190), (245, 220), (180, 220, 20), -1)
    cv2.rectangle(image, (275, 188), (390, 222), (180, 220, 20), -1)
    success, encoded = cv2.imencode(".jpg", image)
    assert success
    return encoded.tobytes()


def test_grounder_combines_collinear_colored_pen_parts() -> None:
    boxes = DemoGrounder().ground(
        _split_pen_image(),
        ["source:blue pen"],
    )
    assert len(boxes) == 1
    box = boxes[0].bbox_0_1000
    assert box[0] <= 200
    assert box[2] >= 600


def test_opencv_pen_mask_keeps_both_collinear_parts() -> None:
    tracker = OpenCvMaskTracker()
    session_id, tracked = tracker.start(
        _split_pen_image(),
        "source:blue pen",
        [150, 400, 650, 600],
    )
    try:
        assert tracked.bbox_0_1000[0] <= 200
        assert tracked.bbox_0_1000[2] >= 600
    finally:
        tracker.close(session_id)


def test_occluded_pen_does_not_jump_to_small_colored_distractor() -> None:
    initial_bytes = _split_pen_image()
    initial = cv2.imdecode(
        np.frombuffer(initial_bytes, dtype=np.uint8),
        cv2.IMREAD_COLOR,
    )
    occluded = initial.copy()
    occluded[160:250, 80:430] = (235, 235, 235)
    cv2.rectangle(occluded, (500, 60), (512, 68), (180, 220, 20), -1)
    success, encoded = cv2.imencode(".jpg", occluded)
    assert success

    tracker = OpenCvMaskTracker()
    session_id, _ = tracker.start(
        initial_bytes,
        "source:blue pen",
        [150, 400, 650, 600],
    )
    try:
        tracked = tracker.update(session_id, encoded.tobytes())
        assert tracked.status == "lost"
        assert tracked.requires_redetection is True
    finally:
        tracker.close(session_id)
