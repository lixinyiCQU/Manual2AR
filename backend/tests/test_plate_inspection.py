from __future__ import annotations

import base64
import io
import uuid

from PIL import Image, ImageDraw

from app.models import BuildPlateInspectionRequest, TrackedComponent
from app.plate_inspection import (
    PlateInspectionEngine,
    _compile_plate_visibility,
    _profile_residue_candidate,
    compile_anomaly_prompt,
)
from app.models import BuildPlateVisionResult
from app.models import BuildPlateAnomalyCandidate
from app.vision_task_profiles import PREPRINT_PLATE_INSPECTION_V1


def _image_base64(dirty: bool = True) -> str:
    image = Image.new("RGB", (160, 120), (225, 225, 225))
    if dirty:
        draw = ImageDraw.Draw(image)
        draw.rectangle((66, 65, 83, 78), fill=(238, 92, 22))
        draw.rectangle((65, 106, 78, 109), fill=(238, 92, 22))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _overlay(box: list[int]) -> str:
    image = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle(
        [
            round(box[0] / 10),
            round(box[1] / 10),
            max(round(box[0] / 10), round(box[2] / 10) - 1),
            max(round(box[1] / 10), round(box[3] / 10) - 1),
        ],
        fill=(22, 215, 233, 130),
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class _Vision:
    provider = "qwen"
    model = "qwen3-vl-flash"

    def __init__(self, result: dict) -> None:
        self.result = result
        self.last_images: list[str] = []
        self.last_prompt = ""

    def chat_structured(self, *, prompt, schema, images_base64, max_tokens):
        self.last_images = images_base64
        self.last_prompt = prompt
        return self.result


class _Tracker:
    def __init__(self, fail_component: str | None = None) -> None:
        self.fail_component = fail_component
        self.sessions: dict[str, str] = {}
        self.closed: list[str] = []

    def start(self, image_bytes, component_id, bbox_0_1000, guidance_target):
        session_id = uuid.uuid4().hex
        self.sessions[session_id] = component_id
        failed = component_id == self.fail_component
        tracked = TrackedComponent(
            component_id=component_id,
            status="lost" if failed else "tracking",
            quality=0.0 if failed else 0.95,
            bbox_0_1000=bbox_0_1000,
            polygon_0_1000=[
                [bbox_0_1000[0], bbox_0_1000[1]],
                [bbox_0_1000[2], bbox_0_1000[1]],
                [bbox_0_1000[2], bbox_0_1000[3]],
                [bbox_0_1000[0], bbox_0_1000[3]],
            ],
            centroid_0_1000=[
                (bbox_0_1000[0] + bbox_0_1000[2]) // 2,
                (bbox_0_1000[1] + bbox_0_1000[3]) // 2,
            ],
            overlay_png_base64="" if failed else _overlay(bbox_0_1000),
            provider="fake-sam2+lk",
            requires_redetection=failed,
            mask_quality_passed=not failed,
            mask_quality_reasons=["synthetic failure"] if failed else [],
            mask_area_ratio=0.01,
            prompt_containment=1.0,
        )
        return session_id, tracked

    def close(self, session_id):
        self.closed.append(session_id)
        return self.sessions.pop(session_id, None) is not None


def _p1_result() -> dict:
    return {
        "plate": {
            "present": "yes",
            "aligned": "yes",
            "fully_visible": "yes",
            "bbox_0_1000": [260, 400, 665, 920],
            "target_point_0_1000": [460, 680],
            "confidence": 0.99,
            "visible_evidence": "complete gold plate",
        },
        "anomalies": [
            {
                "anomaly_id": "foreign-1",
                "anomaly_type": "foreign_object",
                "bbox_0_1000": [410, 535, 520, 650],
                "target_point_0_1000": [465, 592],
                "confidence": 0.99,
                "visible_evidence": "orange square block",
                "correction_instruction": "REMOVE FOREIGN OBJECT",
            },
            {
                "anomaly_id": "residue-1",
                "anomaly_type": "residue",
                "bbox_0_1000": [405, 884, 487, 905],
                "target_point_0_1000": [445, 894],
                "confidence": 0.99,
                "visible_evidence": "thin orange strip on lower edge",
                "correction_instruction": "CLEAN BUILD PLATE BEFORE PRINTING",
            },
        ],
        "scene_evidence": "P1 corrective state",
    }


def test_profile_orders_current_clean_then_dirty() -> None:
    vision = _Vision(_p1_result())
    engine = PlateInspectionEngine(vision, _Tracker())
    result = engine.inspect(BuildPlateInspectionRequest(image_base64=_image_base64()))

    assert len(vision.last_images) == 3
    assert "IMAGE 1 is the CURRENT CAMERA FRAME" in vision.last_prompt
    assert "IMAGE 2 is the CLEAN P2" in vision.last_prompt
    assert result.reference_hashes["clean_p2_sha256"]
    assert result.reference_hashes["dirty_p1_sha256"]


def test_p1_keeps_two_separate_anomaly_sessions_and_blocks_printing() -> None:
    engine = PlateInspectionEngine(_Vision(_p1_result()), _Tracker())
    result = engine.inspect(BuildPlateInspectionRequest(image_base64=_image_base64()))

    assert result.status == "corrective_action"
    assert result.safe_to_print is False
    assert result.plate_mask is not None and result.plate_mask.tracking_ready
    assert [item.object_type for item in result.anomalies] == [
        "foreign_object",
        "residue",
    ]
    assert len({item.session_id for item in result.anomalies}) == 2
    predicates = {item.predicate_id: item.passed for item in result.predicates}
    assert predicates == {
        "plate_present": True,
        "plate_aligned": True,
        "surface_clear": False,
        "no_residue": False,
    }


def test_p2_outside_orange_point_is_rejected_and_printing_is_safe() -> None:
    result = _p1_result()
    result["anomalies"] = [
        {
            "anomaly_id": "outside-orange-point",
            "anomaly_type": "residue",
            "bbox_0_1000": [623, 941, 638, 954],
            "target_point_0_1000": [630, 947],
            "confidence": 0.95,
            "visible_evidence": "orange point below plate",
            "correction_instruction": "CLEAN BUILD PLATE BEFORE PRINTING",
        }
    ]
    engine = PlateInspectionEngine(_Vision(result), _Tracker())
    response = engine.inspect(
        BuildPlateInspectionRequest(image_base64=_image_base64(dirty=False))
    )

    assert response.status == "ready"
    assert response.safe_to_print is True
    assert response.anomalies == []
    assert len(response.rejected_candidates) == 1
    assert response.rejected_candidates[0].benign_exclusion is True
    assert "outside" in response.rejected_candidates[0].reason


def test_clean_frame_rejects_dirty_exemplar_coordinate_leakage() -> None:
    result = _p1_result()
    result["anomalies"] = [result["anomalies"][0]]
    engine = PlateInspectionEngine(_Vision(result), _Tracker())
    response = engine.inspect(
        BuildPlateInspectionRequest(image_base64=_image_base64(dirty=False))
    )

    assert response.status == "ready"
    assert response.safe_to_print is True
    assert response.anomalies == []
    assert len(response.rejected_candidates) == 1
    assert response.rejected_candidates[0].benign_exclusion is True
    assert "exemplar-coordinate leakage" in response.rejected_candidates[0].reason


def test_sam_failure_closes_every_session_and_returns_no_stale_overlay() -> None:
    tracker = _Tracker(fail_component="a1_mini_build_plate_residue")
    engine = PlateInspectionEngine(_Vision(_p1_result()), tracker)
    response = engine.inspect(BuildPlateInspectionRequest(image_base64=_image_base64()))

    assert response.status == "uncertain"
    assert response.safe_to_print is False
    assert response.anomalies == []
    assert response.plate_mask is not None
    assert response.plate_mask.session_id is None
    assert response.plate_mask.tracking_ready is False
    assert tracker.sessions == {}


def test_compiler_clips_edge_residue_to_plate() -> None:
    candidate = BuildPlateAnomalyCandidate(
        anomaly_id="edge-strip",
        anomaly_type="residue",
        bbox_0_1000=[400, 885, 485, 930],
        target_point_0_1000=[440, 895],
        confidence=0.9,
        visible_evidence="edge strip",
        correction_instruction="CLEAN BUILD PLATE BEFORE PRINTING",
    )
    compiled, rejected = compile_anomaly_prompt(
        candidate,
        [260, 400, 665, 920],
        PREPRINT_PLATE_INSPECTION_V1,
    )
    assert rejected is None
    assert compiled is not None
    assert compiled.compiled_box_0_1000 == [400, 885, 485, 920]


def test_compiler_accepts_inset_high_confidence_plate_when_qwen_saw_outer_edges() -> None:
    raw = _p1_result()
    raw["plate"]["fully_visible"] = "uncertain"
    raw["plate"]["visible_evidence"] = (
        "straight outer edges and clipped corners are visible; plate sits squarely"
    )
    qwen, audited = _compile_plate_visibility(
        BuildPlateVisionResult.model_validate(raw),
        raw,
        PREPRINT_PLATE_INSPECTION_V1,
    )
    assert qwen.plate.fully_visible == "yes"
    assert audited["_compiled_plate_visibility"]["compiled"] == "yes"


def test_compiler_resolves_inset_geometry_when_qwen_wording_says_cropped() -> None:
    raw = _p1_result()
    raw["plate"].update(
        aligned="uncertain",
        fully_visible="no",
        bbox_0_1000=[89, 354, 512, 974],
        visible_evidence="plate appears partially cut off on the left and bottom",
    )
    qwen, audited = _compile_plate_visibility(
        BuildPlateVisionResult.model_validate(raw),
        raw,
        PREPRINT_PLATE_INSPECTION_V1,
    )
    assert qwen.plate.fully_visible == "yes"
    assert qwen.plate.aligned == "yes"
    assert audited["_compiled_plate_visibility"]["minimum_image_inset_0_1000"] == 26


def test_profile_compiler_recovers_current_frame_lower_edge_residue() -> None:
    current = base64.b64decode(_image_base64(dirty=True))
    candidate = _profile_residue_candidate(
        current,
        [260, 400, 665, 920],
        0,
    )
    assert candidate is not None
    assert candidate.anomaly_type == "residue"
    assert candidate.bbox_0_1000[1] >= 850
    assert candidate.bbox_0_1000[2] - candidate.bbox_0_1000[0] >= 50


def test_compiler_does_not_accept_plate_box_touching_camera_boundary() -> None:
    raw = _p1_result()
    raw["plate"].update(
        fully_visible="uncertain",
        bbox_0_1000=[0, 400, 665, 920],
        visible_evidence="straight outer edges and clipped corners are visible",
    )
    qwen, audited = _compile_plate_visibility(
        BuildPlateVisionResult.model_validate(raw),
        raw,
        PREPRINT_PLATE_INSPECTION_V1,
    )
    assert qwen.plate.fully_visible == "uncertain"
    assert "_compiled_plate_visibility" not in audited
