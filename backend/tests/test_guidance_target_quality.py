from __future__ import annotations

import base64
import io
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from app.manual_service import ManualService
from app.models import (
    EmptySpoolAxleCandidate,
    EmptySpoolAxleLocateRequest,
    GuidanceTarget,
    SemanticComponentCandidate,
)
from app.tracking import OpenCvMaskTracker, _TrackingState


def _jpeg() -> bytes:
    buffer = io.BytesIO()
    image = Image.new("RGB", (200, 140), color=(225, 225, 225))
    for x in range(50, 120):
        for y in range(45, 95):
            image.putpixel((x, y), (60, 60, 60))
    image.save(buffer, "JPEG", quality=95)
    return buffer.getvalue()


def test_mask_is_rejected_when_it_does_not_contain_the_semantic_target_point() -> None:
    tracker = OpenCvMaskTracker()
    session_id, tracked = tracker.start(
        _jpeg(),
        "target:AMS Lite 3号料盘轴",
        [220, 250, 650, 760],
        GuidanceTarget(
            expected_component_id="target:AMS Lite 3号料盘轴",
            semantic_role="target",
            target_slot_id=3,
            render_mode="billboard",
            target_point_0_1000=[950, 50],
            expected_area_ratio_min=0.001,
            expected_area_ratio_max=0.25,
        ),
    )

    assert tracked.mask_quality_passed is False
    assert "target_point_not_inside_mask" in tracked.mask_quality_reasons
    assert tracked.status == "lost"
    assert tracker.close(session_id) is True


def test_hollow_spindle_mask_accepts_nearby_ring_support() -> None:
    mask = np.zeros((200, 200), dtype=np.uint8)
    cv2.circle(mask, (100, 100), 45, 255, thickness=22)
    state = _TrackingState(
        component_id="target:AMS Lite 3号料盘轴总成",
        gray=np.zeros((200, 200), dtype=np.uint8),
        mask=mask,
        points=None,
        prompt_box=(50, 50, 150, 150),
        guidance_target=GuidanceTarget(
            expected_component_id="target:AMS Lite 3号料盘轴总成",
            semantic_role="target",
            target_slot_id=3,
            render_mode="billboard",
            target_point_0_1000=[500, 500],
            expected_area_ratio_min=0.001,
            expected_area_ratio_max=0.25,
        ),
    )

    passed, reasons, _, _ = OpenCvMaskTracker._mask_quality(state)

    assert passed is True
    assert "target_point_not_inside_mask" not in reasons


def test_hollow_spindle_mask_does_not_require_assembly_suffix() -> None:
    mask = np.zeros((200, 200), dtype=np.uint8)
    cv2.circle(mask, (100, 100), 45, 255, thickness=22)
    state = _TrackingState(
        component_id="target:AMS Lite 3号空料盘轴",
        gray=np.zeros((200, 200), dtype=np.uint8),
        mask=mask,
        points=None,
        prompt_box=(50, 50, 150, 150),
        guidance_target=GuidanceTarget(
            expected_component_id="target:AMS Lite 3号空料盘轴",
            semantic_role="target",
            target_slot_id=3,
            render_mode="billboard",
            target_point_0_1000=[500, 500],
            expected_area_ratio_min=0.001,
            expected_area_ratio_max=0.25,
        ),
    )

    passed, reasons, _, _ = OpenCvMaskTracker._mask_quality(state)

    assert passed is True
    assert "target_point_not_inside_mask" not in reasons


def test_slot4_feeder_repair_box_excludes_the_central_support_column() -> None:
    service = ManualService.__new__(ManualService)

    repaired = service._slot4_white_holder_prompt_box([600, 512, 967, 790])

    assert repaired == [590, 162, 807, 362]


def test_slot4_direction_aware_prompt_removes_attachment_column() -> None:
    image = np.full((1000, 1000, 3), 235, dtype=np.uint8)
    # Pale vertical support and a slightly darker right-projecting holder.
    image[20:700, 520:606] = (205, 205, 205)
    image[100:320, 600:720] = (175, 175, 175)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    service = ManualService.__new__(ManualService)
    qwen = EmptySpoolAxleCandidate(
        found=True,
        slot_id=4,
        bbox_0_1000=[530, 60, 720, 320],
        target_point_0_1000=[640, 190],
        confidence=0.95,
        visible_evidence="visible Slot 4 holder",
        extension_direction="right",
    )

    compiled = service._tighten_slot4_current_frame_prompt(
        base64.b64encode(encoded.tobytes()).decode("ascii"),
        qwen,
    )

    assert compiled.bbox_0_1000 is not None
    assert 588 <= compiled.bbox_0_1000[0] <= 608
    assert 82 <= compiled.bbox_0_1000[1] <= 108
    assert compiled.bbox_0_1000[2:] == [720, 320]
    assert "holder extends right" in compiled.visible_evidence


