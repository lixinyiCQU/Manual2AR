#!/usr/bin/env python3
"""Export traceable paper panels from saved Manual2AR evidence.

This exporter never invents an overlay.  Every visual panel must point to an
existing raw image and an existing system-rendered output.  It only performs
layout, cropping-free scaling, labels, hashes, and manifest generation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


FONT_CANDIDATES = (
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
)


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


def _fit(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    canvas = Image.new("RGB", size, "white")
    copy = image.convert("RGB")
    copy.thumbnail(size, Image.Resampling.LANCZOS)
    left = (size[0] - copy.width) // 2
    top = (size[1] - copy.height) // 2
    canvas.paste(copy, (left, top))
    return canvas


def _read_result_summary(result_path: Path | None) -> str:
    if result_path is None:
        return ""
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    status = payload.get("status")
    safe_to_advance = payload.get("safe_to_advance")
    predicates = payload.get("predicate_evidence") or payload.get("predicates") or []
    passed = sum(
        1
        for item in predicates
        if item.get("status") in {"passed", "completed"}
    )
    necessary = sum(1 for item in predicates if item.get("necessary", True))
    return (
        f"status={status} · safe_to_advance={safe_to_advance} · "
        f"necessary predicates passed={passed}/{necessary}"
    )


def _render_panel(
    *,
    figure_id: str,
    title: str,
    caption: str,
    raw_path: Path,
    overlay_path: Path,
    result_path: Path | None,
    output_path: Path,
) -> None:
    width = 3600
    header_height = 260
    image_height = 2150
    footer_height = 430
    gap = 50
    cell_width = (width - gap * 3) // 2
    canvas = Image.new("RGB", (width, header_height + image_height + footer_height), "white")
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, width, header_height), fill=(19, 47, 78))
    draw.text((70, 52), f"({figure_id}) {title}", font=_font(76), fill="white")

    raw = _fit(Image.open(raw_path), (cell_width, image_height - 100))
    overlay = _fit(Image.open(overlay_path), (cell_width, image_height - 100))
    raw_x = gap
    overlay_x = gap * 2 + cell_width
    canvas.paste(raw, (raw_x, header_height + 75))
    canvas.paste(overlay, (overlay_x, header_height + 75))
    label_font = _font(45)
    draw.text((raw_x, header_height + 12), "Raw input", font=label_font, fill=(30, 45, 60))
    draw.text(
        (overlay_x, header_height + 12),
        "Recorded system output",
        font=label_font,
        fill=(30, 45, 60),
    )
    footer_y = header_height + image_height
    draw.line((60, footer_y + 15, width - 60, footer_y + 15), fill=(190, 200, 210), width=4)
    summary = _read_result_summary(result_path)
    body = caption if not summary else f"{caption}\n{summary}"
    lines: list[str] = []
    for paragraph in body.splitlines():
        lines.extend(textwrap.wrap(paragraph, width=88) or [""])
    draw.multiline_text(
        (70, footer_y + 65),
        "\n".join(lines[:5]),
        font=_font(45),
        fill=(35, 45, 55),
        spacing=18,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, dpi=(300, 300), optimize=True)


def export(spec_path: Path, output_root: Path) -> dict[str, Any]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    panels = spec.get("panels")
    if not isinstance(panels, list) or not panels:
        raise ValueError("spec.panels must contain at least one paper panel")
    output_root.mkdir(parents=True, exist_ok=True)
    evidence_root = output_root / "evidence"
    figures_root = output_root / "figures_300dpi"
    manifest_panels: list[dict[str, Any]] = []

    for panel in panels:
        figure_id = str(panel["figure_id"]).strip().lower()
        if figure_id not in {"a", "b", "c", "d", "e", "f"}:
            raise ValueError(f"unsupported figure_id: {figure_id}")
        raw_path = _resolve(spec_path.parent, panel["raw_image"], "raw_image")
        overlay_path = _resolve(spec_path.parent, panel["overlay_image"], "overlay_image")
        result_path = (
            _resolve(spec_path.parent, panel["result_json"], "result_json")
            if panel.get("result_json")
            else None
        )
        tracking_path = (
            _resolve(spec_path.parent, panel["tracking_log"], "tracking_log")
            if panel.get("tracking_log")
            else None
        )
        run_id = str(panel.get("run_id") or f"figure-{figure_id}")
        panel_dir = evidence_root / f"figure_{figure_id}" / run_id
        panel_dir.mkdir(parents=True, exist_ok=True)
        copied: dict[str, str] = {}
        for label, source in (
            ("raw", raw_path),
            ("overlay", overlay_path),
            ("result", result_path),
            ("tracking", tracking_path),
        ):
            if source is None:
                continue
            destination = panel_dir / f"{label}{source.suffix.lower()}"
            shutil.copy2(source, destination)
            copied[label] = str(destination)

        output_path = figures_root / f"figure_{figure_id}.png"
        _render_panel(
            figure_id=figure_id,
            title=str(panel["title"]),
            caption=str(panel["caption"]),
            raw_path=raw_path,
            overlay_path=overlay_path,
            result_path=result_path,
            output_path=output_path,
        )
        manifest_panels.append(
            {
                "figure_id": figure_id,
                "run_id": run_id,
                "claim": str(panel["claim"]),
                "paper_use_allowed": bool(panel.get("paper_use_allowed", False)),
                "raw_source": str(raw_path),
                "raw_sha256": _sha256(raw_path),
                "overlay_source": str(overlay_path),
                "overlay_sha256": _sha256(overlay_path),
                "result_source": str(result_path) if result_path else None,
                "result_sha256": _sha256(result_path) if result_path else None,
                "tracking_log": str(tracking_path) if tracking_path else None,
                "tracking_log_sha256": _sha256(tracking_path) if tracking_path else None,
                "manual_version": panel.get("manual_version"),
                "compile_version": panel.get("compile_version"),
                "model_version": panel.get("model_version"),
                "prompt_version": panel.get("prompt_version"),
                "exported_figure": str(output_path),
                "copied_evidence": copied,
            }
        )

    manifest = {
        "schema_version": "figure-evidence-manifest-1.0",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_spec": str(spec_path.resolve()),
        "layout_only": True,
        "warning": "Overlays are copied from recorded system output; this exporter does not create model evidence.",
        "panels": manifest_panels,
    }
    manifest_path = output_root / "figure_evidence_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("output_root", type=Path)
    args = parser.parse_args()
    manifest = export(args.spec, args.output_root)
    print(f"exported {len(manifest['panels'])} traceable paper panels")
    print(Path(args.output_root).resolve() / "figure_evidence_manifest.json")


if __name__ == "__main__":
    main()
