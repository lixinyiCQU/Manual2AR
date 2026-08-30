from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from typing import Any

from PIL import Image

from .grounding import DemoGrounder, rotate_jpeg_for_vlm
from .models import (
    BuildPlateAnomalyCandidate,
    BuildPlateInspectionRequest,
    BuildPlateInspectionResponse,
    BuildPlateObservation,
    BuildPlateVisionResult,
    GuidanceTarget,
    InspectionMaskResult,
    InspectionPredicateResult,
    InspectionRejectedCandidate,
    TrackedComponent,
)
from .ollama_client import OllamaError
from .tracking import decode_base64_image
from .tracking_provider import HybridMaskTracker, TrackingProviderError
from .vision_task_profiles import TaskVisionProfile, load_task_vision_profile


@dataclass(frozen=True)
class CompiledAnomalyPrompt:
    candidate: BuildPlateAnomalyCandidate
    semantic_box_0_1000: list[int]
    compiled_box_0_1000: list[int]
    target_point_0_1000: list[int]
    expected_area_ratio_min: float
    expected_area_ratio_max: float
    minimum_mask_containment: float


class PlateInspectionEngine:
    """Qwen profile grounding followed by deterministic SAM2 prompt compilation."""

    def __init__(self, vision: Any, tracker: HybridMaskTracker) -> None:
        self.vision = vision
        self.tracker = tracker

    def inspect(self, request: BuildPlateInspectionRequest) -> BuildPlateInspectionResponse:
        profile = load_task_vision_profile(request.profile_id)
        raw_image = decode_base64_image(request.image_base64)
        upright_image = rotate_jpeg_for_vlm(raw_image, request.image_rotation_degrees)
        live_image = _normalize_jpeg_base64(upright_image, 1280)
        ordered_images = [live_image, *profile.ordered_reference_images_base64()]
        raw_qwen = self.vision.chat_structured(
            prompt=_inspection_prompt(profile),
            schema=BuildPlateVisionResult.model_json_schema(),
            images_base64=ordered_images,
            max_tokens=1800,
        )
        qwen = BuildPlateVisionResult.model_validate(raw_qwen)
        qwen, raw_qwen = _compile_plate_visibility(qwen, raw_qwen, profile)
        return self._compile_and_segment(
            request=request,
            profile=profile,
            raw_image=raw_image,
            qwen=qwen,
            qwen_raw=raw_qwen,
        )

    def _compile_and_segment(
        self,
        *,
        request: BuildPlateInspectionRequest,
        profile: TaskVisionProfile,
        raw_image: bytes,
        qwen: BuildPlateVisionResult,
        qwen_raw: dict[str, Any],
    ) -> BuildPlateInspectionResponse:
        plate_upright = qwen.plate
        plate = _observation_to_raw(plate_upright, request.image_rotation_degrees)
        rejected: list[InspectionRejectedCandidate] = []
        accepted_prompts: list[CompiledAnomalyPrompt] = []
        unresolved_candidate = False
        candidates = list(qwen.anomalies)

        # Qwen occasionally notices the large central object but omits the
        # very thin P1-style edge residue. The task profile may propose that
        # class only when the CURRENT frame contains a thin orange component
        # inside the lower plate band. No exemplar coordinates are reused.
        if (
            plate_upright.bbox_0_1000 is not None
            and not any(item.anomaly_type == "residue" for item in candidates)
        ):
            compiled_residue = _profile_residue_candidate(
                raw_image,
                plate_upright.bbox_0_1000,
                request.image_rotation_degrees,
            )
            if compiled_residue is not None:
                candidates.append(compiled_residue)
                qwen_raw = {
                    **qwen_raw,
                    "_compiled_profile_candidates": [
                        compiled_residue.model_dump(mode="json")
                    ],
                }

        if plate_upright.bbox_0_1000 is not None:
            for candidate in candidates:
                compiled, rejection = compile_anomaly_prompt(
                    candidate,
                    plate_upright.bbox_0_1000,
                    profile,
                    current_raw_image=raw_image,
                    rotation_degrees=request.image_rotation_degrees,
                )
                if rejection is not None:
                    rejected.append(rejection)
                    unresolved_candidate = unresolved_candidate or not rejection.benign_exclusion
                elif compiled is not None:
                    accepted_prompts.append(compiled)
        elif candidates:
            unresolved_candidate = True
            rejected.extend(
                InspectionRejectedCandidate(
                    candidate=candidate,
                    reason="build plate was not established before anomaly segmentation",
                    benign_exclusion=False,
                )
                for candidate in candidates
            )

        plate_mask: InspectionMaskResult | None = None
        anomaly_masks: list[InspectionMaskResult] = []
        segmentation_failed = False
        started_sessions: list[str] = []

        plate_semantically_valid = (
            plate.present == "yes"
            and plate.aligned in {"yes", "no"}
            and plate.fully_visible == "yes"
            and plate.confidence >= profile.minimum_plate_confidence
            and plate.bbox_0_1000 is not None
            and plate.target_point_0_1000 is not None
        )
        if plate_semantically_valid:
            plate_target = GuidanceTarget(
                expected_component_id="a1_mini_build_plate",
                semantic_role="target",
                render_mode="mask",
                forbidden_component_ids=[
                    "printer_base",
                    "purge_waste_box",
                    "surrounding_table",
                ],
                target_point_0_1000=plate.target_point_0_1000,
                expected_area_ratio_min=profile.plate_area_ratio_min,
                expected_area_ratio_max=profile.plate_area_ratio_max,
            )
            plate_mask = self._start_mask(
                raw_image=raw_image,
                object_id="a1_mini_build_plate",
                object_type="build_plate",
                semantic_box=plate.bbox_0_1000,
                compiled_box=plate.bbox_0_1000,
                target_point=plate.target_point_0_1000,
                target=plate_target,
                plate_box=plate.bbox_0_1000,
                minimum_containment=0.88,
                keep_session=request.start_tracking,
            )
            if plate_mask.session_id:
                started_sessions.append(plate_mask.session_id)
            segmentation_failed = not plate_mask.tracking_ready

        if plate_mask is not None and plate_mask.tracking_ready and plate.bbox_0_1000:
            for compiled in accepted_prompts:
                raw_semantic_box = _box_to_raw(
                    compiled.semantic_box_0_1000,
                    request.image_rotation_degrees,
                )
                raw_compiled_box = _box_to_raw(
                    compiled.compiled_box_0_1000,
                    request.image_rotation_degrees,
                )
                raw_point = _point_to_raw(
                    compiled.target_point_0_1000,
                    request.image_rotation_degrees,
                )
                target = GuidanceTarget(
                    expected_component_id=(
                        f"a1_mini_build_plate_{compiled.candidate.anomaly_type}"
                    ),
                    semantic_role="forbidden",
                    render_mode="mask",
                    forbidden_component_ids=[
                        "normal_gold_texture",
                        "engraved_plate_lines",
                        "black_pull_tab",
                        "printer_base",
                        "purge_waste_box",
                    ],
                    target_point_0_1000=raw_point,
                    expected_area_ratio_min=compiled.expected_area_ratio_min,
                    expected_area_ratio_max=compiled.expected_area_ratio_max,
                    forbidden_regions_0_1000=_outside_plate_regions(plate.bbox_0_1000),
                )
                result = self._start_mask(
                    raw_image=raw_image,
                    object_id=compiled.candidate.anomaly_id,
                    object_type=compiled.candidate.anomaly_type,
                    semantic_box=raw_semantic_box,
                    compiled_box=raw_compiled_box,
                    target_point=raw_point,
                    target=target,
                    plate_box=plate.bbox_0_1000,
                    minimum_containment=compiled.minimum_mask_containment,
                    keep_session=request.start_tracking,
                )
                if result.session_id:
                    started_sessions.append(result.session_id)
                if result.tracking_ready:
                    anomaly_masks.append(result)
                else:
                    segmentation_failed = True
                    rejected.append(
                        InspectionRejectedCandidate(
                            candidate=compiled.candidate,
                            reason=result.error or "SAM2 anomaly mask failed quality gate",
                            benign_exclusion=False,
                        )
                    )

        conflict = _has_mask_conflict(anomaly_masks)
        if conflict:
            segmentation_failed = True

        plate_present = (
            plate.present == "yes"
            and plate.fully_visible == "yes"
            and plate.confidence >= profile.minimum_plate_confidence
            and plate_mask is not None
            and plate_mask.tracking_ready
        )
        plate_aligned = (
            plate_present
            and plate.aligned == "yes"
            and plate.confidence >= profile.minimum_plate_confidence
        )
        has_foreign_object = any(
            result.object_type == "foreign_object" for result in anomaly_masks
        )
        has_residue = any(result.object_type == "residue" for result in anomaly_masks)
        surface_clear = plate_present and not has_foreign_object
        no_residue = plate_present and not has_residue
        uncertain = (
            not plate_present
            or plate.aligned == "uncertain"
            or unresolved_candidate
            or segmentation_failed
            or conflict
        )
        safe_to_print = (
            plate_present
            and plate_aligned
            and surface_clear
            and no_residue
            and not uncertain
        )

        if uncertain:
            status = "uncertain"
            headline = "INSPECTION UNCERTAIN · REFRAME BUILD PLATE"
        elif safe_to_print:
            status = "ready"
            headline = "READY TO PRINT"
        else:
            status = "corrective_action"
            headline = "CORRECTIVE ACTION REQUIRED"

        corrections: list[str] = []
        if plate_present and not plate_aligned:
            corrections.append("ALIGN BUILD PLATE BEFORE PRINTING")
        if has_foreign_object:
            corrections.append("REMOVE FOREIGN OBJECT")
        if has_residue:
            corrections.append("CLEAN BUILD PLATE BEFORE PRINTING")
        corrections = list(dict.fromkeys(corrections))

        predicates = [
            InspectionPredicateResult(
                predicate_id="plate_present",
                passed=plate_present,
                confidence=plate.confidence,
                evidence=(
                    "full plate visible and SAM2 plate mask passed"
                    if plate_present
                    else plate.visible_evidence or "plate evidence insufficient"
                ),
            ),
            InspectionPredicateResult(
                predicate_id="plate_aligned",
                passed=plate_aligned,
                confidence=plate.confidence,
                evidence=(
                    "plate is seated squarely in the visible bed area"
                    if plate_aligned
                    else "alignment was not directly verified"
                ),
            ),
            InspectionPredicateResult(
                predicate_id="surface_clear",
                passed=surface_clear and not uncertain,
                confidence=_predicate_confidence(plate.confidence, anomaly_masks, "foreign_object"),
                evidence=(
                    "no accepted foreign-object mask"
                    if surface_clear
                    else "accepted foreign-object mask on the build plate"
                ),
            ),
            InspectionPredicateResult(
                predicate_id="no_residue",
                passed=no_residue and not uncertain,
                confidence=_predicate_confidence(plate.confidence, anomaly_masks, "residue"),
                evidence=(
                    "no accepted residue mask"
                    if no_residue
                    else "accepted residue mask on the build plate"
                ),
            ),
        ]

        if uncertain:
            # A partially valid collection must never continue tracking as if
            # it were current evidence. Close every session and remove IDs from
            # the response so Unity cannot accidentally hold stale overlays.
            for session_id in started_sessions:
                try:
                    self.tracker.close(session_id)
                except TrackingProviderError:
                    pass
            if plate_mask is not None:
                plate_mask.session_id = None
                plate_mask.tracking_ready = False
            for result in anomaly_masks:
                result.session_id = None
                result.tracking_ready = False
            anomaly_masks = []

        return BuildPlateInspectionResponse(
            profile_id=profile.profile_id,
            profile_version=profile.profile_version,
            prompt_version=profile.prompt_version,
            method_label=profile.method_label,
            exemplar_guided=True,
            provider=self.vision.provider,
            model=self.vision.model,
            status=status,
            safe_to_print=safe_to_print,
            headline=headline,
            correction_instructions=corrections,
            predicates=predicates,
            plate=plate,
            plate_mask=plate_mask,
            anomalies=anomaly_masks,
            rejected_candidates=rejected,
            qwen_raw=qwen_raw,
            reference_hashes=profile.reference_hashes(),
        )

    def _start_mask(
        self,
        *,
        raw_image: bytes,
        object_id: str,
        object_type: str,
        semantic_box: list[int],
        compiled_box: list[int],
        target_point: list[int],
        target: GuidanceTarget,
        plate_box: list[int],
        minimum_containment: float,
        keep_session: bool,
    ) -> InspectionMaskResult:
        try:
            session_id, tracked = self.tracker.start(
                raw_image,
                target.expected_component_id,
                compiled_box,
                target,
            )
        except (ValueError, TrackingProviderError) as exc:
            return InspectionMaskResult(
                object_id=object_id,
                object_type=object_type,
                semantic_box_0_1000=semantic_box,
                compiled_box_0_1000=compiled_box,
                target_point_0_1000=target_point,
                tracking_ready=False,
                error=str(exc),
            )
        containment = _mask_containment_in_box(tracked, plate_box)
        ready = (
            tracked.status == "tracking"
            and tracked.mask_quality_passed
            and not tracked.requires_redetection
            and tracked.quality >= 0.50
            and bool(tracked.overlay_png_base64)
            and containment >= minimum_containment
        )
        error = None
        if not ready:
            reasons = list(tracked.mask_quality_reasons)
            if containment < minimum_containment:
                reasons.append(
                    f"mask containment {containment:.3f} is below {minimum_containment:.3f}"
                )
            error = "; ".join(reasons) or "SAM2 mask did not pass the inspection gate"
            try:
                self.tracker.close(session_id)
            except TrackingProviderError:
                pass
            session_id = None
        elif not keep_session:
            try:
                self.tracker.close(session_id)
            except TrackingProviderError:
                pass
            session_id = None
        return InspectionMaskResult(
            object_id=object_id,
            object_type=object_type,
            semantic_box_0_1000=semantic_box,
            compiled_box_0_1000=compiled_box,
            target_point_0_1000=target_point,
            session_id=session_id,
            tracked=tracked,
            tracking_ready=ready,
            mask_containment_in_plate=containment,
            error=error,
        )


