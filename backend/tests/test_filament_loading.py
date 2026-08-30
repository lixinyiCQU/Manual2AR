from __future__ import annotations

import base64
import io
import uuid

import cv2
import numpy as np
from PIL import Image, ImageDraw

from app.filament_loading import (
    FilamentLoadingEngine,
    _loose_tip_is_distinct_from_inserted,
)
from app.models import FilamentLoadingInspectionRequest, TrackedComponent
from app.tracking import OpenCvMaskTracker


def _image_base64() -> str:
    image = Image.new("RGB", (200, 160), (218, 218, 218))
    draw = ImageDraw.Draw(image)
    draw.rectangle((68, 104, 82, 122), fill=(242, 91, 20))
    draw.rectangle((40, 14, 58, 43), fill=(220, 80, 26))
    draw.rectangle((112, 116, 127, 137), fill=(242, 91, 20))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _overlay(box: list[int]) -> str:
    image = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle(
        (
            round(box[0] / 10),
            round(box[1] / 10),
            max(round(box[0] / 10), round(box[2] / 10) - 1),
            max(round(box[1] / 10), round(box[3] / 10) - 1),
        ),
        fill=(10, 225, 245, 150),
    )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class _Vision:
    provider = "qwen"
    model = "qwen3-vl-flash"

    def __init__(self, result: dict) -> None:
        self.result = result
        self.images = []
        self.prompt = ""
        self.prompts = []

    def chat_structured(self, *, prompt, schema, images_base64, max_tokens):
        self.images = images_base64
        self.prompt = prompt
        self.prompts.append(prompt)
        if "LOOSE-TIP OVERRIDE CHECK" in prompt:
            return {
                "loose_tip_visible": "no",
                "bbox_0_1000": None,
                "target_point_0_1000": None,
                "confidence": 0.9,
                "visible_evidence": "no loose tip in synthetic loaded frame",
            }
        if "CONNECTION-STATE TIE-BREAK VERIFICATION" in prompt:
            return _connection_check("uncertain")
        return self.result


class _VisionWithFocusedLooseTip(_Vision):
    def chat_structured(self, *, prompt, schema, images_base64, max_tokens):
        self.images = images_base64
        self.prompt = prompt
        self.prompts.append(prompt)
        if "LOOSE-TIP OVERRIDE CHECK" in prompt:
            return {
                "loose_tip_visible": "yes",
                "bbox_0_1000": [350, 570, 450, 730],
                "target_point_0_1000": [400, 650],
                "confidence": 0.95,
                "visible_evidence": "orange free endpoint in focused lower-feeder crop",
            }
        if "CONNECTION-STATE TIE-BREAK VERIFICATION" in prompt:
            return _connection_check("uncertain")
        return self.result


class _VisionWithLoadedTieBreak(_Vision):
    def chat_structured(self, *, prompt, schema, images_base64, max_tokens):
        self.images = images_base64
        self.prompt = prompt
        self.prompts.append(prompt)
        if "CONNECTION-STATE TIE-BREAK VERIFICATION" in prompt:
            return _connection_check("loaded")
        return self.result


class _Tracker:
    def __init__(self, fail_type: str | None = None) -> None:
        self.fail_type = fail_type
        self.sessions: dict[str, str] = {}

    def start(self, image_bytes, component_id, bbox_0_1000, guidance_target):
        session_id = uuid.uuid4().hex
        failed = self.fail_type is not None and component_id.endswith(self.fail_type)
        self.sessions[session_id] = component_id
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
        return self.sessions.pop(session_id, None) is not None


def _region(visible, box=None, point=None, confidence=0.95, evidence="visible"):
    return {
        "visible": visible,
        "bbox_0_1000": box,
        "target_point_0_1000": point,
        "confidence": confidence,
        "visible_evidence": evidence,
    }


def _connection_check(state: str) -> dict:
    loaded = state == "loaded"
    return {
        "connection_state": state,
        "confidence": 0.95 if loaded else 0.45,
        "feeder_module": _region("yes", [41, 200, 450, 700], [245, 450]),
        # These are crop coordinates. With the synthetic feeder crop they map
        # back onto the two orange proof regions in _image_base64.
        "inserted_filament_at_inlet": _region(
            "yes" if loaded else "uncertain",
            [320, 640, 420, 770] if loaded else None,
            [370, 700] if loaded else None,
            confidence=0.95 if loaded else 0.3,
        ),
        "filament_visible_in_ptfe": _region(
            "yes" if loaded else "uncertain",
            [321, 87, 536, 269] if loaded else None,
            [430, 170] if loaded else None,
            confidence=0.92 if loaded else 0.3,
        ),
        "free_filament_cut_end": _region(
            "no" if loaded else "uncertain",
            confidence=0.95 if loaded else 0.3,
        ),
        "evidence": "two current-frame connection proofs" if loaded else "ambiguous",
    }


