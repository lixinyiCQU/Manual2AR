#!/usr/bin/env python3
"""Create a paper-ready empty AMS Lite spool-spindle overlay from one photo.

This intentionally calls only the narrow Qwen Flash -> SAM2 endpoint.  It does
not start a task, recommend a slot, or advance any procedure state.

Example:
  python scripts/locate_empty_spool_axle.py /absolute/path/photo.jpg
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def post_json(url: str, payload: dict[str, object]) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=210) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Cannot reach backend: {exc}") from exc


def write_overlay(source: bytes, overlay_base64: str, output_path: Path) -> bool:
    if not overlay_base64:
        return False
    if overlay_base64.startswith("data:"):
        overlay_base64 = overlay_base64.split(",", 1)[-1]
    base = Image.open(BytesIO(source)).convert("RGBA")
    overlay = Image.open(BytesIO(base64.b64decode(overlay_base64))).convert("RGBA")
    if overlay.size != base.size:
        overlay = overlay.resize(base.size, Image.Resampling.LANCZOS)
    Image.alpha_composite(base, overlay).convert("RGB").save(output_path, quality=95)
    return True


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    """Return a readable macOS font, with a Pillow fallback for portability."""
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
        if bold
        else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _rounded_panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    draw.rounded_rectangle(box, radius=20, fill=(7, 25, 45, 220), outline=(44, 216, 235, 220), width=2)


def _arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    color: tuple[int, int, int, int],
    width: int,
) -> None:
    """Draw a vector arrow whose head lands on the segmented operation target."""
    draw.line([start, end], fill=color, width=width)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    head_length = width * 2.4
    head_angle = math.radians(28)
    left = (
        end[0] - head_length * math.cos(angle - head_angle),
        end[1] - head_length * math.sin(angle - head_angle),
    )
    right = (
        end[0] - head_length * math.cos(angle + head_angle),
        end[1] - head_length * math.sin(angle + head_angle),
    )
    draw.polygon([end, left, right], fill=color)


def write_paper_guidance(
    source: bytes,
    overlay_base64: str,
    bbox_0_1000: list[object],
    slot_id: int,
    output_path: Path,
) -> bool:
    """Keep the real SAM2 overlay, then add presentation-only English guidance.

    The cyan visible-surface mask is supplied by the backend.  Labels and the
    arrow are deliberately rendered here as a separate, reproducible paper
    layout layer instead of being treated as model segmentation output.
    """
    if not overlay_base64 or len(bbox_0_1000) != 4:
        return False
    if overlay_base64.startswith("data:"):
        overlay_base64 = overlay_base64.split(",", 1)[-1]
    try:
        normalized_box = [int(value) for value in bbox_0_1000]
    except (TypeError, ValueError):
        return False
    if not all(0 <= value <= 1000 for value in normalized_box):
        return False

    base = Image.open(BytesIO(source)).convert("RGBA")
    overlay = Image.open(BytesIO(base64.b64decode(overlay_base64))).convert("RGBA")
    if overlay.size != base.size:
        overlay = overlay.resize(base.size, Image.Resampling.LANCZOS)
    canvas = Image.alpha_composite(base, overlay)
    draw = ImageDraw.Draw(canvas, "RGBA")
    width, height = canvas.size
    x1, y1, x2, y2 = (
        round(width * normalized_box[0] / 1000),
        round(height * normalized_box[1] / 1000),
        round(width * normalized_box[2] / 1000),
        round(height * normalized_box[3] / 1000),
    )

    # Keep instruction text away from the target and centered in the lower safe area.
    panel_width = min(width - 48, max(520, round(width * 0.78)))
    panel_left = round((width - panel_width) / 2)
    panel_right = panel_left + panel_width
    panel_bottom = height - 30
    panel_top = max(24, panel_bottom - 168)
    _rounded_panel(draw, (panel_left, panel_top, panel_right, panel_bottom))
    title_font = _font(max(22, round(width * 0.031)), bold=True)
    action_font = _font(max(19, round(width * 0.026)))
    def centered(text: str, y: int, font: ImageFont.ImageFont, color: tuple[int, int, int, int]) -> None:
        text_box = draw.textbbox((0, 0), text, font=font)
        text_width = text_box[2] - text_box[0]
        draw.text(((width - text_width) / 2, y), text, font=font, fill=color)

    centered(f"SLOT {slot_id}  ·  TARGET LOCKED", panel_top + 17, title_font, (55, 228, 240, 255))
    centered("Empty spool holder", panel_top + 63, action_font, (55, 228, 240, 255))
    centered("Mount filament spool from right to left", panel_top + 104, action_font, (255, 255, 255, 255))

    # Right-to-left arrow: the tip lands inside the verified SAM2 seed region.
    end = (max(16, min(width - 16, x1 + max(18, (x2 - x1) * 0.38))), y1 + (y2 - y1) * 0.52)
    start = (min(width - 28, max(x2 + 105, end[0] + 220)), end[1] - 24)
    _arrow(draw, start, end, color=(46, 224, 238, 255), width=max(8, round(width * 0.010)))
    radius = max(10, round(width * 0.014))
    draw.ellipse(
        (end[0] - radius, end[1] - radius, end[0] + radius, end[1] + radius),
        fill=(46, 224, 238, 235),
        outline=(255, 255, 255, 255),
        width=2,
    )
    canvas.convert("RGB").save(output_path, quality=95)
    return True


def parse_seed_box(raw: str) -> list[int]:
    try:
        values = [int(value.strip()) for value in raw.split(",")]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Seed box must be x1,y1,x2,y2 in 0-1000 coordinates") from exc
    if len(values) != 4 or not all(0 <= value <= 1000 for value in values):
        raise argparse.ArgumentTypeError("Seed box must have four values in 0-1000")
    if values[0] >= values[2] or values[1] >= values[3]:
        raise argparse.ArgumentTypeError("Seed box requires x1<x2 and y1<y2")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Qwen Flash + SAM2 empty AMS Lite spool-spindle overlay"
    )
    parser.add_argument("image", type=Path, help="Input AMS Lite JPEG or PNG")
    parser.add_argument("--slot", type=int, choices=(1, 2, 3, 4))
    parser.add_argument(
        "--seed-bbox",
        type=parse_seed_box,
        help=(
            "Human-verified target box in normalized x1,y1,x2,y2 coordinates. "
            "Use this to test SAM2 visible-surface segmentation without relying "
            "on VLM pixel localisation."
        ),
    )
    parser.add_argument("--url", default="http://127.0.0.1:8010")
    parser.add_argument("--output-dir", type=Path, default=Path("output/empty_spindle"))
    args = parser.parse_args()

    image_path = args.image.expanduser().resolve()
    if not image_path.is_file():
        raise SystemExit(f"Input image not found: {image_path}")
    source = image_path.read_bytes()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir.expanduser().resolve() / f"{image_path.stem}_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    payload: dict[str, object] = {
        "image_base64": base64.b64encode(source).decode("ascii"),
        "preferred_slot_id": args.slot,
    }
    if args.seed_bbox is not None:
        if args.slot is None:
            raise SystemExit("--seed-bbox also requires --slot")
        payload["verified_seed_bbox_0_1000"] = args.seed_bbox

    result = post_json(
        f"{args.url.rstrip('/')}/api/ams-lite/empty-spool-axle/locate",
        payload,
    )
    raw_path = output_dir / f"{image_path.stem}_raw{image_path.suffix.lower()}"
    raw_path.write_bytes(source)
    result_path = output_dir / "result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    tracked = result.get("tracked") or {}
    overlay_path = output_dir / f"{image_path.stem}_cyan_overlay.jpg"
    overlay_written = write_overlay(
        source,
        str(tracked.get("overlay_png_base64", "")),
        overlay_path,
    )
    candidate = result.get("candidate") or {}
    paper_guidance_path = output_dir / f"{image_path.stem}_paper_guidance.jpg"
    paper_guidance_written = write_paper_guidance(
        source,
        str(tracked.get("overlay_png_base64", "")),
        list(candidate.get("bbox_0_1000") or []),
        int(candidate.get("slot_id") or args.slot or 0),
        paper_guidance_path,
    )
    summary = {
        "found": result.get("found"),
        "slot_id": candidate.get("slot_id"),
        "proposal_source": candidate.get("proposal_source"),
        "model": result.get("model"),
        "provider": result.get("provider"),
        "tracking_ready": result.get("tracking_ready"),
        "tracking_provider": tracked.get("provider"),
        "mask_quality_passed": tracked.get("mask_quality_passed"),
        "quality": tracked.get("quality"),
        "mask_area_ratio": tracked.get("mask_area_ratio"),
        "overlay": str(overlay_path) if overlay_written else None,
        "paper_guidance": str(paper_guidance_path) if paper_guidance_written else None,
        "result": str(result_path),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if overlay_written and paper_guidance_written and bool(result.get("tracking_ready")) else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
