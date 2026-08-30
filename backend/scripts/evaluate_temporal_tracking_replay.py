#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tracking import OpenCvMaskTracker
from app.tracking_provider import MaskTracker, RemoteSam2Tracker


def _mask_from_overlay(value: str, shape: tuple[int, int]) -> np.ndarray:
    if not value:
        return np.zeros(shape, dtype=np.uint8)
    overlay = cv2.imdecode(
        np.frombuffer(base64.b64decode(value), dtype=np.uint8),
        cv2.IMREAD_UNCHANGED,
    )
    if overlay is None or overlay.ndim != 3 or overlay.shape[2] != 4:
        return np.zeros(shape, dtype=np.uint8)
    return np.where(overlay[:, :, 3] > 0, 255, 0).astype(np.uint8)


def _iou(left: np.ndarray, right: np.ndarray) -> float:
    intersection = np.count_nonzero((left > 0) & (right > 0))
    union = np.count_nonzero((left > 0) | (right > 0))
    return intersection / union if union else 0.0


def _centroid(mask: np.ndarray) -> tuple[float, float] | None:
    moments = cv2.moments(mask)
    if not moments["m00"]:
        return None
    return (
        moments["m10"] / moments["m00"],
        moments["m01"] / moments["m00"],
    )


def _centroid_error(left: np.ndarray, right: np.ndarray) -> float | None:
    left_center = _centroid(left)
    right_center = _centroid(right)
    if left_center is None or right_center is None:
        return None
    return float(
        np.hypot(
            left_center[0] - right_center[0],
            left_center[1] - right_center[1],
        )
    )


def _affine(
    width: int,
    height: int,
    translate_x: float,
    translate_y: float,
    rotation_degrees: float,
    scale: float,
) -> np.ndarray:
    matrix = cv2.getRotationMatrix2D(
        (width / 2.0, height / 2.0),
        rotation_degrees,
        scale,
    )
    matrix[0, 2] += translate_x
    matrix[1, 2] += translate_y
    return matrix


