from __future__ import annotations

import argparse
import base64
import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw
from pydantic import BaseModel, Field

from app.models import ComponentBox
from app.vision_client import VisionClient


class VisibleCheck(BaseModel):
    check_id: str
    condition: str
    status: Literal["satisfied", "violated", "uncertain"]
    evidence: str


class FieldPairResult(BaseModel):
    status: Literal["completed", "wrong_operation", "uncertain"]
    device_match: bool
    same_target_area: bool
    before_observation: str
    after_observation: str
    checks: list[VisibleCheck]
    component_boxes_0_1000: list[ComponentBox] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    confounders: list[str] = Field(default_factory=list)


def _encode(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _post_json(url: str, payload: dict[str, object], timeout: int = 180) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_") or "component"


def _render_highlight(
    *,
    source_path: Path,
    boxes: list[ComponentBox],
    backend_url: str,
    output_dir: Path,
    output_name: str,
    seed_source: str,
    min_mask_area_to_prompt_ratio: float = 0.18,
) -> dict[str, object]:
    source = Image.open(source_path).convert("RGBA")
    image_encoded = _encode(source_path)
    providers: list[str] = []
    retained_boxes: list[dict[str, object]] = []

    for index, box in enumerate(boxes):
        x1, y1, x2, y2 = box.bbox_0_1000
        area_ratio = ((x2 - x1) * (y2 - y1)) / 1_000_000
        if area_ratio > 0.65:
            continue
        tracked = _post_json(
            f"{backend_url.rstrip('/')}/api/tracking/sessions",
            {
                "image_base64": image_encoded,
                "component_id": box.component_id,
                "bbox_0_1000": box.bbox_0_1000,
            },
            timeout=120,
        )
        session_id = str(tracked["session_id"])
        component = tracked["tracked"]
        try:
            overlay_text = str(component.get("overlay_png_base64", ""))
            if overlay_text:
                overlay_bytes = base64.b64decode(overlay_text)
                overlay = Image.open(BytesIO(overlay_bytes)).convert("RGBA")
                if overlay.size != source.size:
                    overlay = overlay.resize(source.size)
                alpha_histogram = overlay.getchannel("A").histogram()
                mask_pixels = sum(alpha_histogram[1:])
                prompt_pixels = max(
                    1.0,
                    (x2 - x1)
                    / 1000
                    * source.width
                    * (y2 - y1)
                    / 1000
                    * source.height,
                )
                mask_area_to_prompt_ratio = mask_pixels / prompt_pixels
                mask_accepted = (
                    min_mask_area_to_prompt_ratio
                    <= mask_area_to_prompt_ratio
                    <= 3.0
                )
                if mask_accepted:
                    source = Image.alpha_composite(source, overlay)
                overlay_path = output_dir / (
                    f"{'mask' if mask_accepted else 'rejected_mask'}_"
                    f"{index + 1:02d}_{_safe_name(box.component_id)}.png"
                )
                overlay_path.write_bytes(overlay_bytes)
            else:
                mask_area_to_prompt_ratio = 0.0
                mask_accepted = False
            providers.append(str(component.get("provider", "unknown")))
            retained_boxes.append(
                {
                    "component_id": box.component_id,
                    "prompt_bbox_0_1000": box.bbox_0_1000,
                    "mask_bbox_0_1000": component.get("bbox_0_1000"),
                    "quality": component.get("quality"),
                    "provider": component.get("provider"),
                    "status": component.get("status"),
                    "mask_area_to_prompt_ratio": round(
                        mask_area_to_prompt_ratio,
                        4,
                    ),
                    "mask_accepted": mask_accepted,
                    "fallback": None if mask_accepted else "transparent_box",
                }
            )
        finally:
            request = urllib.request.Request(
                f"{backend_url.rstrip('/')}/api/tracking/sessions/{session_id}",
                method="DELETE",
            )
            try:
                urllib.request.urlopen(request, timeout=30).read()
            except urllib.error.HTTPError:
                pass

    box_overlay = Image.new("RGBA", source.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(box_overlay, "RGBA")
    width, height = source.size
    for box in boxes:
        x1, y1, x2, y2 = box.bbox_0_1000
        pixels = (
            round(x1 / 1000 * width),
            round(y1 / 1000 * height),
            round(x2 / 1000 * width),
            round(y2 / 1000 * height),
        )
        draw.rectangle(
            pixels,
            fill=(33, 210, 164, 18),
            outline=(33, 210, 164, 235),
            width=max(3, width // 350),
        )
    source = Image.alpha_composite(source, box_overlay)
    highlight_path = output_dir / output_name
    source.convert("RGB").save(highlight_path, quality=94)
    return {
        "highlight_file": str(highlight_path),
        "source_image": str(source_path),
        "seed_source": seed_source,
        "providers": sorted(set(providers)),
        "components": retained_boxes,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("output/evaluations/field_sequences"),
    )
    parser.add_argument("--backend-url", default="http://127.0.0.1:8010")
    parser.add_argument(
        "--sample-id",
        action="append",
        default=[],
        help="Only evaluate the listed sample id; repeat for multiple stages.",
    )
    parser.add_argument(
        "--guidance-only",
        action="store_true",
        help="Render the predefined before-action highlight without calling a VLM.",
    )
    parser.add_argument("--no-highlight", action="store_true")
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    payload = json.loads(args.manifest.resolve().read_text(encoding="utf-8"))
    client = VisionClient()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    summaries: list[dict[str, object]] = []

    for stage in payload["stages"]:
        if args.sample_id and stage["sample_id"] not in set(args.sample_id):
            continue
        before_path = project_root / stage["before_image"]
        after_path = project_root / stage["after_image"]
        output_dir = args.output_root / stage["sample_id"] / timestamp
        output_dir.mkdir(parents=True, exist_ok=True)
        guidance = stage.get("guidance_highlight")
        if args.guidance_only:
            guidance_highlight = None
            if guidance:
                guidance_path = (
                    before_path
                    if guidance["image_role"] == "before"
                    else after_path
                )
                guidance_highlight = _render_highlight(
                    source_path=guidance_path,
                    boxes=[
                        ComponentBox(
                            component_id=guidance["component_id"],
                            bbox_0_1000=guidance["bbox_0_1000"],
                            observation=guidance["note"],
                        )
                    ],
                    backend_url=args.backend_url,
                    output_dir=output_dir,
                    output_name="guidance_highlight_before.png",
                    seed_source=str(guidance["seed_source"]),
                    min_mask_area_to_prompt_ratio=float(
                        guidance.get("min_mask_area_to_prompt_ratio", 0.18)
                    ),
                )
            preview_record = {
                "sample_id": stage["sample_id"],
                "mode": "guidance_only",
                "knowledge_version": payload["knowledge_version"],
                "guidance_highlight": guidance_highlight,
            }
            preview_path = output_dir / "guidance_preview.json"
            preview_path.write_text(
                json.dumps(preview_record, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            summaries.append(
                {
                    "sample_id": stage["sample_id"],
                    "mode": "guidance_only",
                    "guidance_highlight_file": (
                        guidance_highlight["highlight_file"]
                        if guidance_highlight
                        else None
                    ),
                    "result_file": str(preview_path.resolve()),
                }
            )
            continue
        prompt = (
            "你是Manual2AR的保守视觉证据评估器。IMAGE 1是操作前，IMAGE 2是操作后，"
            "不得颠倒。只判断下方预定义的可见条件。人工真值没有提供给你。"
            "不要从标签或常识臆测机器内部状态；看不清就返回uncertain。"
            "component_boxes_0_1000只能来自IMAGE 2，并且必须紧贴请求的局部部件，"
            "不能框整机、整幅图或完整长管路。背景里的灰色2号槽料盘不是橙色目标。\n\n"
            f"设备：{payload['device']}\n"
            f"操作：{stage['operation']}\n"
            f"预定义知识：{json.dumps(payload['knowledge'], ensure_ascii=False)}\n"
            f"必须逐项检查：{json.dumps(stage['conditions'], ensure_ascii=False)}\n"
            f"请求定位的部件：{json.dumps(stage['requested_components'], ensure_ascii=False)}\n"
            "completed表示所有条件在操作后清晰满足；wrong_operation表示有明确反证；"
            "其余情况返回uncertain。每个条件都必须在checks中单独返回，"
            "并原样复制对应的check_id；不得改写、漏掉或新增check_id。"
        )
        try:
            raw = client.chat_structured(
                prompt=prompt,
                schema=FieldPairResult.model_json_schema(),
                images_base64=[_encode(before_path), _encode(after_path)],
                max_tokens=1200,
            )
            result = FieldPairResult.model_validate(raw)
        except Exception as exc:
            error_record = {
                "sample_id": stage["sample_id"],
                "sequence_id": payload["sequence_id"],
                "provider": client.provider,
                "model": client.model,
                "knowledge_version": payload["knowledge_version"],
                "before_image": str(before_path),
                "after_image": str(after_path),
                "model_error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
                "server_gate": {
                    "safe_to_advance": False,
                    "reason": "model_response_invalid",
                },
                "human_comparison": {
                    "expected_status": stage["human_label"]["status"],
                    "exact_status_match": False,
                    "human_note": stage["human_label"]["note"],
                },
            }
            error_path = output_dir / "result.json"
            error_path.write_text(
                json.dumps(error_record, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            summaries.append(
                {
                    "sample_id": stage["sample_id"],
                    "status": "model_error",
                    "safe_to_advance": False,
                    "exact_status_match": False,
                    "error": str(exc),
                    "result_file": str(error_path.resolve()),
                }
            )
            continue
        expected_check_ids = {
            str(item["check_id"]) for item in stage["conditions"]
        }
        returned_check_ids = {item.check_id for item in result.checks}
        checks_complete = expected_check_ids == returned_check_ids
        all_satisfied = checks_complete and all(
            item.status == "satisfied" for item in result.checks
        )
        safe_to_advance = bool(
            result.status == "completed"
            and result.device_match
            and result.same_target_area
            and all_satisfied
            and result.confidence >= 0.75
        )
        guidance_highlight = None
        if not args.no_highlight and guidance:
            guidance_path = (
                before_path if guidance["image_role"] == "before" else after_path
            )
            guidance_highlight = _render_highlight(
                source_path=guidance_path,
                boxes=[
                    ComponentBox(
                        component_id=guidance["component_id"],
                        bbox_0_1000=guidance["bbox_0_1000"],
                        observation=guidance["note"],
                    )
                ],
                backend_url=args.backend_url,
                output_dir=output_dir,
                output_name="guidance_highlight_before.png",
                seed_source=str(guidance["seed_source"]),
                min_mask_area_to_prompt_ratio=float(
                    guidance.get("min_mask_area_to_prompt_ratio", 0.18)
                ),
            )
        verification_highlight = None
        if not args.no_highlight and result.component_boxes_0_1000:
            verification_highlight = _render_highlight(
                source_path=after_path,
                boxes=result.component_boxes_0_1000,
                backend_url=args.backend_url,
                output_dir=output_dir,
                output_name="verification_highlight_after.png",
                seed_source="model",
            )
        record = {
            "sample_id": stage["sample_id"],
            "sequence_id": payload["sequence_id"],
            "provider": client.provider,
            "model": client.model,
            "knowledge_version": payload["knowledge_version"],
            "before_image": str(before_path),
            "after_image": str(after_path),
            "model_result": result.model_dump(),
            "server_gate": {
                "safe_to_advance": safe_to_advance,
                "threshold": 0.75,
                "checks_complete": checks_complete,
                "all_satisfied": all_satisfied,
            },
            "human_comparison": {
                "expected_status": stage["human_label"]["status"],
                "exact_status_match": result.status == stage["human_label"]["status"],
                "human_note": stage["human_label"]["note"],
            },
            "guidance_highlight": guidance_highlight,
            "verification_highlight": verification_highlight,
        }
        result_path = output_dir / "result.json"
        result_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        summaries.append(
            {
                "sample_id": stage["sample_id"],
                "status": result.status,
                "confidence": result.confidence,
                "safe_to_advance": safe_to_advance,
                "exact_status_match": record["human_comparison"]["exact_status_match"],
                "boxes": len(result.component_boxes_0_1000),
                "result_file": str(result_path.resolve()),
                "guidance_highlight_file": (
                    guidance_highlight["highlight_file"]
                    if guidance_highlight
                    else None
                ),
                "verification_highlight_file": (
                    verification_highlight["highlight_file"]
                    if verification_highlight
                    else None
                ),
            }
        )

    print(
        json.dumps(
            {
                "provider": client.provider,
                "model": client.model,
                "runs": summaries,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
