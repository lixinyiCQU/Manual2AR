from __future__ import annotations

import json

import cv2
import numpy as np

from scripts.render_guidance_replay import render_replay


def test_replay_renders_pixel_masks_and_source_target_arrow(tmp_path) -> None:
    image = np.full((600, 800, 3), 235, dtype=np.uint8)
    cv2.rectangle(image, (280, 120), (680, 520), (150, 150, 150), -1)
    cv2.rectangle(image, (80, 300), (250, 330), (200, 180, 20), -1)
    image_path = tmp_path / "scene.jpg"
    assert cv2.imwrite(str(image_path), image)
    metadata = {
        "image_path": image_path.name,
        "request_context": {"current_step_id": "S2"},
        "procedure": {
            "states": [
                {
                    "state_id": "S2",
                    "instruction": "Move the blue pen onto the book.",
                    "target_components": ["source:blue pen", "target:book"],
                }
            ]
        },
        "model_result": {
            "status": "in_progress",
            "component_boxes_0_1000": [
                {
                    "component_id": "source:blue pen",
                    "bbox_0_1000": [90, 470, 330, 580],
                },
                {
                    "component_id": "target:book",
                    "bbox_0_1000": [350, 180, 860, 880],
                },
            ],
        },
    }
    metadata_path = tmp_path / "capture.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    output_path = tmp_path / "replay.png"

    report = render_replay(metadata_path, output_path)

    assert output_path.exists()
    assert output_path.with_suffix(".json").exists()
    assert report["arrow_drawn"] is True
    assert len(report["components"]) == 2
    assert all(item["mask_pixel_count"] > 0 for item in report["components"])
    assert report["components"][0]["provider"] == "opencv-grabcut-lk-baseline"