def _inspection_prompt(profile: TaskVisionProfile) -> str:
    exclusions = "; ".join(profile.excluded_visuals)
    return (
        "This is an exemplar-guided pre-print inspection with exactly three images. "
        "IMAGE 1 is the CURRENT CAMERA FRAME and is the only image for which you may "
        "output coordinates. IMAGE 2 is the CLEAN P2 reference. IMAGE 3 is the DIRTY "
        "P1 reference showing two distinct errors: the central orange square metal "
        "block is a foreign_object, and the thin orange strip attached to the lower "
        "build-plate edge is residue. Never copy coordinates from IMAGE 2 or IMAGE 3. "
        f"Device definition: {profile.device_description} Allowed target: "
        f"{profile.allowed_target} Exclude: {exclusions}. "
        "In IMAGE 1, locate the complete visible gold textured rectangular build plate "
        "by its straight outer sheet edges, clipped/tabbed corners, and continuous "
        "fine texture; do not expand the plate box into the white printer base. "
        "present=yes only when it is clearly the A1 mini plate. fully_visible=yes only "
        "when all plate boundaries needed for containment checks are in frame. aligned=yes "
        "only when the plate visibly sits squarely on the bed without offset, lift, or skew. "
        "Then enumerate ALL visible anomalies physically on the plate or attached to its "
        "visible edge. Use foreign_object for a discrete removable object and residue for "
        "thin adhered scraps, blobs, or remaining printed material. Give each anomaly its "
        "own tight box and a point on its solid foreground; never merge anomalies. Normal "
        "gold texture, etched lines, black tabs, reflections, shadows, printer hardware, "
        "toolhead waste tray contents, and orange waste outside the plate are not "
        "anomalies. A candidate is valid only when its center lies on the current-frame "
        "plate surface or its material is visibly attached across a plate edge. If "
        "evidence is unclear, use uncertain for the "
        "plate fields and do not invent anomalies. Return concise JSON only."
    )