def _loaded_result() -> dict:
    return {
        "proposed_state": "loaded",
        "state_confidence": 0.95,
        "feeder_module": _region("yes", [100, 200, 450, 700], [275, 450]),
        "filament_inlet": _region("yes", [335, 640, 420, 750], [375, 690]),
        "loose_filament_tip": _region("no", confidence=0.90),
        "inserted_filament_at_inlet": _region(
            "yes", [335, 640, 420, 750], [375, 690]
        ),
        "filament_visible_in_ptfe": _region(
            "yes", [190, 70, 300, 290], [245, 160]
        ),
        "scene_evidence": "orange filament enters inlet and continues in PTFE",
    }


def _not_inserted_result() -> dict:
    result = _loaded_result()
    result.update(
        proposed_state="not_inserted",
        loose_filament_tip=_region("yes", [550, 720, 640, 860], [600, 800]),
        inserted_filament_at_inlet=_region("no", confidence=0.93),
        filament_visible_in_ptfe=_region("no", confidence=0.91),
        scene_evidence="loose tip is outside the inlet",
    )
    return result


def test_profile_orders_current_loaded_then_not_inserted() -> None:
    vision = _Vision(_loaded_result())
    response = FilamentLoadingEngine(vision, _Tracker()).inspect(
        FilamentLoadingInspectionRequest(image_base64=_image_base64())
    )
    assert len(vision.images) == 3
    assert "IMAGE 1 is the CURRENT CAMERA FRAME" in vision.prompts[0]
    assert all("LOOSE-TIP OVERRIDE CHECK" not in prompt for prompt in vision.prompts)
    assert response.reference_hashes["loaded_sha256"]
    assert response.reference_hashes["not_inserted_sha256"]


def test_loaded_requires_two_direct_predicates_and_tracks_visible_entry() -> None:
    response = FilamentLoadingEngine(_Vision(_loaded_result()), _Tracker()).inspect(
        FilamentLoadingInspectionRequest(image_base64=_image_base64())
    )
    assert response.status == "loaded"
    assert [mask.object_type for mask in response.masks] == [
        "feeder_module",
        "inserted_filament",
    ]
    assert len({mask.session_id for mask in response.masks}) == 2
    predicates = {item.predicate_id: item.passed for item in response.predicates}
    assert predicates["filament_entered_feeder"] is True
    assert predicates["filament_visible_in_ptfe"] is True


def test_missing_qwen_region_point_is_compiled_from_its_current_frame_box() -> None:
    result = _loaded_result()
    result["feeder_module"] = _region("yes", [100, 200, 450, 700], None)
    response = FilamentLoadingEngine(_Vision(result), _Tracker()).inspect(
        FilamentLoadingInspectionRequest(image_base64=_image_base64())
    )
    assert response.status == "loaded"
    assert response.feeder_module.target_point_0_1000 == [275, 450]
    assert response.qwen_raw["_compiled_geometry_repairs"] == [
        {"region": "feeder_module", "compiled_point_0_1000": [275, 450]}
    ]


def test_feeder_sam_point_uses_stable_semantic_box_center() -> None:
    result = _loaded_result()
    result["feeder_module"] = _region("yes", [100, 200, 450, 700], [120, 220])
    response = FilamentLoadingEngine(_Vision(result), _Tracker()).inspect(
        FilamentLoadingInspectionRequest(image_base64=_image_base64())
    )
    feeder_mask = next(mask for mask in response.masks if mask.object_type == "feeder_module")
    assert feeder_mask.target_point_0_1000 == [275, 450]


def test_not_inserted_tracks_feeder_and_tip_and_guides_upward() -> None:
    response = FilamentLoadingEngine(
        _Vision(_not_inserted_result()), _Tracker()
    ).inspect(FilamentLoadingInspectionRequest(image_base64=_image_base64()))
    assert response.status == "not_inserted"
    assert response.primary_instruction == "INSERT FILAMENT UPWARD"
    assert [mask.object_type for mask in response.masks] == [
        "feeder_module",
        "filament_tip",
    ]
    assert len({mask.session_id for mask in response.masks}) == 2
    assert response.filament_inlet.target_point_0_1000 == [450, 700]
    assert "SAM feeder surface boundary" in response.filament_inlet.visible_evidence


def test_not_inserted_compiles_inlet_anchor_when_hole_is_occluded() -> None:
    result = _not_inserted_result()
    result["filament_inlet"] = _region(
        "no",
        confidence=0.0,
        evidence="physical opening is occluded by the diagonal housing",
    )
    response = FilamentLoadingEngine(_Vision(result), _Tracker()).inspect(
        FilamentLoadingInspectionRequest(image_base64=_image_base64())
    )
    assert response.status == "not_inserted"
    assert [mask.object_type for mask in response.masks] == [
        "feeder_module",
        "filament_tip",
    ]
    assert response.filament_inlet.target_point_0_1000 == [450, 700]
    predicates = {item.predicate_id: item for item in response.predicates}
    assert predicates["inlet_visible"].passed is True
    assert "compiled from the tracked feeder surface" in predicates["inlet_visible"].evidence


