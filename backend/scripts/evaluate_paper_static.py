#!/usr/bin/env python3
"""Evaluate static Manual2AR paper panels (a) and (e) from saved images.

Panel (a) grounds exactly six reviewed manual-derived component terms.  Qwen
proposes tight boxes; an optional local SAM2 service refines each visible box
to a recorded polygon when its own mask-quality gate passes.

Panel (e) evaluates only four visible build-plate predicates.  A deterministic
gate, not the model's overall confidence, owns ``safe_to_advance``.

The script writes raw model output, structured results, evidence geometry, and
provenance separately so clean paper rendering never changes model evidence.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models import GuidanceTarget
from app.tracking_provider import RemoteSam2Tracker, TrackingProviderError
from app.vision_client import QwenChatCompletionsClient


COMPONENT_LABELS = {
    "a1_mini_toolhead_assembly": "A1 mini toolhead assembly",
    "build_plate": "Build plate",
    "touchscreen": "Touchscreen",
    "ams_lite_spool_holder": "AMS Lite spool holder",
    "filament_inlet": "Filament inlet",
    "ptfe_tube": "PTFE tube",
}
REQUIRED_COMPONENT_IDS = tuple(COMPONENT_LABELS)
REQUIRED_PLATE_PREDICATES = (
    "plate_present",
    "plate_aligned",
    "surface_clear",
    "no_residue",
)


class GroundedComponent(BaseModel):
    component_id: Literal[
        "a1_mini_toolhead_assembly",
        "build_plate",
        "touchscreen",
        "ams_lite_spool_holder",
        "filament_inlet",
        "ptfe_tube",
    ]
    visible: bool
    confidence: float = Field(ge=0.0, le=1.0)
    bbox_0_1000: list[int] = Field(min_length=4, max_length=4)
    visible_evidence: str
    ambiguity: str = ""


class ComponentGroundingResult(BaseModel):
    device_match: bool
    components: list[GroundedComponent]
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_one_record_per_component(self) -> "ComponentGroundingResult":
        ids = [item.component_id for item in self.components]
        if len(ids) != len(set(ids)):
            raise ValueError("component grounding contains duplicate component IDs")
        missing = sorted(set(REQUIRED_COMPONENT_IDS) - set(ids))
        if missing:
            raise ValueError("component grounding is missing: " + ", ".join(missing))
        return self


class PlatePredicate(BaseModel):
    predicate_id: Literal[
        "plate_present", "plate_aligned", "surface_clear", "no_residue"
    ]
    status: Literal["completed", "failed", "uncertain"]
    confidence: float = Field(ge=0.0, le=1.0)
    bbox_0_1000: list[int] = Field(min_length=4, max_length=4)
    visible_evidence: str
    failure_reason: str = ""
    correction_instruction: str = ""


class PlateInspectionResult(BaseModel):
    device_match: bool
    predicates: list[PlatePredicate]
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_all_predicates(self) -> "PlateInspectionResult":
        ids = [item.predicate_id for item in self.predicates]
        if len(ids) != len(set(ids)):
            raise ValueError("plate inspection contains duplicate predicates")
        missing = sorted(set(REQUIRED_PLATE_PREDICATES) - set(ids))
        if missing:
            raise ValueError("plate inspection is missing: " + ", ".join(missing))
        return self


def _encode(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _valid_box(box: list[int]) -> bool:
    if len(box) != 4:
        return False
    x1, y1, x2, y2 = box
    return 0 <= x1 < x2 <= 1000 and 0 <= y1 < y2 <= 1000


def plate_server_gate(result: PlateInspectionResult) -> tuple[bool, list[str]]:
    """Compute visible-condition readiness without model-owned aggregation."""
    reasons: list[str] = []
    if not result.device_match:
        reasons.append("image does not credibly show the tested A1 mini build plate")
    by_id = {item.predicate_id: item for item in result.predicates}
    for predicate_id in REQUIRED_PLATE_PREDICATES:
        item = by_id[predicate_id]
        if item.status != "completed":
            reasons.append(f"{predicate_id} is {item.status}")
        if item.confidence < 0.75:
            reasons.append(f"{predicate_id} confidence is below 0.75")
        if not _valid_box(item.bbox_0_1000):
            reasons.append(f"{predicate_id} has no valid visible evidence region")
    return not reasons, reasons


def _component_prompt() -> str:
    terms = "\n".join(f"- {key}: {value}" for key, value in COMPONENT_LABELS.items())
    return f"""
You are producing auditable component grounding for one Manual2AR paper panel.
The image should show an A1 mini with AMS Lite. Return exactly one entry for
each canonical component below, using the canonical component_id verbatim:
{terms}

