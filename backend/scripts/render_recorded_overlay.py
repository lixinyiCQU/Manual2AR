#!/usr/bin/env python3
"""Render a clean paper overlay from recorded Manual2AR evidence.

The renderer is intentionally conservative: it accepts only geometry already
stored by the runtime (polygon, mask, or bounding box).  It never predicts,
repairs, or hand-draws missing model evidence.  Styling annotations are saved
separately from evidence geometry so a paper figure remains auditable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


FONT_CANDIDATES = (
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
)

PAPER_COLORS = {
    "target": (26, 203, 223, 92),
    "passed": (31, 181, 111, 92),
    "uncertain": (242, 184, 49, 92),
    "error": (231, 76, 60, 92),
}


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve(base: Path, value: str, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (base / path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} does not exist: {path}")
    return path


def _point(point: list[float], width: int, height: int) -> tuple[int, int]:
    if len(point) != 2:
        raise ValueError(f"point must contain two coordinates: {point}")
    return round(float(point[0]) * width / 1000), round(float(point[1]) * height / 1000)


def _bbox(box: list[float], width: int, height: int) -> tuple[int, int, int, int]:
    if len(box) != 4:
        raise ValueError(f"bbox must contain four coordinates: {box}")
    x1, y1 = _point(box[:2], width, height)
    x2, y2 = _point(box[2:], width, height)
    return x1, y1, x2, y2


def _load_components(payload: dict[str, Any]) -> list[dict[str, Any]]:
    components = payload.get("components")
    if components is None:
        components = payload.get("guidance_highlight", {}).get("components")
    if components is None and payload.get("polygon_0_1000") is not None:
        components = [payload]
    if not isinstance(components, list) or not components:
        raise ValueError("evidence JSON contains no recorded components")
    return components


def _component_style(component: dict[str, Any]) -> tuple[str, tuple[int, int, int, int]]:
    requested = str(component.get("display_status") or "").lower()
    if requested in PAPER_COLORS:
        return requested, PAPER_COLORS[requested]
    if component.get("mask_accepted") is False or component.get("mask_quality_passed") is False:
        return "uncertain", PAPER_COLORS["uncertain"]
    status = str(component.get("status") or "target").lower()
    if status in {"passed", "completed", "verified"}:
        return "passed", PAPER_COLORS["passed"]
    if status in {"error", "failed", "incorrect"}:
        return "error", PAPER_COLORS["error"]
    return "target", PAPER_COLORS["target"]


def _recorded_geometry(component: dict[str, Any]) -> tuple[str, Any]:
    polygon = component.get("polygon_0_1000") or component.get("polygon")
    if isinstance(polygon, list) and len(polygon) >= 3:
        return "polygon", polygon
    mask_file = component.get("mask_file")
    if mask_file:
        return "mask", mask_file
    bbox = component.get("mask_bbox_0_1000") or component.get("bbox_0_1000")
    if isinstance(bbox, list) and len(bbox) == 4:
        return "bbox", bbox
    raise ValueError(
        f"component {component.get('component_id')!r} has no recorded polygon, mask, or bbox"
    )


def render(
    *,
    raw_path: Path,
    evidence_path: Path,
    output_path: Path,
    provenance_path: Path,
) -> dict[str, Any]:
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    components = _load_components(payload)
    base = Image.open(raw_path).convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    rendered: list[dict[str, Any]] = []

    for component in components:
        geometry_kind, geometry = _recorded_geometry(component)
        display_status, color = _component_style(component)
        outline = color[:3] + (235,)
        label = str(component.get("display_label") or component.get("component_id") or "target")
        anchor: tuple[int, int]

        if geometry_kind == "polygon":
            points = [_point(point, base.width, base.height) for point in geometry]
            draw.polygon(points, fill=color)
            draw.line(points + [points[0]], fill=outline, width=max(3, base.width // 420))
            anchor = min(points, key=lambda point: (point[1], point[0]))
        elif geometry_kind == "bbox":
            box = _bbox(geometry, base.width, base.height)
            draw.rounded_rectangle(
                box,
                radius=max(6, base.width // 170),
                fill=color,
                outline=outline,
                width=max(3, base.width // 420),
            )
            anchor = box[0], box[1]
        else:
            mask_path = _resolve(evidence_path.parent, str(geometry), "mask_file")
            mask = Image.open(mask_path).convert("L").resize(base.size, Image.Resampling.NEAREST)
            tint = Image.new("RGBA", base.size, color)
            alpha = mask.point(lambda value: round(value * color[3] / 255))
            tint.putalpha(alpha)
            overlay.alpha_composite(tint)
            mask_bbox = mask.getbbox()
            if mask_bbox is None:
                raise ValueError(f"recorded mask is empty: {mask_path}")
            draw.rectangle(mask_bbox, outline=outline, width=max(3, base.width // 420))
            anchor = mask_bbox[0], mask_bbox[1]

        label_font = _font(max(24, base.width // 36))
        text_box = draw.textbbox((0, 0), label, font=label_font)
        label_width = text_box[2] - text_box[0]
        label_height = text_box[3] - text_box[1]
        label_x = max(8, min(anchor[0], base.width - label_width - 28))
        label_y = max(8, anchor[1] - label_height - 24)
        draw.rounded_rectangle(
            (label_x - 10, label_y - 7, label_x + label_width + 10, label_y + label_height + 10),
            radius=8,
            fill=(15, 34, 54, 210),
        )
        draw.text((label_x, label_y), label, font=label_font, fill=(255, 255, 255, 255))
        rendered.append(
            {
                "component_id": component.get("component_id"),
                "display_label": label,
                "display_status": display_status,
                "geometry_kind": geometry_kind,
                "geometry": geometry,
                "mask_quality_passed": component.get("mask_quality_passed"),
                "mask_accepted": component.get("mask_accepted"),
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    Image.alpha_composite(base, overlay).convert("RGB").save(output_path, quality=95)
    provenance = {
        "schema_version": "recorded-overlay-provenance-1.0",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "raw_image": str(raw_path.resolve()),
        "raw_sha256": _sha256(raw_path),
        "evidence_json": str(evidence_path.resolve()),
        "evidence_sha256": _sha256(evidence_path),
        "output_overlay": str(output_path.resolve()),
        "rendered_components": rendered,
        "evidence_geometry_modified": False,
        "note": "Only visual styling and labels were added to recorded runtime geometry.",
    }
    provenance_path.parent.mkdir(parents=True, exist_ok=True)
    provenance_path.write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return provenance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_image", type=Path)
    parser.add_argument("evidence_json", type=Path)
    parser.add_argument("output_overlay", type=Path)
    parser.add_argument("--provenance", type=Path)
    args = parser.parse_args()
    provenance_path = args.provenance or args.output_overlay.with_suffix(".provenance.json")
    result = render(
        raw_path=args.raw_image.resolve(),
        evidence_path=args.evidence_json.resolve(),
        output_path=args.output_overlay.resolve(),
        provenance_path=provenance_path.resolve(),
    )
    print(f"rendered {len(result['rendered_components'])} recorded components")
    print(args.output_overlay.resolve())


if __name__ == "__main__":
    main()