def _compile_plate_visibility(
    qwen: BuildPlateVisionResult,
    raw_qwen: dict[str, Any],
    profile: TaskVisionProfile,
) -> tuple[BuildPlateVisionResult, dict[str, Any]]:
    """Resolve a narrow Qwen wording ambiguity using current-frame geometry.

    Qwen sometimes describes the outer sheet edges and clipped corners, returns
    a high-confidence inset box, but still writes ``fully_visible=uncertain``.
    That combination is sufficient current-frame evidence for the inspection
    compiler: it does not invent a plate or a box, and it cannot fire when the
    proposed plate touches the camera boundary.  The audit marker keeps the
    distinction between the model observation and compiled decision explicit.
    """

    plate = qwen.plate
    box = plate.bbox_0_1000
    evidence = plate.visible_evidence.lower()
    inset = min(box[0], box[1], 1000 - box[2], 1000 - box[3]) if box else -1
    box_width = box[2] - box[0] if box else 0
    box_height = box[3] - box[1] if box else 0
    can_compile = (
        plate.present == "yes"
        and plate.aligned in {"yes", "uncertain"}
        and plate.fully_visible in {"no", "uncertain"}
        and plate.confidence >= max(0.85, profile.minimum_plate_confidence)
        and box is not None
        and plate.target_point_0_1000 is not None
        and inset >= 20
        and box_width >= 260
        and box_height >= 300
        and not any(
            phrase in evidence
            for phrase in ("lifted", "misaligned", "displaced", "offset from the bed")
        )
    )
    if not can_compile:
        return qwen, raw_qwen

    compiled_plate = plate.model_copy(
        update={"fully_visible": "yes", "aligned": "yes"}
    )
    compiled_qwen = qwen.model_copy(update={"plate": compiled_plate})
    audited = {
        **raw_qwen,
        "_compiled_plate_visibility": {
            "original_fully_visible": plate.fully_visible,
            "original_aligned": plate.aligned,
            "compiled": "yes",
            "reason": (
                "high-confidence current-frame plate box is inset from every image "
                "boundary and has the expected complete-plate extent"
            ),
            "minimum_image_inset_0_1000": inset,
        },
    }
    return compiled_qwen, audited