For every component, report whether it is visibly identifiable and a tight
[x1,y1,x2,y2] box normalized to 0..1000. A filament_inlet is the visible feeder
entry region on an AMS Lite feeding module, not a spool or yellow release
button. A PTFE tube is the visible translucent tube, not a generic cable.
Do not infer hidden surfaces. If a required component is not sufficiently
visible, set visible=false, use the smallest valid placeholder [0,0,1,1], and
explain the ambiguity. Keep evidence text concise. This output supports only
visible component grounding, not task completion or arbitrary-device transfer.
""".strip()


def _plate_prompt() -> str:
    return """
Inspect only the visible A1 mini build plate in this image. Return exactly four
predicates: plate_present, plate_aligned, surface_clear, and no_residue.

For each predicate return completed, failed, or uncertain, a tight visible
evidence box normalized to 0..1000, and concise evidence. plate_aligned means
the removable plate visibly sits squarely on its support without obvious
offset or lift. surface_clear means no foreign object blocks the printable
surface. no_residue means no visible leftover print or debris is present.
Use failed only for directly visible contradiction; use uncertain when the
relevant area is occluded, blurred, or outside the image. Do not infer
temperature, printer readiness, or hidden mechanical state. If uncertain and
no credible region exists, use [0,0,1,1].
""".strip()


def _sam_refine(
    *,
    tracker: RemoteSam2Tracker,
    image_bytes: bytes,
    component: GroundedComponent,
) -> dict[str, object]:
    target = GuidanceTarget(
        expected_component_id=component.component_id,
        semantic_role="target",
        render_mode="outline",
        target_point_0_1000=[
            round((component.bbox_0_1000[0] + component.bbox_0_1000[2]) / 2),
            round((component.bbox_0_1000[1] + component.bbox_0_1000[3]) / 2),
        ],
        expected_area_ratio_min=0.0002,
        expected_area_ratio_max=0.45,
    )
    session_id, tracked = tracker.start(
        image_bytes,
        component.component_id,
        component.bbox_0_1000,
        target,
    )
    try:
        return tracked.model_dump(mode="json")
    finally:
        tracker.close(session_id)


def evaluate_component_panel(
    *,
    image_path: Path,
    output_dir: Path,
    client: QwenChatCompletionsClient,
    sam2_url: str | None,
) -> dict[str, object]:
    raw = client.chat_structured(
        prompt=_component_prompt(),
        schema=ComponentGroundingResult.model_json_schema(),
        images_base64=[_encode(image_path)],
        max_tokens=1800,
    )
    result = ComponentGroundingResult.model_validate(raw)
    if not result.device_match:
        raise ValueError("panel (a) image was not identified as the tested device setup")
    unusable = [
        item.component_id
        for item in result.components
        if not item.visible or item.confidence < 0.50 or not _valid_box(item.bbox_0_1000)
    ]
    if unusable:
        raise ValueError(
            "panel (a) needs a clearer overview; unusable component evidence: "
            + ", ".join(unusable)
        )

    tracker = RemoteSam2Tracker(sam2_url) if sam2_url else None
    image_bytes = image_path.read_bytes()
    evidence_components: list[dict[str, object]] = []
    sam_records: list[dict[str, object]] = []
    for item in result.components:
        evidence: dict[str, object] = {
            "component_id": item.component_id,
            "display_label": COMPONENT_LABELS[item.component_id],
            "display_status": "target",
            "bbox_0_1000": item.bbox_0_1000,
            "confidence": item.confidence,
            "visible_evidence": item.visible_evidence,
            "geometry_source": "qwen_bbox",
        }
        if tracker is not None:
            try:
                tracked = _sam_refine(
                    tracker=tracker,
                    image_bytes=image_bytes,
                    component=item,
                )
                sam_records.append(tracked)
                if tracked.get("mask_quality_passed") and tracked.get("polygon_0_1000"):
                    evidence.update(
                        {
                            "polygon_0_1000": tracked["polygon_0_1000"],
                            "mask_quality_passed": True,
                            "mask_quality_reasons": tracked.get("mask_quality_reasons", []),
                            "mask_area_ratio": tracked.get("mask_area_ratio"),
                            "prompt_containment": tracked.get("prompt_containment"),
                            "geometry_source": "sam2_polygon",
                        }
                    )
                else:
                    evidence.update(
                        {
                            "mask_quality_passed": False,
                            "mask_quality_reasons": tracked.get("mask_quality_reasons", []),
                            "geometry_fallback_reason": "SAM2 mask failed its recorded quality gate",
                        }
                    )
            except TrackingProviderError as exc:
                evidence["geometry_fallback_reason"] = f"SAM2 unavailable: {exc}"
        evidence_components.append(evidence)

    structured = {
        "schema_version": "paper-static-component-grounding-1.0",
        "figure_id": "a",
        "status": "completed",
        "device_match": result.device_match,
        "required_component_ids": list(REQUIRED_COMPONENT_IDS),
        "components": [item.model_dump(mode="json") for item in result.components],
        "limitations": result.limitations,
        "safe_to_advance": None,
    }
    evidence = {
        "schema_version": "paper-recorded-evidence-1.0",
        "figure_id": "a",
        "components": evidence_components,
    }
    _write_outputs(output_dir, raw=raw, structured=structured, evidence=evidence)
    if sam_records:
        _write_json(output_dir / "sam2_records.json", {"records": sam_records})
    return structured


def evaluate_plate_panel(
    *,
    image_path: Path,
    output_dir: Path,
    client: QwenChatCompletionsClient,
) -> dict[str, object]:
    raw = client.chat_structured(
        prompt=_plate_prompt(),
        schema=PlateInspectionResult.model_json_schema(),
        images_base64=[_encode(image_path)],
        max_tokens=1400,
    )
    result = PlateInspectionResult.model_validate(raw)
    safe, gate_reasons = plate_server_gate(result)
    predicate_evidence = []
    evidence_components = []
    for item in result.predicates:
        predicate_evidence.append(
            {
                **item.model_dump(mode="json"),
                "evidence_region": [
                    {
                        "component_id": "build_plate",
                        "bbox_0_1000": item.bbox_0_1000,
                        "observation": item.visible_evidence,
                    }
                ],
                "necessary": True,
            }
        )
        evidence_components.append(
            {
                "component_id": item.predicate_id,
                "display_label": item.predicate_id.replace("_", " "),
                "display_status": (
                    "passed" if item.status == "completed"
                    else "error" if item.status == "failed"
                    else "uncertain"
                ),
                "bbox_0_1000": item.bbox_0_1000,
                "confidence": item.confidence,
                "visible_evidence": item.visible_evidence,
                "geometry_source": "qwen_bbox",
            }
        )
    structured = {
        "schema_version": "paper-static-plate-inspection-1.0",
        "figure_id": "e",
        "status": "completed" if safe else "wrong_operation",
        "device_match": result.device_match,
        "predicate_evidence": predicate_evidence,
        "safe_to_advance": safe,
        "server_gate": {
            "owner": "deterministic_visible_predicate_gate",
            "confidence_threshold": 0.75,
            "failure_reasons": gate_reasons,
        },
        "limitations": result.limitations,
    }
    evidence = {
        "schema_version": "paper-recorded-evidence-1.0",
        "figure_id": "e",
        "components": evidence_components,
    }
    _write_outputs(output_dir, raw=raw, structured=structured, evidence=evidence)
    return structured


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_outputs(
    output_dir: Path,
    *,
    raw: dict[str, object],
    structured: dict[str, object],
    evidence: dict[str, object],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "raw_model_result.json", raw)
    _write_json(output_dir / "result.json", structured)
    _write_json(output_dir / "evidence.json", evidence)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("panel", choices=("a", "e"))
    parser.add_argument("image", type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("output/paper_static"))
    parser.add_argument("--run-id")
    parser.add_argument("--sam2-url", default="http://127.0.0.1:8020")
    parser.add_argument("--no-sam2", action="store_true")
    args = parser.parse_args()

    image_path = args.image.expanduser().resolve()
    if not image_path.is_file():
        raise FileNotFoundError(image_path)
    run_id = args.run_id or datetime.now(timezone.utc).strftime(
        f"{args.panel.upper()}_%Y%m%dT%H%M%SZ"
    )
    output_dir = (args.output_root / run_id).resolve()
    client = QwenChatCompletionsClient()
    if args.panel == "a":
        result = evaluate_component_panel(
            image_path=image_path,
            output_dir=output_dir,
            client=client,
            sam2_url=None if args.no_sam2 else args.sam2_url,
        )
        prompt_version = "paper_component_grounding_v1"
    else:
        result = evaluate_plate_panel(
            image_path=image_path,
            output_dir=output_dir,
            client=client,
        )
        prompt_version = "paper_plate_visible_predicates_v1"

    _write_json(
        output_dir / "provenance.json",
        {
            "schema_version": "paper-static-provenance-1.0",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "figure_id": args.panel,
            "run_id": run_id,
            "source_image": str(image_path),
            "source_sha256": _sha256(image_path),
            "provider": "qwen",
            "model": client.model,
            "base_url": client.base_url,
            "prompt_version": prompt_version,
            "sam2_url": None if args.no_sam2 or args.panel != "a" else args.sam2_url,
            "structured_result": str(output_dir / "result.json"),
            "evidence_geometry": str(output_dir / "evidence.json"),
            "claim_scope": (
                "visible manual-derived component grounding"
                if args.panel == "a"
                else "visible build-plate installation and surface-state inspection"
            ),
        },
    )
    print(f"paper panel ({args.panel}) static evaluation completed")
    print(f"run_id={run_id}")
    print(f"safe_to_advance={result.get('safe_to_advance')}")
    print(f"result_file={(output_dir / 'result.json').resolve()}")
    print(f"evidence_file={(output_dir / 'evidence.json').resolve()}")


if __name__ == "__main__":
    main()