def test_uncertain_wide_pass_uses_verified_focused_tip_for_guidance() -> None:
    result = _not_inserted_result()
    result.update(
        proposed_state="uncertain",
        state_confidence=0.45,
        loose_filament_tip=_region("uncertain", confidence=0.35),
        inserted_filament_at_inlet=_region("uncertain", confidence=0.35),
        filament_visible_in_ptfe=_region("uncertain", confidence=0.35),
        scene_evidence="diagonal distant view is ambiguous in the broad pass",
    )

    response = FilamentLoadingEngine(
        _VisionWithFocusedLooseTip(result),
        _Tracker(),
    ).inspect(FilamentLoadingInspectionRequest(image_base64=_image_base64()))

    assert response.status == "not_inserted"
    assert response.primary_instruction == "INSERT FILAMENT UPWARD"
    assert [mask.object_type for mask in response.masks] == [
        "feeder_module",
        "filament_tip",
    ]
    assert response.qwen_raw["_compiled_state_override"]["state"] == "not_inserted"


def test_invalid_loose_tip_recovers_loaded_from_two_connection_proofs() -> None:
    result = _not_inserted_result()
    result["loose_filament_tip"] = _region(
        "yes",
        [800, 800, 850, 850],
        [825, 825],
        evidence="false blank-background endpoint",
    )
    response = FilamentLoadingEngine(
        _VisionWithLoadedTieBreak(result),
        _Tracker(),
    ).inspect(FilamentLoadingInspectionRequest(image_base64=_image_base64()))

    assert response.status == "loaded"
    assert response.qwen_raw["_loose_tip_quality_gate"]["passed"] is False
    assert response.qwen_raw["_connection_state_tiebreak"][
        "loaded_proof_passed"
    ] is True


def test_filament_refinement_keeps_orange_line_not_full_sam_patch() -> None:
    image = np.full((160, 220, 3), 210, dtype=np.uint8)
    cv2.line(image, (96, 72), (124, 112), (18, 88, 242), thickness=4)
    candidate = np.zeros(image.shape[:2], dtype=np.uint8)
    candidate[45:140, 55:175] = 255
    refined = OpenCvMaskTracker._refine_filament_mask(
        image,
        "ams_lite_filament_tip",
        (55, 45, 175, 140),
        candidate_mask=candidate,
        target_point_0_1000=[450, 500],
    )
    refined_area = cv2.countNonZero(refined)
    assert 40 < refined_area < cv2.countNonZero(candidate) * 0.10
    x, y, width, height = cv2.boundingRect(refined)
    assert x >= 90 and y >= 66
    assert x + width <= 130 and y + height <= 118


def test_loose_tip_override_rejects_same_region_as_inserted_segment() -> None:
    inserted = _region("yes", [392, 632, 492, 755], [425, 685])
    overlapping_tip = _region("yes", [349, 667, 596, 888], [358, 695])
    distinct_tip = _region("yes", [380, 627, 509, 716], [400, 650])
    from app.models import FilamentRegionObservation

    inserted_model = FilamentRegionObservation.model_validate(inserted)
    assert not _loose_tip_is_distinct_from_inserted(
        FilamentRegionObservation.model_validate(overlapping_tip),
        inserted_model,
    )
    assert _loose_tip_is_distinct_from_inserted(
        FilamentRegionObservation.model_validate(distinct_tip),
        FilamentRegionObservation.model_validate(
            _region("yes", [384, 322, 468, 484], [420, 380])
        ),
    )


def test_spool_mounted_without_ptfe_evidence_is_uncertain() -> None:
    result = _loaded_result()
    result["filament_visible_in_ptfe"] = _region("no", confidence=0.90)
    tracker = _Tracker()
    response = FilamentLoadingEngine(_Vision(result), tracker).inspect(
        FilamentLoadingInspectionRequest(image_base64=_image_base64())
    )
    assert response.status == "uncertain"
    assert response.masks == []
    assert tracker.sessions == {}


def test_any_mask_failure_closes_all_sessions_and_returns_no_stale_overlay() -> None:
    tracker = _Tracker(fail_type="inserted_filament")
    response = FilamentLoadingEngine(_Vision(_loaded_result()), tracker).inspect(
        FilamentLoadingInspectionRequest(image_base64=_image_base64())
    )
    assert response.status == "uncertain"
    assert response.masks == []
    assert tracker.sessions == {}