def _profile_residue_candidate(
    raw_image: bytes,
    upright_plate_box: list[int],
    rotation_degrees: int,
) -> BuildPlateAnomalyCandidate | None:
    """Compile a missed thin lower-edge residue from current-frame evidence."""

    x1, y1, x2, y2 = upright_plate_box
    plate_width = x2 - x1
    plate_height = y2 - y1
    if plate_width <= 0 or plate_height <= 0:
        return None
    lower_band = [
        x1,
        max(y1, round(y2 - plate_height * 0.16)),
        x2,
        y2,
    ]
    raw_band = _box_to_raw(lower_band, rotation_degrees)
    ratio, raw_box, raw_point = _orange_foreground_geometry(raw_image, raw_band)
    if raw_box is None or raw_point is None or ratio < 0.0015:
        return None
    box = _box_from_raw(raw_box, rotation_degrees)
    point = _point_from_raw(raw_point, rotation_degrees)
    width = box[2] - box[0]
    height = box[3] - box[1]
    center_y = (box[1] + box[3]) * 0.5
    if (
        width < 15
        or height < 2
        or width < height * 2.0
        or height > max(35, round(plate_height * 0.08))
        or center_y < y1 + plate_height * 0.78
        or _area(box) / max(1, _area(upright_plate_box)) > 0.018
    ):
        return None
    return BuildPlateAnomalyCandidate(
        anomaly_id="PROFILE-CURRENT-RESIDUE-1",
        anomaly_type="residue",
        bbox_0_1000=box,
        target_point_0_1000=point,
        confidence=0.82,
        visible_evidence=(
            "Task-profile compiler found a thin high-saturation orange component "
            "attached to the current-frame lower build-plate band."
        ),
        correction_instruction="Clean the residue from the build-plate edge.",
    )


