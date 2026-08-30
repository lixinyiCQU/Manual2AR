#!/usr/bin/env python3
"""Run automatic three-component grounding and save a labelled proof image."""

from __future__ import annotations

import argparse
import base64
import json
import urllib.request
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


COMPONENTS = ["filament_spool", "empty_spool_holder", "build_plate"]


def post_json(url: str, payload: dict[str, object]) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=210) as response:
        return json.loads(response.read().decode("utf-8"))


def font(size: int) -> ImageFont.ImageFont:
    for path in (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ):
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            pass
    return ImageFont.load_default()


def render(source: bytes, result: dict[str, object], output: Path) -> None:
    canvas = Image.open(BytesIO(source)).convert("RGBA")
    width, height = canvas.size
    labels: list[tuple[str, list[int]]] = []

    for item in result.get("results", []):
        if not isinstance(item, dict) or not item.get("tracking_ready"):
            continue
        tracked = item.get("tracked") or {}
        encoded = tracked.get("overlay_png_base64", "")
        if encoded:
            overlay = Image.open(BytesIO(base64.b64decode(encoded))).convert("RGBA")
            if overlay.size != canvas.size:
                overlay = overlay.resize(canvas.size, Image.Resampling.LANCZOS)
            canvas = Image.alpha_composite(canvas, overlay)
        candidate = item.get("candidate") or {}
        box = candidate.get("bbox_0_1000") or []
        if len(box) == 4:
            labels.append((str(item.get("english_label", "COMPONENT")).upper(), box))

    draw = ImageDraw.Draw(canvas, "RGBA")
    label_font = font(max(18, round(width * 0.022)))
    for text, box in labels:
        x1, y1, x2, _ = [round(value) for value in box]
        center_x = round((x1 + x2) * width / 2000)
        top_y = round(y1 * height / 1000)
        text_box = draw.textbbox((0, 0), text, font=label_font)
        text_width = text_box[2] - text_box[0]
        text_height = text_box[3] - text_box[1]
        pad_x, pad_y = 12, 7
        left = max(8, min(width - text_width - pad_x * 2 - 8, center_x - text_width // 2 - pad_x))
        top = max(8, top_y - text_height - pad_y * 2 - 12)
        panel = (left, top, left + text_width + pad_x * 2, top + text_height + pad_y * 2)
        draw.rounded_rectangle(
            panel,
            radius=10,
            fill=(4, 27, 39, 225),
            outline=(18, 222, 238, 255),
            width=2,
        )
        draw.text(
            (left + pad_x, top + pad_y - text_box[1]),
            text,
            font=label_font,
            fill=(225, 255, 255, 255),
        )

    canvas.convert("RGB").save(output, quality=95)


def close_sessions(base_url: str, result: dict[str, object]) -> None:
    for item in result.get("results", []):
        if not isinstance(item, dict) or not item.get("session_id"):
            continue
        request = urllib.request.Request(
            f"{base_url.rstrip('/')}/api/tracking/sessions/{item['session_id']}",
            method="DELETE",
        )
        try:
            urllib.request.urlopen(request, timeout=10).close()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:8010")
    parser.add_argument("--output-dir", type=Path, default=Path("output/component_overview"))
    args = parser.parse_args()

    image_path = args.image.expanduser().resolve()
    source = image_path.read_bytes()
    result = post_json(
        f"{args.url.rstrip('/')}/api/components/locate",
        {
            "image_base64": base64.b64encode(source).decode("ascii"),
            "component_ids": COMPONENTS,
        },
    )
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir.expanduser().resolve() / f"{image_path.stem}_{run_id}"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    proof = output_dir / "component_overview.jpg"
    render(source, result, proof)
    close_sessions(args.url, result)

    summary = {
        "model": result.get("model"),
        "provider": result.get("provider"),
        "ready": {
            item.get("component_id"): item.get("tracking_ready")
            for item in result.get("results", [])
            if isinstance(item, dict)
        },
        "proof": str(proof),
        "result": str(output_dir / "result.json"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if all(summary["ready"].get(item) for item in COMPONENTS) else 2


if __name__ == "__main__":
    raise SystemExit(main())
