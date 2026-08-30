#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import sys
import textwrap
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.grounding import DemoGrounder
from app.tracking import OpenCvMaskTracker
from app.tracking_provider import MaskTracker, RemoteSam2Tracker


FONT_PATHS = (
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
)


def _state_for(metadata: dict[str, Any]) -> dict[str, Any] | None:
    result = metadata.get("model_result", {})
    request = metadata.get("request_context", {})
    state_id = request.get("current_step_id") or result.get("recommended_step_id")
    for state in metadata.get("procedure", {}).get("states", []):
        if state.get("state_id") == state_id:
            return state
    return None


def _normalized_center(box: list[int]) -> tuple[int, int]:
    return ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)


def _pixel_point(point: tuple[int, int], width: int, height: int) -> tuple[int, int]:
    return (round(point[0] / 1000 * width), round(point[1] / 1000 * height))


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for font_path in FONT_PATHS:
        if font_path.is_file():
            return ImageFont.truetype(str(font_path), size=size)
    return ImageFont.load_default()


def _draw_text_panel(
    image_bgr: np.ndarray,
    title: str,
    subtitle: str,
) -> np.ndarray:
    image = Image.fromarray(cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(image, "RGBA")
    width, height = image.size
    panel_height = max(112, round(height * 0.17))
    draw.rounded_rectangle(
        (18, 18, width - 18, panel_height),
        radius=18,
        fill=(15, 39, 70, 225),
        outline=(76, 176, 242, 255),
        width=3,
    )
    title_font = _load_font(max(22, round(height * 0.035)))
    subtitle_font = _load_font(max(16, round(height * 0.024)))
    title_lines = textwrap.wrap(title or "当前步骤", width=max(18, width // 30))[:2]
    draw.multiline_text(
        (38, 30),
        "\n".join(title_lines),
        font=title_font,
        fill=(255, 255, 255, 255),
        spacing=5,
    )
    draw.text(
        (38, panel_height - 34),
        subtitle,
        font=subtitle_font,
        fill=(181, 220, 246, 255),
    )
    return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)


def render_replay(
    metadata_path: Path,
    output_path: Path,
    tracker: MaskTracker | None = None,
    reground: bool = False,
) -> dict[str, Any]:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    image_path = metadata_path.parent / metadata["image_path"]
    image_bytes = image_path.read_bytes()
    image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Could not decode {image_path}")

    result = metadata.get("model_result", {})
    state = _state_for(metadata)
    boxes = [] if reground else list(result.get("component_boxes_0_1000") or [])
    if not boxes and state:
        boxes = [
            box.model_dump()
            for box in DemoGrounder().ground(
                image_bytes,
                list(state.get("target_components") or []),
            )
        ]

    tracker = tracker or OpenCvMaskTracker()
    height, width = image.shape[:2]
    rendered = image.copy()
    components: list[dict[str, Any]] = []
    source_center: tuple[int, int] | None = None
    target_center: tuple[int, int] | None = None

    for box in boxes:
        component_id = str(box["component_id"])
        prompt_box = [int(value) for value in box["bbox_0_1000"]]
        session_id, tracked = tracker.start(image_bytes, component_id, prompt_box)
        tracker.close(session_id)
        overlay = None
        if tracked.overlay_png_base64:
            overlay = cv2.imdecode(
                np.frombuffer(
                    base64.b64decode(tracked.overlay_png_base64),
                    dtype=np.uint8,
                ),
                cv2.IMREAD_UNCHANGED,
            )
        mask = (
            overlay[:, :, 3] > 0
            if overlay is not None and overlay.ndim == 3 and overlay.shape[2] == 4
            else np.zeros((height, width), dtype=bool)
        )
        is_target = component_id.lower().startswith("target:")
        color = np.array([80, 205, 95] if is_target else [15, 150, 255], dtype=np.float32)
        rendered[mask] = np.clip(
            rendered[mask].astype(np.float32) * 0.42 + color * 0.58,
            0,
            255,
        ).astype(np.uint8)
        if np.any(mask):
            contours, _ = cv2.findContours(
                mask.astype(np.uint8) * 255,
                cv2.RETR_EXTERNAL,
                cv2.CHAIN_APPROX_SIMPLE,
            )
            cv2.drawContours(rendered, contours, -1, color.tolist(), 4)

        center = _pixel_point(
            (tracked.centroid_0_1000[0], tracked.centroid_0_1000[1]),
            width,
            height,
        )
        if is_target:
            target_center = center
        elif source_center is None:
            source_center = center

        prompt_area = max(
            1,
            (prompt_box[2] - prompt_box[0]) * (prompt_box[3] - prompt_box[1]),
        )
        tracked_box = tracked.bbox_0_1000
        tracked_area = max(
            1,
            (tracked_box[2] - tracked_box[0]) * (tracked_box[3] - tracked_box[1]),
        )
        prompt_pixel_width = max(
            1,
            round((prompt_box[2] - prompt_box[0]) / 1000 * width),
        )
        prompt_pixel_height = max(
            1,
            round((prompt_box[3] - prompt_box[1]) / 1000 * height),
        )
        prompt_pixel_area = prompt_pixel_width * prompt_pixel_height
        mask_fill_ratio = int(np.count_nonzero(mask)) / prompt_pixel_area
        components.append(
            {
                "component_id": component_id,
                "prompt_bbox_0_1000": prompt_box,
                "mask_bbox_0_1000": tracked_box,
                "centroid_0_1000": tracked.centroid_0_1000,
                "mask_pixel_count": int(np.count_nonzero(mask)),
                "mask_to_prompt_box_area_ratio": round(tracked_area / prompt_area, 4),
                "mask_to_prompt_pixel_area_ratio": round(mask_fill_ratio, 4),
                "rectangle_fallback_like": mask_fill_ratio >= 0.92,
                "provider": tracked.provider,
                "status": tracked.status,
                "quality": tracked.quality,
            }
        )

    arrow_drawn = source_center is not None and target_center is not None
    if arrow_drawn:
        cv2.arrowedLine(
            rendered,
            source_center,
            target_center,
            (255, 246, 80),
            max(5, round(min(width, height) * 0.009)),
            cv2.LINE_AA,
            tipLength=0.16,
        )

    instruction = state.get("instruction", "当前步骤") if state else "当前步骤"
    status = str(result.get("status") or "定位当前状态")
    provider = components[0]["provider"] if components else "no-mask"
    rendered = _draw_text_panel(
        rendered,
        instruction,
        f"状态：{status} · 分割：{provider}",
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), rendered):
        raise OSError(f"Could not write {output_path}")
    report = {
        "source_metadata": str(metadata_path),
        "source_image": str(image_path),
        "output_image": str(output_path),
        "state_id": state.get("state_id") if state else None,
        "instruction": instruction,
        "model_status": result.get("status"),
        "arrow_drawn": arrow_drawn,
        "components": components,
    }
    report_path = output_path.with_suffix(".json")
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render actual Manual2AR mask and arrow on a saved capture.",
    )
    parser.add_argument("metadata", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--sam2-url",
        help="Use a running remote SAM2 provider instead of the OpenCV fallback.",
    )
    parser.add_argument(
        "--reground",
        action="store_true",
        help="Ignore saved boxes and rerun the current deterministic grounder.",
    )
    args = parser.parse_args()
    tracker = (
        RemoteSam2Tracker(args.sam2_url, timeout_seconds=90.0)
        if args.sam2_url
        else None
    )
    report = render_replay(
        args.metadata,
        args.output,
        tracker=tracker,
        reground=args.reground,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