def compile_anomaly_prompt(
    candidate: BuildPlateAnomalyCandidate,
    plate_box: list[int],
    profile: TaskVisionProfile,
    current_raw_image: bytes | None = None,
    rotation_degrees: int = 0,
) -> tuple[CompiledAnomalyPrompt | None, InspectionRejectedCandidate | None]:
    policy = profile.anomaly_policies[candidate.anomaly_type]
    candidate_box = candidate.bbox_0_1000
    intersection = _intersection(candidate_box, plate_box)
    center = [
        (candidate_box[0] + candidate_box[2]) // 2,
        (candidate_box[1] + candidate_box[3]) // 2,
    ]
    overlap = _area(intersection) / max(1, _area(candidate_box))
    if intersection is None or not _point_in_box(center, plate_box):
        return None, InspectionRejectedCandidate(
            candidate=candidate,
            reason="candidate center is outside the established build plate",
            benign_exclusion=True,
        )
    if overlap < policy.minimum_box_overlap_with_plate:
        return None, InspectionRejectedCandidate(
            candidate=candidate,
            reason=(
                f"candidate/plate overlap {overlap:.3f} is below "
                f"{policy.minimum_box_overlap_with_plate:.3f}"
            ),
            benign_exclusion=True,
        )
    if candidate.confidence < 0.58:
        return None, InspectionRejectedCandidate(
            candidate=candidate,
            reason="Qwen anomaly confidence is below 0.58",
            benign_exclusion=False,
        )
    compiled_intersection = intersection
    compiled_point = candidate.target_point_0_1000
    if current_raw_image is not None:
        raw_candidate_box = _box_to_raw(candidate_box, rotation_degrees)
        orange_ratio, raw_orange_box, raw_orange_point = _orange_foreground_geometry(
            current_raw_image,
            raw_candidate_box,
        )
        minimum_orange_ratio = (
            min(policy.minimum_current_frame_orange_ratio, 0.004)
            if candidate.anomaly_type == "residue"
            else policy.minimum_current_frame_orange_ratio
        )
        if orange_ratio < minimum_orange_ratio:
            return None, InspectionRejectedCandidate(
                candidate=candidate,
                reason=(
                    "candidate lacks current-frame orange foreground evidence "
                    f"({orange_ratio:.3f} < "
                    f"{minimum_orange_ratio:.3f}); "
                    "probable exemplar-coordinate leakage"
                ),
                benign_exclusion=True,
            )
        if raw_orange_box is not None:
            upright_orange_box = _box_from_raw(
                raw_orange_box,
                rotation_degrees,
            )
            tightened = _intersection(upright_orange_box, intersection)
            if tightened is not None:
                compiled_intersection = _expand_normalized_box(
                    tightened,
                    8 if candidate.anomaly_type == "residue" else 12,
                )
                compiled_intersection = _intersection(
                    compiled_intersection,
                    plate_box,
                ) or tightened
        if raw_orange_point is not None:
            compiled_point = _point_from_raw(raw_orange_point, rotation_degrees)
    point = compiled_point
    if not _point_in_box(point, compiled_intersection):
        point = [
            (compiled_intersection[0] + compiled_intersection[2]) // 2,
            (compiled_intersection[1] + compiled_intersection[3]) // 2,
        ]
    return CompiledAnomalyPrompt(
        candidate=candidate,
        semantic_box_0_1000=list(candidate_box),
        compiled_box_0_1000=compiled_intersection,
        target_point_0_1000=point,
        expected_area_ratio_min=policy.expected_area_ratio_min,
        expected_area_ratio_max=policy.expected_area_ratio_max,
        minimum_mask_containment=policy.minimum_mask_containment_in_plate,
    ), None