def test_slot4_task_exemplar_compiles_tight_current_frame_holder_prompt() -> None:
    camera_frame = (
        Path.home()
        / "Library"
        / "Application Support"
        / "Unity Technologies"
        / "AR Foundation Samples"
        / "Manual2AR"
        / "Diagnostics"
        / "latest_component_overview_camera.jpg"
    )
    if not camera_frame.exists():
        # CI does not have the physical-camera artifact; local demo validation
        # exercises this branch with the actual Unity evidence frame.
        return
    service = ManualService.__new__(ManualService)
    qwen = EmptySpoolAxleCandidate(
        found=True,
        slot_id=4,
        # Deliberately wrong coarse geometry: the exemplar compiler is the
        # pixel-geometry correction stage and must not be vetoed by this box.
        bbox_0_1000=[800, 40, 985, 260],
        target_point_0_1000=[900, 150],
        confidence=0.90,
        visible_evidence="Qwen located the visible empty Slot 4 holder",
    )

    compiled = service._compile_slot4_holder_from_exemplar(
        base64.b64encode(camera_frame.read_bytes()).decode("ascii"),
        qwen,
    )

    assert compiled is not None
    assert compiled.proposal_source == "qwen_flash_task_profile_exemplar"
    assert compiled.bbox_0_1000 is not None
    assert compiled.bbox_0_1000[2] - compiled.bbox_0_1000[0] < 130
    assert compiled.bbox_0_1000[3] - compiled.bbox_0_1000[1] < 180
    assert compiled.target_point_0_1000 is not None
    assert service._point_patch_is_pale_holder(
        base64.b64encode(camera_frame.read_bytes()).decode("ascii"),
        compiled.target_point_0_1000,
    )


def test_overview_rejects_round_or_edge_spool_as_empty_holder() -> None:
    round_spool = SemanticComponentCandidate(
        component_id="empty_spool_holder",
        found=True,
        bbox_0_1000=[110, 850, 295, 999],
        target_point_0_1000=[200, 920],
        confidence=0.9,
        visible_evidence="white empty holder",
    )
    elongated_holder = SemanticComponentCandidate(
        component_id="empty_spool_holder",
        found=True,
        bbox_0_1000=[130, 150, 390, 270],
        target_point_0_1000=[260, 210],
        confidence=0.9,
        visible_evidence="elongated pale-white trough arm attached to AMS Lite",
    )
    entire_ams_support = SemanticComponentCandidate(
        component_id="empty_spool_holder",
        found=True,
        bbox_0_1000=[27, 689, 832, 885],
        target_point_0_1000=[412, 780],
        confidence=0.9,
        visible_evidence="elongated pale-white structural arm",
    )

    assert ManualService._overview_holder_is_probably_a_spool(round_spool) is True
    assert ManualService._overview_holder_is_probably_a_spool(elongated_holder) is False
    assert ManualService._overview_holder_is_probably_a_spool(entire_ams_support) is True


def test_overview_compiles_pale_holder_prompt_below_qwen_feeder_anchor() -> None:
    image = Image.new("RGB", (1000, 1000), color=(80, 80, 80))
    for x in range(575, 810):
        for y in range(640, 910):
            image.putpixel((x, y), (175, 175, 180))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=95)
    service = ManualService.__new__(ManualService)
    rejected = SemanticComponentCandidate(
        component_id="empty_spool_holder",
        found=True,
        bbox_0_1000=[592, 406, 720, 652],
        target_point_0_1000=[638, 520],
        confidence=0.92,
        visible_evidence="support arm beside the feeder cluster",
    )

    compiled = service._compile_holder_from_feeder_anchor(
        base64.b64encode(buffer.getvalue()).decode("ascii"),
        rejected,
    )

    assert compiled is not None
    assert compiled.bbox_0_1000 == [586, 647, 790, 898]
    assert compiled.target_point_0_1000 == [682, 787]
    assert "target point verified on pale holder plastic" in compiled.visible_evidence


