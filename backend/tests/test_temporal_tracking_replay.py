from __future__ import annotations

import cv2
import numpy as np

from app.tracking import OpenCvMaskTracker
from scripts.evaluate_temporal_tracking_replay import evaluate_sequence


def test_known_motion_replay_produces_metrics_and_artifact(tmp_path) -> None:
    image = np.full((420, 640, 3), 230, dtype=np.uint8)
    for x in range(80, 250, 20):
        cv2.circle(image, (x, 210), 6, (20, 20, 20), -1)
    cv2.rectangle(image, (70, 190), (270, 230), (200, 180, 20), -1)
    success, encoded = cv2.imencode(".jpg", image)
    assert success
    output = tmp_path / "tracking.png"

    report = evaluate_sequence(
        encoded.tobytes(),
        "source:blue pen",
        [90, 420, 450, 600],
        OpenCvMaskTracker(),
        output,
    )

    assert output.exists()
    assert output.with_suffix(".json").exists()
    assert len(report["frames"]) == 4
    assert report["provider"] == "opencv-grabcut-lk-baseline"
    assert 0.0 <= report["mean_iou"] <= 1.0
    assert report["mean_centroid_error_pixels"] is not None