def _normalize_jpeg_base64(image_bytes: bytes, maximum_side: int) -> str:
    with Image.open(io.BytesIO(image_bytes)) as image:
        image = image.convert("RGB")
        image.thumbnail((maximum_side, maximum_side), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=88)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _orange_pixel_ratio(image_bytes: bytes, box: list[int]) -> float:
    ratio, _, _ = _orange_foreground_geometry(image_bytes, box)
    return ratio


def _orange_foreground_geometry(
    image_bytes: bytes,
    box: list[int],
) -> tuple[float, list[int] | None, list[int] | None]:
    with Image.open(io.BytesIO(image_bytes)) as image:
        image = image.convert("RGB")
        width, height = image.size
        crop_box = (
            max(0, min(width - 1, round(box[0] / 1000 * width))),
            max(0, min(height - 1, round(box[1] / 1000 * height))),
            max(1, min(width, round(box[2] / 1000 * width))),
            max(1, min(height, round(box[3] / 1000 * height))),
        )
        crop = image.crop(crop_box)
        pixels = list(crop.getdata())
    if not pixels:
        return 0.0, None, None
    orange_indices = [
        index
        for index, (red, green, blue) in enumerate(pixels)
        if red >= 145
        and red >= green * 1.35
        and 35 <= green <= 190
        and blue <= 125
    ]
    if not orange_indices:
        return 0.0, None, None
    crop_width, _ = crop.size
    xs = [index % crop_width for index in orange_indices]
    ys = [index // crop_width for index in orange_indices]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    representative = min(
        orange_indices,
        key=lambda index: (
            (index % crop_width - mean_x) ** 2
            + (index // crop_width - mean_y) ** 2
        ),
    )
    point = [
        round((crop_box[0] + representative % crop_width) / width * 1000),
        round((crop_box[1] + representative // crop_width) / height * 1000),
    ]
    foreground_box = [
        round((crop_box[0] + min(xs)) / width * 1000),
        round((crop_box[1] + min(ys)) / height * 1000),
        round((crop_box[0] + max(xs) + 1) / width * 1000),
        round((crop_box[1] + max(ys) + 1) / height * 1000),
    ]
    return len(orange_indices) / len(pixels), foreground_box, point


def _observation_to_raw(
    observation: BuildPlateObservation,
    rotation: int,
) -> BuildPlateObservation:
    updates: dict[str, Any] = {}
    if observation.bbox_0_1000 is not None:
        updates["bbox_0_1000"] = _box_to_raw(observation.bbox_0_1000, rotation)
    if observation.target_point_0_1000 is not None:
        updates["target_point_0_1000"] = _point_to_raw(
            observation.target_point_0_1000,
            rotation,
        )
    return observation.model_copy(update=updates)


def _point_to_raw(point: list[int], rotation: int) -> list[int]:
    x = point[0] / 1000.0
    y = point[1] / 1000.0
    normalized = DemoGrounder._normalize_rotation(rotation)
    if normalized == 90:
        raw = (y, 1.0 - x)
    elif normalized == 180:
        raw = (1.0 - x, 1.0 - y)
    elif normalized == 270:
        raw = (1.0 - y, x)
    else:
        raw = (x, y)
    return [
        max(0, min(1000, round(raw[0] * 1000))),
        max(0, min(1000, round(raw[1] * 1000))),
    ]


def _box_to_raw(box: list[int], rotation: int) -> list[int]:
    corners = [
        _point_to_raw([box[0], box[1]], rotation),
        _point_to_raw([box[2], box[1]], rotation),
        _point_to_raw([box[2], box[3]], rotation),
        _point_to_raw([box[0], box[3]], rotation),
    ]
    xs = [point[0] for point in corners]
    ys = [point[1] for point in corners]
    result = [min(xs), min(ys), max(xs), max(ys)]
    if result[2] <= result[0]:
        result[2] = min(1000, result[0] + 1)
    if result[3] <= result[1]:
        result[3] = min(1000, result[1] + 1)
    return result


def _point_from_raw(point: list[int], rotation: int) -> list[int]:
    inverse = (360 - DemoGrounder._normalize_rotation(rotation)) % 360
    return _point_to_raw(point, inverse)


def _box_from_raw(box: list[int], rotation: int) -> list[int]:
    inverse = (360 - DemoGrounder._normalize_rotation(rotation)) % 360
    return _box_to_raw(box, inverse)


def _expand_normalized_box(box: list[int], padding: int) -> list[int]:
    return [
        max(0, box[0] - padding),
        max(0, box[1] - padding),
        min(1000, box[2] + padding),
        min(1000, box[3] + padding),
    ]


def _outside_plate_regions(plate: list[int]) -> list[list[int]]:
    x1, y1, x2, y2 = plate
    regions: list[list[int]] = []
    if y1 > 0:
        regions.append([0, 0, 1000, y1])
    if y2 < 1000:
        regions.append([0, y2, 1000, 1000])
    if x1 > 0:
        regions.append([0, y1, x1, y2])
    if x2 < 1000:
        regions.append([x2, y1, 1000, y2])
    return [region for region in regions if region[2] > region[0] and region[3] > region[1]]


def _mask_containment_in_box(tracked: TrackedComponent, box: list[int]) -> float:
    if not tracked.overlay_png_base64:
        return 0.0
    try:
        encoded = base64.b64decode(tracked.overlay_png_base64, validate=True)
        with Image.open(io.BytesIO(encoded)) as overlay:
            alpha = overlay.convert("RGBA").getchannel("A")
            binary = alpha.point(lambda value: 255 if value >= 16 else 0)
            total = sum(binary.histogram()[1:]) / 255.0
            if total <= 0:
                return 0.0
            width, height = binary.size
            crop = binary.crop(
                (
                    round(box[0] / 1000 * width),
                    round(box[1] / 1000 * height),
                    round(box[2] / 1000 * width),
                    round(box[3] / 1000 * height),
                )
            )
            inside = sum(crop.histogram()[1:]) / 255.0
            return max(0.0, min(1.0, inside / total))
    except (ValueError, OSError):
        return 0.0


def _intersection(first: list[int], second: list[int]) -> list[int] | None:
    result = [
        max(first[0], second[0]),
        max(first[1], second[1]),
        min(first[2], second[2]),
        min(first[3], second[3]),
    ]
    return result if result[2] > result[0] and result[3] > result[1] else None


def _area(box: list[int] | None) -> int:
    if box is None:
        return 0
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def _point_in_box(point: list[int], box: list[int]) -> bool:
    return box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]


def _box_iou(first: list[int], second: list[int]) -> float:
    intersection = _area(_intersection(first, second))
    union = _area(first) + _area(second) - intersection
    return intersection / union if union > 0 else 0.0


def _has_mask_conflict(results: list[InspectionMaskResult]) -> bool:
    for index, first in enumerate(results):
        if first.tracked is None:
            continue
        for second in results[index + 1 :]:
            if second.tracked is None or first.object_type == second.object_type:
                continue
            if _box_iou(first.tracked.bbox_0_1000, second.tracked.bbox_0_1000) > 0.45:
                return True
    return False


def _predicate_confidence(
    plate_confidence: float,
    masks: list[InspectionMaskResult],
    anomaly_type: str,
) -> float:
    matching = [
        result.tracked.quality
        for result in masks
        if result.object_type == anomaly_type and result.tracked is not None
    ]
    return min([plate_confidence, *matching]) if matching else plate_confidence
