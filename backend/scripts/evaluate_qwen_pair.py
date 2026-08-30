from __future__ import annotations

import argparse
import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.vision_client import QwenChatCompletionsClient


class PairEvaluationResult(BaseModel):
    status: Literal["completed", "wrong_operation", "uncertain"]
    device_match: bool
    before_observation: str
    after_observation: str
    expected_change_visible: bool
    evidence: list[str]
    target_bbox_after_0_1000: list[int] = Field(min_length=4, max_length=4)
    confidence: float = Field(ge=0.0, le=1.0)
    confounders: list[str]


def _encode(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _valid_box(box: list[int]) -> bool:
    if len(box) != 4:
        return False
    x1, y1, x2, y2 = box
    return 0 <= x1 < x2 <= 1000 and 0 <= y1 < y2 <= 1000


def _box_iou(first: list[int], second: list[int]) -> float:
    if not _valid_box(first) or not _valid_box(second):
        return 0.0
    ax1, ay1, ax2, ay2 = first
    bx1, by1, bx2, by2 = second
    intersection_width = max(0, min(ax2, bx2) - max(ax1, bx1))
    intersection_height = max(0, min(ay2, by2) - max(ay1, by1))
    intersection = intersection_width * intersection_height
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - intersection
    return intersection / union if union > 0 else 0.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("sample_dir", type=Path)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("output/evaluations"),
    )
    args = parser.parse_args()

    sample_dir = args.sample_dir.resolve()
    truth = json.loads((sample_dir / "ground_truth.json").read_text())
    before = sample_dir / truth["image_order"]["before"]
    after = sample_dir / truth["image_order"]["after"]
    condition = truth["predefined_condition"]

    prompt = f"""
You are evaluating one fixed Manual2AR before/after visual checkpoint.

IMAGE 1 is BEFORE. IMAGE 2 is AFTER. Never reverse their order.
Device expected: {truth['device']}.
Target region: {condition['target_region']}.
Before requirement: {condition['before_required']}.
After requirement: {condition['after_required']}.
Completion rule: {condition['completion_rule']}.

Judge only this predefined visible condition. Ignore unrelated background
changes and small camera motion. Do not treat orange waste in the left-side
waste container or orange objects on the table as the target. If the target
region or evidence is not sufficiently visible, return uncertain. Return the
tight AFTER-image bounding box around the target object as [x1,y1,x2,y2]
normalized to 0..1000. If no credible target exists, return [0,0,1,1].
""".strip()

    client = QwenChatCompletionsClient()
    raw_result = client.chat_structured(
        prompt=prompt,
        schema=PairEvaluationResult.model_json_schema(),
        images_base64=[_encode(before), _encode(after)],
        max_tokens=1200,
    )
    result = PairEvaluationResult.model_validate(raw_result)
    safe_to_advance = (
        result.status == "completed"
        and result.device_match
        and result.expected_change_visible
        and result.confidence >= 0.75
        and _valid_box(result.target_bbox_after_0_1000)
    )

    expected = truth["human_label"]
    exact_label_match = (
        result.status == expected["status"]
        and result.device_match == expected["device_match"]
        and result.expected_change_visible == expected["expected_change_visible"]
    )
    bbox_iou = _box_iou(
        result.target_bbox_after_0_1000,
        expected["target_bbox_after_0_1000"],
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_root / truth["sample_id"]
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{client.model}_{timestamp}.json"
    record = {
        "sample_id": truth["sample_id"],
        "provider": "qwen",
        "model": client.model,
        "base_url": client.base_url,
        "prompt_version": "a1_sanity_pair_v1",
        "model_result": result.model_dump(),
        "server_gate": {"safe_to_advance": safe_to_advance, "threshold": 0.75},
        "human_comparison": {
            "exact_label_match": exact_label_match,
            "bbox_iou": bbox_iou,
            "human_bbox_after_0_1000": expected["target_bbox_after_0_1000"],
        },
    }
    output_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")

    print("Qwen before/after image test completed")
    print(f"sample_id={truth['sample_id']}")
    print(f"model={client.model}")
    print(f"status={result.status}")
    print(f"confidence={result.confidence:.3f}")
    print(f"expected_change_visible={result.expected_change_visible}")
    print(f"target_bbox_after_0_1000={result.target_bbox_after_0_1000}")
    print(f"safe_to_advance={safe_to_advance}")
    print(f"exact_label_match={exact_label_match}")
    print(f"bbox_iou={bbox_iou:.3f}")
    print(f"result_file={output_path.resolve()}")


if __name__ == "__main__":
    main()