def test_clockwise_holder_retry_maps_back_to_raw_camera_coordinates() -> None:
    rotated = SemanticComponentCandidate(
        component_id="empty_spool_holder",
        found=True,
        bbox_0_1000=[116, 589, 270, 795],
        target_point_0_1000=[180, 660],
        confidence=0.95,
        visible_evidence="attached empty trough arm",
    )

    raw = ManualService._clockwise_candidate_to_original(rotated)

    assert raw.bbox_0_1000 == [589, 730, 795, 884]
    assert raw.target_point_0_1000 == [660, 820]


def test_unity_empty_verified_seed_array_is_treated_as_absent() -> None:
    request = EmptySpoolAxleLocateRequest(
        image_base64="x" * 32,
        preferred_slot_id=4,
        verified_seed_bbox_0_1000=[],
    )

    assert request.verified_seed_bbox_0_1000 is None


def test_overview_boxes_reject_substantial_identity_overlap() -> None:
    assert ManualService._box_overlap_over_smaller(
        [550, 20, 800, 500],
        [600, 40, 760, 420],
    ) > 0.18
    assert ManualService._box_overlap_over_smaller(
        [100, 100, 300, 300],
        [500, 500, 700, 700],
    ) == 0.0


def test_overview_mask_must_remain_inside_immutable_semantic_box() -> None:
    mask = np.zeros((200, 200), dtype=np.uint8)
    mask[20:180, 20:180] = 255
    state = _TrackingState(
        component_id="paper_figure_empty_spool_holder",
        gray=np.zeros((200, 200), dtype=np.uint8),
        mask=mask,
        points=None,
        prompt_box=(60, 60, 140, 140),
        semantic_box=(60, 60, 140, 140),
        guidance_target=GuidanceTarget(
            expected_component_id="paper_figure_empty_spool_holder",
            semantic_role="target",
            render_mode="mask",
            target_point_0_1000=[500, 500],
            expected_area_ratio_min=0.001,
            expected_area_ratio_max=0.90,
        ),
    )

    passed, reasons, _, containment = OpenCvMaskTracker._mask_quality(state)

    assert passed is False
    assert containment < 0.86
    assert "overview_mask_leaves_semantic_box" in reasons


def test_slot4_mask_cannot_leak_far_outside_task_profile_box() -> None:
    mask = np.zeros((200, 200), dtype=np.uint8)
    mask[20:180, 20:180] = 255
    state = _TrackingState(
        component_id="ams_lite_empty_spool_spindle",
        gray=np.zeros((200, 200), dtype=np.uint8),
        mask=mask,
        points=None,
        prompt_box=(60, 60, 140, 140),
        semantic_box=(60, 60, 140, 140),
        guidance_target=GuidanceTarget(
            expected_component_id="ams_lite_empty_spool_spindle",
            semantic_role="target",
            target_slot_id=4,
            render_mode="mask",
            target_point_0_1000=[500, 500],
            expected_area_ratio_min=0.001,
            expected_area_ratio_max=0.08,
        ),
    )

    passed, reasons, _, containment = OpenCvMaskTracker._mask_quality(state)

    assert passed is False
    assert containment < 0.90
    assert "slot4_mask_leaves_semantic_box" in reasons


def test_overview_small_ransac_motion_can_refresh_current_frame_contract() -> None:
    previous = np.zeros((200, 300), dtype=np.uint8)
    previous[60:120, 80:160] = 255
    current = np.zeros_like(previous)
    current[64:124, 87:167] = 255

    assert OpenCvMaskTracker._overview_motion_is_plausible(
        previous,
        current,
        current.shape,
        quality=0.62,
    ) is True


def test_overview_large_jump_cannot_refresh_current_frame_contract() -> None:
    previous = np.zeros((200, 300), dtype=np.uint8)
    previous[60:120, 20:100] = 255
    current = np.zeros_like(previous)
    current[60:120, 200:280] = 255

    assert OpenCvMaskTracker._overview_motion_is_plausible(
        previous,
        current,
        current.shape,
        quality=0.95,
    ) is False


def test_overview_holder_exemplar_compiles_reference_frame_prompt() -> None:
    from app.manual_service import OVERVIEW_HOLDER_EXEMPLAR_PATH

    encoded = base64.b64encode(OVERVIEW_HOLDER_EXEMPLAR_PATH.read_bytes()).decode()
    candidate = ManualService._compile_overview_holder_from_exemplar(
        ManualService.__new__(ManualService),
        encoded,
    )

    assert candidate is not None
    assert candidate.found is True
    assert candidate.bbox_0_1000 is not None
    assert candidate.target_point_0_1000 is not None
    assert "SIFT/RANSAC" in candidate.visible_evidence