def _draw_comparison(
    image: np.ndarray,
    expected: np.ndarray,
    predicted: np.ndarray,
    label: str,
) -> np.ndarray:
    rendered = image.copy()
    expected_contours, _ = cv2.findContours(
        expected,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    predicted_contours, _ = cv2.findContours(
        predicted,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    cv2.drawContours(rendered, expected_contours, -1, (255, 0, 220), 4)
    cv2.drawContours(rendered, predicted_contours, -1, (0, 255, 255), 3)
    cv2.rectangle(rendered, (12, 12), (440, 58), (15, 39, 70), -1)
    cv2.putText(
        rendered,
        label,
        (26, 45),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.72,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return rendered


def evaluate_sequence(
    image_bytes: bytes,
    component_id: str,
    bbox_0_1000: list[int],
    tracker: MaskTracker,
    output_path: Path,
) -> dict[str, Any]:
    original = cv2.imdecode(
        np.frombuffer(image_bytes, dtype=np.uint8),
        cv2.IMREAD_COLOR,
    )
    if original is None:
        raise ValueError("Could not decode replay image")
    height, width = original.shape[:2]
    session_id, initial = tracker.start(image_bytes, component_id, bbox_0_1000)
    try:
        expected_mask = _mask_from_overlay(initial.overlay_png_base64, (height, width))
        previous_image = original
        transforms = [
            (14.0, -8.0, 0.0, 1.0),
            (0.0, 0.0, 2.0, 1.0),
            (7.0, 5.0, -1.0, 1.015),
            (-12.0, 10.0, 1.0, 0.99),
        ]
        frames: list[np.ndarray] = [
            _draw_comparison(
                original,
                expected_mask,
                expected_mask,
                "initial | expected=magenta predicted=yellow",
            )
        ]
        rows: list[dict[str, Any]] = []
        for index, transform in enumerate(transforms, start=1):
            matrix = _affine(width, height, *transform)
            next_image = cv2.warpAffine(
                previous_image,
                matrix,
                (width, height),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REFLECT,
            )
            expected_mask = cv2.warpAffine(
                expected_mask,
                matrix,
                (width, height),
                flags=cv2.INTER_NEAREST,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=0,
            )
            success, encoded = cv2.imencode(".jpg", next_image, [cv2.IMWRITE_JPEG_QUALITY, 90])
            if not success:
                raise RuntimeError("Could not encode replay frame")
            tracked = tracker.update(session_id, encoded.tobytes())
            predicted = _mask_from_overlay(
                tracked.overlay_png_base64,
                (height, width),
            )
            frame_iou = _iou(expected_mask, predicted)
            error = _centroid_error(expected_mask, predicted)
            rows.append(
                {
                    "frame_index": index,
                    "transform": {
                        "translate_x": transform[0],
                        "translate_y": transform[1],
                        "rotation_degrees": transform[2],
                        "scale": transform[3],
                    },
                    "status": tracked.status,
                    "quality": tracked.quality,
                    "iou": round(frame_iou, 4),
                    "centroid_error_pixels": round(error, 3) if error is not None else None,
                    "requires_redetection": tracked.requires_redetection,
                }
            )
            frames.append(
                _draw_comparison(
                    next_image,
                    expected_mask,
                    predicted,
                    f"frame {index} | IoU={frame_iou:.3f} q={tracked.quality:.3f}",
                )
            )
            previous_image = next_image

        mean_iou = float(np.mean([row["iou"] for row in rows]))
        valid_errors = [
            float(row["centroid_error_pixels"])
            for row in rows
            if row["centroid_error_pixels"] is not None
        ]
        report = {
            "provider": initial.provider,
            "component_id": component_id,
            "frames": rows,
            "mean_iou": round(mean_iou, 4),
            "minimum_iou": round(min(row["iou"] for row in rows), 4),
            "mean_centroid_error_pixels": (
                round(float(np.mean(valid_errors)), 3) if valid_errors else None
            ),
            "lost_frames": sum(row["status"] == "lost" for row in rows),
            "redetection_requests": sum(row["requires_redetection"] for row in rows),
            "synthetic_motion_gate_passed": bool(
                mean_iou >= 0.75
                and all(row["status"] == "tracking" for row in rows)
            ),
        }

        panel_width = 480
        thumbnails: list[np.ndarray] = []
        for frame in frames:
            ratio = panel_width / frame.shape[1]
            thumbnails.append(
                cv2.resize(
                    frame,
                    (panel_width, round(frame.shape[0] * ratio)),
                    interpolation=cv2.INTER_AREA,
                )
            )
        columns = 2
        rows_of_frames: list[np.ndarray] = []
        blank = np.zeros_like(thumbnails[0])
        for start in range(0, len(thumbnails), columns):
            row = thumbnails[start : start + columns]
            while len(row) < columns:
                row.append(blank)
            rows_of_frames.append(np.hstack(row))
        contact_sheet = np.vstack(rows_of_frames)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(output_path), contact_sheet):
            raise OSError(f"Could not write {output_path}")
        output_path.with_suffix(".json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return report
    finally:
        tracker.close(session_id)


def _source_box(metadata: dict[str, Any]) -> tuple[str, list[int]]:
    boxes = metadata.get("model_result", {}).get("component_boxes_0_1000") or []
    for box in boxes:
        if not str(box.get("component_id", "")).lower().startswith("target:"):
            return str(box["component_id"]), [int(value) for value in box["bbox_0_1000"]]
    raise ValueError("Capture has no source component box")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate mask propagation under known synthetic camera motion.",
    )
    parser.add_argument("metadata", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--sam2-url", default="http://127.0.0.1:8020")
    parser.add_argument("--opencv", action="store_true")
    args = parser.parse_args()
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    image_path = args.metadata.parent / metadata["image_path"]
    component_id, box = _source_box(metadata)
    tracker: MaskTracker = (
        OpenCvMaskTracker()
        if args.opencv
        else RemoteSam2Tracker(args.sam2_url, timeout_seconds=90.0)
    )
    report = evaluate_sequence(
        image_path.read_bytes(),
        component_id,
        box,
        tracker,
        args.output,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

