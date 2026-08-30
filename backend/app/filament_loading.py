from __future__ import annotations

import base64
import io
from typing import Any

from PIL import Image

from .grounding import rotate_jpeg_for_vlm
from .models import (
    FilamentLoadingInspectionRequest,
    FilamentLoadingInspectionResponse,
    FilamentLoadingMaskResult,
    FilamentLoadingPredicateResult,
    FilamentLoadingRejectedRegion,
    FilamentConnectionVerification,
    FilamentLoadingVisionResult,
    FilamentRegionObservation,
    GuidanceTarget,
    LooseFilamentTipCheck,
)
from .plate_inspection import _box_to_raw, _normalize_jpeg_base64, _point_to_raw
from .tracking import decode_base64_image
from .tracking_provider import HybridMaskTracker, TrackingProviderError
from .vision_task_profiles import (
    FilamentLoadingVisionProfile,
    load_filament_loading_profile,
)


MIN_LOOSE_TIP_ORANGE_RATIO = 0.004


class FilamentLoadingEngine:
    """Task-conditioned Qwen grounding and independently tracked SAM2 masks."""

    def __init__(self, vision: Any, tracker: HybridMaskTracker) -> None:
        self.vision = vision
        self.tracker = tracker

    def inspect(
        self,
        request: FilamentLoadingInspectionRequest,
    ) -> FilamentLoadingInspectionResponse:
        profile = load_filament_loading_profile(request.profile_id)
        raw_image = decode_base64_image(request.image_base64)
        upright_image = rotate_jpeg_for_vlm(raw_image, request.image_rotation_degrees)
        ordered_images = [
            _normalize_jpeg_base64(upright_image, 1280),
            *profile.ordered_reference_images_base64(),
        ]
        raw_qwen = self.vision.chat_structured(
            prompt=_filament_loading_prompt(profile),
            schema=FilamentLoadingVisionResult.model_json_schema(),
            images_base64=ordered_images,
            max_tokens=1800,
        )
        raw_qwen = _repair_missing_region_target_points(raw_qwen)
        qwen = FilamentLoadingVisionResult.model_validate(raw_qwen)
        if _filament_semantics_need_recheck(qwen, upright_image):
            selector_raw: dict[str, Any] | None = None
            focus_box: list[int] | None = None
            recheck_images = ordered_images
            recheck_prompt = _filament_loading_recheck_prompt(profile)
            if _feeder_geometry_unreliable(qwen.feeder_module.bbox_0_1000):
                selector_raw = self.vision.chat_structured(
                    prompt=_single_feeder_selection_prompt(profile),
                    schema=FilamentRegionObservation.model_json_schema(),
                    images_base64=[ordered_images[0]],
                    max_tokens=700,
                )
                selector_raw = _repair_single_region_target_point(selector_raw)
                selector = FilamentRegionObservation.model_validate(selector_raw)
                if (
                    selector.visible == "yes"
                    and selector.bbox_0_1000 is not None
                    and selector.confidence >= 0.60
                    and not _feeder_geometry_unreliable(selector.bbox_0_1000)
                ):
                    focused_current, focus_box = _filament_focus_crop(
                        upright_image,
                        selector.bbox_0_1000,
                    )
                    recheck_images = [
                        focused_current,
                        *profile.ordered_reference_images_base64(),
                    ]
                    recheck_prompt += (
                        " IMAGE 1 is now a focused CURRENT-FRAME crop around the "
                        "selected feeder; output coordinates relative to this crop."
                    )
            recheck_raw = self.vision.chat_structured(
                prompt=recheck_prompt,
                schema=FilamentLoadingVisionResult.model_json_schema(),
                images_base64=recheck_images,
                max_tokens=1800,
            )
            recheck_raw = _repair_missing_region_target_points(recheck_raw)
            recheck = FilamentLoadingVisionResult.model_validate(recheck_raw)
            if focus_box is not None:
                recheck = _filament_result_from_crop(recheck, focus_box)
            first_score = _filament_semantic_score(qwen, upright_image)
            recheck_score = _filament_semantic_score(recheck, upright_image)
            if recheck_score > first_score:
                qwen = recheck
                selected = "focused_recheck"
            else:
                selected = "initial"
            raw_qwen = {
                **qwen.model_dump(),
                "_semantic_recheck": {
                    "selected": selected,
                    "initial_score": round(first_score, 4),
                    "focused_recheck_score": round(recheck_score, 4),
                    "selector": selector_raw,
                    "focus_box_0_1000": focus_box,
                    "initial": raw_qwen,
                    "focused_recheck": recheck_raw,
                },
            }

        # The broad multi-object pass can confuse the normal continuous strand
        # between spool and feeder with a free cut endpoint.  Recover only when
        # its not-inserted proof fails a deterministic current-frame gate.  The
        # focused tie-break checks the two physical success predicates together
        # and cannot promote a frame from exemplar similarity alone.
        tip_valid, tip_gate = _loose_tip_candidate_quality(
            qwen.loose_filament_tip,
            upright_image,
        )
        if qwen.proposed_state in {"not_inserted", "uncertain"} and not tip_valid:
            qwen, connection_audit = self._recover_loaded_connection(
                qwen=qwen,
                upright_image=upright_image,
                profile=profile,
            )
            raw_qwen = {
                **raw_qwen,
                "_loose_tip_quality_gate": tip_gate,
                "_connection_state_tiebreak": connection_audit,
            }

        if qwen.proposed_state == "uncertain":
            # A loaded claim is safety-significant, while a distant diagonal
            # view can leave the broad pass uncertain even though the free
            # endpoint is visible. Compile a lower-feeder crop in both cases:
            # a verified current-frame orange terminal endpoint can recover
            # the guidance state, but it still has to pass the short-tip gate.
            crop_base64, crop_box = _loose_tip_crop(
                upright_image,
                qwen.feeder_module.bbox_0_1000,
            )
            tip_raw = self.vision.chat_structured(
                prompt=_loose_tip_check_prompt(profile),
                schema=LooseFilamentTipCheck.model_json_schema(),
                images_base64=[
                    crop_base64,
                    *profile.ordered_reference_images_base64(),
                ],
                max_tokens=900,
            )
            tip_check = LooseFilamentTipCheck.model_validate(tip_raw)
            raw_qwen = {**raw_qwen, "_loose_tip_check": tip_raw}
            if tip_check.loose_tip_visible == "yes" and tip_check.confidence >= 0.68:
                loose_tip = _tip_check_to_full_observation(tip_check, crop_box)
                loose_tip_orange_ratio, _ = _orange_evidence(
                    upright_image,
                    loose_tip.bbox_0_1000,
                )
            else:
                loose_tip = None
                loose_tip_orange_ratio = 0.0
            loose_tip_is_distinct = _loose_tip_is_distinct_from_inserted(
                loose_tip,
                qwen.inserted_filament_at_inlet,
            )
            loose_tip_valid, loose_tip_gate = _loose_tip_candidate_quality(
                loose_tip,
                upright_image,
            )
            if (
                loose_tip_valid
                and loose_tip_is_distinct
            ):
                absent = FilamentRegionObservation(
                    visible="no",
                    confidence=max(0.68, tip_check.confidence),
                    visible_evidence=(
                        "loaded claim rejected because a current-frame loose tip "
                        "was verified in the lower-feeder crop"
                    ),
                )
                qwen = qwen.model_copy(
                    update={
                        "proposed_state": "not_inserted",
                        "state_confidence": tip_check.confidence,
                        "loose_filament_tip": loose_tip,
                        "inserted_filament_at_inlet": absent,
                        "filament_visible_in_ptfe": absent,
                        "scene_evidence": tip_check.visible_evidence,
                    }
                )
                raw_qwen["_compiled_state_override"] = {
                    "state": "not_inserted",
                    "reason": (
                        "focused loose-tip crop and current orange endpoint "
                        "evidence passed"
                    ),
                    "orange_ratio": loose_tip_orange_ratio,
                    "quality_gate": loose_tip_gate,
                }
            elif loose_tip is not None:
                raw_qwen["_compiled_state_override_rejected"] = {
                    "reason": (
                        "focused candidate was not a distinct short open-air "
                        "filament endpoint"
                    ),
                    "orange_ratio": loose_tip_orange_ratio,
                    "quality_gate": loose_tip_gate,
                    "distinct_from_inserted": loose_tip_is_distinct,
                }
        return self._compile_and_segment(
            request=request,
            profile=profile,
            raw_image=raw_image,
            qwen=qwen,
            qwen_raw=raw_qwen,
        )

    def _recover_loaded_connection(
        self,
        *,
        qwen: FilamentLoadingVisionResult,
        upright_image: bytes,
        profile: FilamentLoadingVisionProfile,
    ) -> tuple[FilamentLoadingVisionResult, dict[str, Any]]:
        """Use a focused binary check to recover direct loaded-state evidence."""

        focused_current, crop_box = _filament_focus_crop(
            upright_image,
            qwen.feeder_module.bbox_0_1000 or [0, 180, 650, 900],
        )
        raw = self.vision.chat_structured(
            prompt=_connection_state_tiebreak_prompt(profile),
            schema=FilamentConnectionVerification.model_json_schema(),
            images_base64=[
                focused_current,
                *profile.ordered_reference_images_base64(),
            ],
            max_tokens=1200,
        )
        raw = _repair_connection_target_points(raw)
        check = FilamentConnectionVerification.model_validate(raw)
        check = _connection_verification_from_crop(check, crop_box)

        inlet_proof = _inserted_observation_from_inlet(
            upright_image,
            qwen.filament_inlet,
            check.inserted_filament_at_inlet,
        )
        ptfe = check.filament_visible_in_ptfe
        ptfe_ratio = 0.0
        if ptfe.bbox_0_1000 is not None:
            ptfe_ratio, ptfe_point = _orange_evidence(
                upright_image,
                ptfe.bbox_0_1000,
            )
            if ptfe_point is not None:
                ptfe = ptfe.model_copy(
                    update={"target_point_0_1000": ptfe_point}
                )
        loaded_proof = (
            check.connection_state == "loaded"
            and check.confidence >= 0.78
            and _visible_with_confidence(inlet_proof, 0.68)
            and _visible_with_confidence(ptfe, 0.68)
            and ptfe_ratio >= 0.002
            and check.free_filament_cut_end.visible != "yes"
        )
        audit: dict[str, Any] = {
            "crop_box_0_1000": crop_box,
            "raw": raw,
            "mapped": check.model_dump(),
            "current_frame_ptfe_orange_ratio": round(ptfe_ratio, 6),
            "loaded_proof_passed": loaded_proof,
        }
        if not loaded_proof:
            return qwen, audit

        absent_tip = FilamentRegionObservation(
            visible="no",
            confidence=max(0.78, check.confidence),
            visible_evidence=(
                "No open-air cut endpoint in focused current-frame connection check"
            ),
        )
        feeder = qwen.feeder_module
        focused_feeder = check.feeder_module
        if (
            focused_feeder.visible == "yes"
            and focused_feeder.bbox_0_1000 is not None
            and focused_feeder.confidence >= 0.70
            and _box_area_ratio(focused_feeder.bbox_0_1000)
            < _box_area_ratio(feeder.bbox_0_1000 or [0, 0, 1000, 1000])
        ):
            feeder = focused_feeder
        recovered = qwen.model_copy(
            update={
                "proposed_state": "loaded",
                "state_confidence": check.confidence,
                "feeder_module": feeder,
                "loose_filament_tip": absent_tip,
                "inserted_filament_at_inlet": inlet_proof,
                "filament_visible_in_ptfe": ptfe,
                "scene_evidence": check.evidence,
            }
        )
        audit["compiled_state_override"] = "loaded"
        return recovered, audit

    def _compile_and_segment(
        self,
        *,
        request: FilamentLoadingInspectionRequest,
        profile: FilamentLoadingVisionProfile,
        raw_image: bytes,
        qwen: FilamentLoadingVisionResult,
        qwen_raw: dict[str, Any],
    ) -> FilamentLoadingInspectionResponse:
        feeder = _observation_to_raw(qwen.feeder_module, request.image_rotation_degrees)
        inlet = _observation_to_raw(qwen.filament_inlet, request.image_rotation_degrees)
        loose_tip = _observation_to_raw(
            qwen.loose_filament_tip, request.image_rotation_degrees
        )
        inserted = _observation_to_raw(
            qwen.inserted_filament_at_inlet, request.image_rotation_degrees
        )
        ptfe = _observation_to_raw(
            qwen.filament_visible_in_ptfe, request.image_rotation_degrees
        )

        feeder_ok = _visible_with_confidence(feeder, 0.65)
        inlet_ok = _visible_with_confidence(inlet, 0.60)
        entered = _visible_with_confidence(inserted, 0.65)
        ptfe_visible = _visible_with_confidence(ptfe, 0.65)
        loose_tip_visible = _visible_with_confidence(loose_tip, 0.65)
        state_confident = qwen.state_confidence >= profile.minimum_state_confidence

        loaded_candidate = (
            state_confident
            and qwen.proposed_state == "loaded"
            and feeder_ok
            and inlet_ok
            and entered
            and ptfe_visible
            and loose_tip.visible != "yes"
        )
        not_inserted_candidate = (
            state_confident
            and qwen.proposed_state == "not_inserted"
            and feeder_ok
            and loose_tip_visible
            and not entered
            and not ptfe_visible
        )

        desired: list[tuple[str, str, FilamentRegionObservation]] = []
        if loaded_candidate:
            desired = [
                ("ams_lite_feeder_module", "feeder_module", feeder),
                ("inserted_filament_at_inlet", "inserted_filament", inserted),
            ]
        elif not_inserted_candidate:
            desired = [
                ("ams_lite_feeder_module", "feeder_module", feeder),
                ("loose_filament_tip", "filament_tip", loose_tip),
            ]

        masks: list[FilamentLoadingMaskResult] = []
        rejected: list[FilamentLoadingRejectedRegion] = []
        started_sessions: list[str] = []
        segmentation_failed = not (loaded_candidate or not_inserted_candidate)

        for object_id, object_type, observation in desired:
            compiled_box, compiled_point, error = compile_filament_prompt(
                observation,
                object_type,
                raw_image,
            )
            if error is not None:
                rejected.append(
                    FilamentLoadingRejectedRegion(
                        object_type=object_type,
                        reason=error,
                    )
                )
                segmentation_failed = True
                continue
            compiled_observation = observation.model_copy(
                update={"target_point_0_1000": compiled_point}
            )
            result = self._start_mask(
                raw_image=raw_image,
                object_id=object_id,
                object_type=object_type,
                observation=compiled_observation,
                compiled_box=compiled_box,
                profile=profile,
                keep_session=request.start_tracking,
            )
            if result.session_id:
                started_sessions.append(result.session_id)
            if result.tracking_ready:
                masks.append(result)
            else:
                segmentation_failed = True
                rejected.append(
                    FilamentLoadingRejectedRegion(
                        object_type=object_type,
                        reason=result.error or "SAM2 mask failed the filament quality gate",
                    )
                )

        if segmentation_failed:
            for session_id in started_sessions:
                try:
                    self.tracker.close(session_id)
                except TrackingProviderError:
                    pass
            masks = []
            status = "uncertain"
            headline = "LOADING STATE UNCERTAIN"
            primary = "REFRAME FEEDER + FILAMENT PATH"
            secondary = "KEEP INLET, TIP AND PTFE TUBE VISIBLE"
        elif loaded_candidate:
            status = "loaded"
            headline = "FILAMENT LOADED"
            primary = "LOADING VERIFIED"
            secondary = "FEEDER + PTFE PATH VERIFIED"
        else:
            status = "not_inserted"
            headline = "FILAMENT NOT INSERTED"
            primary = "INSERT FILAMENT UPWARD"
            secondary = "ALIGN TIP WITH FILAMENT INLET"

        # Qwen's complete-feeder semantic box can include the white mounting
        # body beneath the dark Feeder Unit, especially in landscape views.
        # Compile the arrow endpoint only after SAM has found the actual unit
        # surface, then project the loose end onto that mask's lower boundary.
        if status == "not_inserted" and loose_tip.target_point_0_1000 is not None:
            feeder_mask = next(
                (item for item in masks if item.object_type == "feeder_module"),
                None,
            )
            feeder_surface_box = (
                feeder_mask.tracked.bbox_0_1000
                if feeder_mask is not None and feeder_mask.tracked is not None
                else feeder.bbox_0_1000
            )
            if feeder_surface_box is not None:
                inlet = inlet.model_copy(
                    update={
                        "target_point_0_1000": _compile_insertion_anchor(
                            feeder_surface_box,
                            loose_tip.target_point_0_1000,
                        ),
                        "visible_evidence": (
                            inlet.visible_evidence
                            + "; insertion anchor compiled from the SAM feeder "
                            "surface boundary"
                        ).lstrip("; "),
                    }
                )

        predicates = [
            FilamentLoadingPredicateResult(
                predicate_id="feeder_visible",
                passed=feeder_ok and status != "uncertain",
                confidence=feeder.confidence,
                evidence=feeder.visible_evidence,
            ),
            FilamentLoadingPredicateResult(
                predicate_id="inlet_visible",
                passed=(inlet_ok or status == "not_inserted") and status != "uncertain",
                confidence=inlet.confidence,
                evidence=(
                    inlet.visible_evidence
                    if inlet_ok
                    else (
                        "insertion anchor compiled from the tracked feeder surface "
                        "and current-frame loose filament tip"
                        if status == "not_inserted"
                        else inlet.visible_evidence
                    )
                ),
            ),
            FilamentLoadingPredicateResult(
                predicate_id="filament_entered_feeder",
                passed=status == "loaded" and entered,
                confidence=inserted.confidence,
                evidence=inserted.visible_evidence,
            ),
            FilamentLoadingPredicateResult(
                predicate_id="filament_visible_in_ptfe",
                passed=status == "loaded" and ptfe_visible,
                confidence=ptfe.confidence,
                evidence=ptfe.visible_evidence,
            ),
        ]

        return FilamentLoadingInspectionResponse(
            profile_id=profile.profile_id,
            profile_version=profile.profile_version,
            prompt_version=profile.prompt_version,
            method_label=profile.method_label,
            exemplar_guided=True,
            provider=self.vision.provider,
            model=self.vision.model,
            status=status,
            headline=headline,
            primary_instruction=primary,
            secondary_instruction=secondary,
            predicates=predicates,
            feeder_module=feeder,
            filament_inlet=inlet,
            loose_filament_tip=loose_tip,
            inserted_filament_at_inlet=inserted,
            filament_visible_in_ptfe=ptfe,
            masks=masks,
            rejected_regions=rejected,
            qwen_raw=qwen_raw,
            reference_hashes=profile.reference_hashes(),
        )

    def _start_mask(
        self,
        *,
        raw_image: bytes,
        object_id: str,
        object_type: str,
        observation: FilamentRegionObservation,
        compiled_box: list[int],
        profile: FilamentLoadingVisionProfile,
        keep_session: bool,
    ) -> FilamentLoadingMaskResult:
        area_min, area_max = profile.object_area_limits[object_type]
        target = GuidanceTarget(
            expected_component_id=f"ams_lite_{object_type}",
            semantic_role="target",
            render_mode="mask",
            forbidden_component_ids=[
                "filament_spool",
                "spool_holder",
                "printer_frame",
                "background",
            ],
            target_point_0_1000=observation.target_point_0_1000,
            expected_area_ratio_min=area_min,
            expected_area_ratio_max=area_max,
        )
        try:
            session_id, tracked = self.tracker.start(
                raw_image,
                target.expected_component_id,
                compiled_box,
                target,
            )
        except (ValueError, TrackingProviderError) as exc:
            return FilamentLoadingMaskResult(
                object_id=object_id,
                object_type=object_type,
                semantic_box_0_1000=observation.bbox_0_1000,
                compiled_box_0_1000=compiled_box,
                target_point_0_1000=observation.target_point_0_1000,
                error=str(exc),
            )
        ready = (
            tracked.status == "tracking"
            and tracked.mask_quality_passed
            and not tracked.requires_redetection
            and tracked.quality >= 0.48
            and bool(tracked.overlay_png_base64)
        )
        error = None
        if not ready:
            error = "; ".join(tracked.mask_quality_reasons) or (
                "SAM2 mask did not pass the filament quality gate"
            )
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
        return FilamentLoadingMaskResult(
            object_id=object_id,
            object_type=object_type,
            semantic_box_0_1000=observation.bbox_0_1000,
            compiled_box_0_1000=compiled_box,
            target_point_0_1000=observation.target_point_0_1000,
            session_id=session_id,
            tracked=tracked,
            tracking_ready=ready,
            error=error,
        )


def _filament_loading_prompt(profile: FilamentLoadingVisionProfile) -> str:
    return (
        "This is an exemplar-guided AMS Lite filament-loading check with exactly "
        "three images. IMAGE 1 is the CURRENT CAMERA FRAME and is the only image "
        "for which coordinates may be returned. IMAGE 2 is a LOADED reference. "
        "IMAGE 3 is a NOT INSERTED reference. Never copy exemplar coordinates. "
        f"Device definition: {profile.device_description} "
        "Use these exact parts: feeder_module is ONE complete dark translucent "
        "rectangular AMS Lite Feeder Unit paired with the dominant visible white "
        "filament spool and its orange strand. If several feeder units are visible, "
        "select only the single unit physically connected to that spool; never merge "
        "adjacent feeder units into one box. filament_inlet is the small opening at "
        "that unit's physical underside/spool-facing boundary where filament travels "
        "into the unit; do not interpret LOWER as merely the largest screen-y value "
        "when the feeder is tilted. "
        "loose_filament_tip is the short free end outside and below that inlet; "
        "inserted_filament_at_inlet is only the orange segment physically continuous "
        "into the inlet; filament_visible_in_ptfe is only orange material visibly "
        "inside the gray PTFE tube leaving the feeder at the TOP. The feeder_module "
        "box must contain only the dark/translucent rectangular housing and its "
        "visible lower insertion boundary; never absorb the white spool flange, white "
        "mounting frame, loose loop, or background into this box. "
        "proposed_state=loaded is allowed only when the CURRENT FRAME directly shows "
        "both (1) orange filament entering the lower inlet and (2) orange filament "
        "continuing inside the upper gray PTFE tube. A mounted spool, orange color "
        "behind spool perforations, or filament merely touching the feeder is never "
        "proof of loading. proposed_state=not_inserted requires a clearly visible "
        "loose orange physical ENDPOINT outside the inlet, with "
        "inserted_filament_at_inlet=no and "
        "filament_visible_in_ptfe=no. Otherwise return uncertain. Give tight boxes "
        "and foreground target points for every visible region. In not_inserted, the "
        "tip point must land on the short terminal segment nearest the feeder inlet, "
        "not on the middle of the long loop. Never call a continuous strand that "
        "visibly enters the inlet a loose tip. The tip box must not include the long "
        "loop, spool, or feeder housing. Return concise JSON only."
    )


def _filament_loading_recheck_prompt(profile: FilamentLoadingVisionProfile) -> str:
    return (
        _filament_loading_prompt(profile)
        + " FOCUSED CURRENT-FRAME RECHECK: The first pass was geometrically or "
        "visually inconsistent. Begin by selecting ONE feeder paired with the "
        "largest/closest visible white spool and trace that spool's orange strand "
        "toward this feeder. Put a tight box around this feeder only; its box must "
        "not contain another feeder, most of the spool, or a large background area. "
        "Then inspect two tiny proof regions on this same feeder: the orange strand "
        "at the physical insertion opening and orange material inside the gray PTFE "
        "tube at the upper orange push-fit connector. If both are directly visible, "
        "return loaded even when the assembly is diagonal. Return not_inserted only "
        "when a real orange terminal endpoint is directly visible; the point and "
        "tight box must land on orange pixels. Do not guess a tip in blank background."
    )


def _connection_state_tiebreak_prompt(
    profile: FilamentLoadingVisionProfile,
) -> str:
    return (
        "CONNECTION-STATE TIE-BREAK VERIFICATION. Exactly three images are "
        "provided: IMAGE 1 is a focused CURRENT-FRAME crop, IMAGE 2 is the "
        "LOADED reference, and IMAGE 3 is the NOT INSERTED reference. Return "
        "coordinates only for IMAGE 1. Select the one complete dark translucent "
        "rectangular feeder housing and exclude the white printer body and spool. "
        "Critical definition: the normal orange strand running continuously from "
        "the spool into the lower orange inlet is NOT a free tip. A free cut end "
        "must visibly terminate in open air as it does in IMAGE 3. LOADED requires "
        "both orange filament entering the lower inlet and reddish/orange filament "
        "visible inside the upper gray PTFE tube, with no open-air cut endpoint. "
        "Return tight foreground boxes and target points for the feeder, inserted "
        "segment, PTFE segment, and free cut endpoint. Use visible=no with null "
        "geometry when a region is absent. Do not use an orange gear, button, "
        "connector shell, reflection, or spool perforation as filament evidence. "
        f"Device context: {profile.device_description} Return concise JSON only."
    )


def _single_feeder_selection_prompt(profile: FilamentLoadingVisionProfile) -> str:
    return (
        "SINGLE TARGET SELECTION. One CURRENT CAMERA FRAME is provided. Find ONE "
        "dark translucent rectangular AMS Lite Feeder Unit that is physically paired "
        "with the dominant/closest visible white filament spool and its orange "
        "filament strand. Multiple adjacent feeder units may overlap in perspective: "
        "select only the unit connected to that spool and never merge two housings. "
        "Return visible=yes, a tight box around only that one translucent housing, a "
        "point on its solid dark surface, confidence, and brief evidence. The box must "
        "exclude other feeder housings, the spool, white mounting body, tubes, and "
        f"background. Device context: {profile.device_description} JSON only."
    )


def _repair_single_region_target_point(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("visible") != "yes" or payload.get("target_point_0_1000") is not None:
        return payload
    box = payload.get("bbox_0_1000")
    if not isinstance(box, list) or len(box) != 4:
        return payload
    repaired = dict(payload)
    repaired["target_point_0_1000"] = [
        round((box[0] + box[2]) / 2),
        round((box[1] + box[3]) / 2),
    ]
    return repaired


def _repair_connection_target_points(payload: dict[str, Any]) -> dict[str, Any]:
    repaired = dict(payload)
    for key in (
        "feeder_module",
        "inserted_filament_at_inlet",
        "filament_visible_in_ptfe",
        "free_filament_cut_end",
    ):
        region = repaired.get(key)
        if not isinstance(region, dict) or region.get("visible") != "yes":
            continue
        box = region.get("bbox_0_1000")
        if region.get("target_point_0_1000") is not None:
            continue
        if not isinstance(box, list) or len(box) != 4:
            continue
        updated = dict(region)
        updated["target_point_0_1000"] = [
            round((box[0] + box[2]) / 2),
            round((box[1] + box[3]) / 2),
        ]
        repaired[key] = updated
    return repaired


def _feeder_geometry_unreliable(box: list[int] | None) -> bool:
    if box is None:
        return True
    width = box[2] - box[0]
    height = box[3] - box[1]
    return _box_area_ratio(box) > 0.34 or width > 650 or height > 720


def _filament_focus_crop(
    image_bytes: bytes,
    feeder_box: list[int],
) -> tuple[str, list[int]]:
    width = feeder_box[2] - feeder_box[0]
    height = feeder_box[3] - feeder_box[1]
    crop_box = [
        max(0, round(feeder_box[0] - width * 0.10)),
        max(0, round(feeder_box[1] - height * 0.55)),
        min(1000, round(feeder_box[2] + width * 0.10)),
        min(1000, round(feeder_box[3] + height * 0.65)),
    ]
    with Image.open(io.BytesIO(image_bytes)) as image:
        image = image.convert("RGB")
        image_width, image_height = image.size
        crop = image.crop(
            (
                round(crop_box[0] / 1000 * image_width),
                round(crop_box[1] / 1000 * image_height),
                round(crop_box[2] / 1000 * image_width),
                round(crop_box[3] / 1000 * image_height),
            )
        )
        buffer = io.BytesIO()
        crop.save(buffer, format="JPEG", quality=92)
    return base64.b64encode(buffer.getvalue()).decode("ascii"), crop_box


def _filament_result_from_crop(
    result: FilamentLoadingVisionResult,
    crop_box: list[int],
) -> FilamentLoadingVisionResult:
    def map_point(point: list[int]) -> list[int]:
        return [
            round(crop_box[0] + point[0] / 1000 * (crop_box[2] - crop_box[0])),
            round(crop_box[1] + point[1] / 1000 * (crop_box[3] - crop_box[1])),
        ]

    def map_observation(observation: FilamentRegionObservation) -> FilamentRegionObservation:
        updates: dict[str, Any] = {}
        if observation.bbox_0_1000 is not None:
            box = observation.bbox_0_1000
            updates["bbox_0_1000"] = [*map_point(box[:2]), *map_point(box[2:])]
        if observation.target_point_0_1000 is not None:
            updates["target_point_0_1000"] = map_point(
                observation.target_point_0_1000
            )
        return observation.model_copy(update=updates)

    return result.model_copy(
        update={
            "feeder_module": map_observation(result.feeder_module),
            "filament_inlet": map_observation(result.filament_inlet),
            "loose_filament_tip": map_observation(result.loose_filament_tip),
            "inserted_filament_at_inlet": map_observation(
                result.inserted_filament_at_inlet
            ),
            "filament_visible_in_ptfe": map_observation(
                result.filament_visible_in_ptfe
            ),
        }
    )


def _observation_from_crop(
    observation: FilamentRegionObservation,
    crop_box: list[int],
) -> FilamentRegionObservation:
    def map_point(point: list[int]) -> list[int]:
        return [
            round(crop_box[0] + point[0] / 1000 * (crop_box[2] - crop_box[0])),
            round(crop_box[1] + point[1] / 1000 * (crop_box[3] - crop_box[1])),
        ]

    updates: dict[str, Any] = {}
    if observation.bbox_0_1000 is not None:
        box = observation.bbox_0_1000
        updates["bbox_0_1000"] = [*map_point(box[:2]), *map_point(box[2:])]
    if observation.target_point_0_1000 is not None:
        updates["target_point_0_1000"] = map_point(
            observation.target_point_0_1000
        )
    return observation.model_copy(update=updates)


def _connection_verification_from_crop(
    check: FilamentConnectionVerification,
    crop_box: list[int],
) -> FilamentConnectionVerification:
    return check.model_copy(
        update={
            "feeder_module": _observation_from_crop(
                check.feeder_module,
                crop_box,
            ),
            "inserted_filament_at_inlet": _observation_from_crop(
                check.inserted_filament_at_inlet,
                crop_box,
            ),
            "filament_visible_in_ptfe": _observation_from_crop(
                check.filament_visible_in_ptfe,
                crop_box,
            ),
            "free_filament_cut_end": _observation_from_crop(
                check.free_filament_cut_end,
                crop_box,
            ),
        }
    )


def _inserted_observation_from_inlet(
    image_bytes: bytes,
    inlet: FilamentRegionObservation,
    focused_inserted: FilamentRegionObservation,
) -> FilamentRegionObservation:
    """Compile insertion proof from current orange pixels at the semantic inlet."""

    candidates = [inlet, focused_inserted]
    best: tuple[float, FilamentRegionObservation, list[int]] | None = None
    for candidate in candidates:
        if candidate.bbox_0_1000 is None:
            continue
        ratio, point = _orange_evidence(image_bytes, candidate.bbox_0_1000)
        if point is None:
            continue
        if best is None or ratio > best[0]:
            best = (ratio, candidate, point)
    if best is None or best[0] < 0.012:
        return FilamentRegionObservation(
            visible="uncertain",
            confidence=0.0,
            visible_evidence="No current-frame orange insertion proof at the inlet",
        )
    ratio, candidate, point = best
    return FilamentRegionObservation(
        visible="yes",
        bbox_0_1000=candidate.bbox_0_1000,
        target_point_0_1000=point,
        confidence=max(0.68, candidate.confidence),
        visible_evidence=(
            f"Current-frame orange filament is continuous at the semantic inlet "
            f"(orange ratio {ratio:.4f})"
        ),
    )


def _filament_semantics_need_recheck(
    qwen: FilamentLoadingVisionResult,
    upright_image: bytes,
) -> bool:
    feeder_box = qwen.feeder_module.bbox_0_1000
    if qwen.proposed_state == "uncertain" or feeder_box is None:
        return True
    feeder_area = _box_area_ratio(feeder_box)
    if feeder_area > 0.34 or feeder_area < 0.008:
        return True
    if qwen.proposed_state == "loaded":
        return not (
            qwen.inserted_filament_at_inlet.visible == "yes"
            and qwen.filament_visible_in_ptfe.visible == "yes"
            and _loaded_color_evidence_passes(upright_image, qwen)
        )
    if qwen.proposed_state == "not_inserted":
        tip = qwen.loose_filament_tip
        if tip.visible != "yes" or tip.bbox_0_1000 is None:
            return True
        orange_ratio, _ = _orange_evidence(upright_image, tip.bbox_0_1000)
        return orange_ratio < MIN_LOOSE_TIP_ORANGE_RATIO
    return True


def _filament_semantic_score(
    qwen: FilamentLoadingVisionResult,
    upright_image: bytes,
) -> float:
    score = qwen.state_confidence
    feeder_box = qwen.feeder_module.bbox_0_1000
    if feeder_box is None:
        return score - 5.0
    feeder_area = _box_area_ratio(feeder_box)
    score += 1.5 if 0.008 <= feeder_area <= 0.34 else -3.0
    if qwen.feeder_module.visible == "yes":
        score += qwen.feeder_module.confidence
    if qwen.filament_inlet.visible == "yes":
        score += qwen.filament_inlet.confidence * 0.5

    if qwen.proposed_state == "loaded":
        score += 1.0
        score += 1.2 if qwen.inserted_filament_at_inlet.visible == "yes" else -1.2
        score += 1.2 if qwen.filament_visible_in_ptfe.visible == "yes" else -1.2
        score += 1.5 if _loaded_color_evidence_passes(upright_image, qwen) else -1.5
        if qwen.loose_filament_tip.visible == "yes":
            score -= 1.0
    elif qwen.proposed_state == "not_inserted":
        score += 0.8
        tip = qwen.loose_filament_tip
        if tip.visible == "yes" and tip.bbox_0_1000 is not None:
            orange_ratio, _ = _orange_evidence(upright_image, tip.bbox_0_1000)
            score += 1.8 if orange_ratio >= 0.012 else -2.5
        else:
            score -= 2.0
        if qwen.inserted_filament_at_inlet.visible == "yes":
            score -= 0.8
        if qwen.filament_visible_in_ptfe.visible == "yes":
            score -= 0.8
    else:
        score -= 2.5
    return score


def _box_area_ratio(box: list[int]) -> float:
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1]) / 1_000_000.0


def _repair_missing_region_target_points(payload: dict[str, Any]) -> dict[str, Any]:
    """Compile an omitted Qwen point from its own tight semantic box.

    Qwen occasionally returns a valid visible box but omits the redundant
    interior point. Rejecting the entire frame makes the recording UI appear
    dead even though semantic localization succeeded. This deterministic
    repair never invents a box or state: it only uses the center of Qwen's
    current-frame box as the SAM positive point and records the repair in the
    raw audit payload.
    """
    repaired = dict(payload)
    repairs: list[dict[str, Any]] = []
    for key in (
        "feeder_module",
        "filament_inlet",
        "loose_filament_tip",
        "inserted_filament_at_inlet",
        "filament_visible_in_ptfe",
    ):
        region = repaired.get(key)
        if not isinstance(region, dict) or region.get("visible") != "yes":
            continue
        box = region.get("bbox_0_1000")
        point = region.get("target_point_0_1000")
        if point is not None or not isinstance(box, list) or len(box) != 4:
            continue
        if not all(isinstance(value, (int, float)) for value in box):
            continue
        compiled_point = [
            round((box[0] + box[2]) / 2),
            round((box[1] + box[3]) / 2),
        ]
        updated = dict(region)
        updated["target_point_0_1000"] = compiled_point
        updated["visible_evidence"] = (
            f"{updated.get('visible_evidence', '')} "
            "Positive SAM point compiled from the Qwen semantic-box center."
        ).strip()
        repaired[key] = updated
        repairs.append({"region": key, "compiled_point_0_1000": compiled_point})
    if repairs:
        repaired["_compiled_geometry_repairs"] = repairs
    return repaired


def _loose_tip_check_prompt(profile: FilamentLoadingVisionProfile) -> str:
    return (
        "LOOSE-TIP OVERRIDE CHECK. Exactly three images are provided. IMAGE 1 is "
        "a CURRENT-FRAME CROP around and below the feeder and is the only coordinate "
        "source. IMAGE 2 is a full LOADED reference; IMAGE 3 is a full NOT INSERTED "
        "reference. Search only for the free physical ENDPOINT of the orange filament "
        "outside/below the dark feeder. A long orange loop that visibly terminates "
        "before entering the feeder is loose_tip_visible=yes. Do not label an orange "
        "button, gear, reflection, spool perforation, or a continuous inserted strand. "
        "When yes, return a very tight crop-coordinate box around the short terminal "
        "segment and put the target point directly on orange foreground. Otherwise use "
        f"no or uncertain. Device context: {profile.device_description} JSON only."
    )


def _loaded_color_evidence_passes(
    image_bytes: bytes,
    qwen: FilamentLoadingVisionResult,
) -> bool:
    inserted_box = qwen.inserted_filament_at_inlet.bbox_0_1000
    ptfe_box = qwen.filament_visible_in_ptfe.bbox_0_1000
    if inserted_box is None or ptfe_box is None:
        return False
    inserted_ratio, _ = _orange_evidence(image_bytes, inserted_box)
    ptfe_ratio, _ = _orange_evidence(image_bytes, ptfe_box)
    # Filament inside translucent gray PTFE is desaturated and occupies only a
    # thin fraction of a tight semantic box.  The inlet remains the stronger
    # chromatic proof; PTFE is accepted only after Qwen has localized that tube.
    return inserted_ratio >= 0.012 and ptfe_ratio >= 0.002


def _loose_tip_crop(
    image_bytes: bytes,
    feeder_box: list[int] | None,
) -> tuple[str, list[int]]:
    if feeder_box is None:
        crop_box = [0, 250, 850, 1000]
    else:
        crop_box = [
            max(0, feeder_box[0] - 90),
            max(0, feeder_box[1] - 40),
            min(1000, feeder_box[2] + 470),
            min(1000, feeder_box[3] + 360),
        ]
    with Image.open(io.BytesIO(image_bytes)) as image:
        image = image.convert("RGB")
        width, height = image.size
        crop = image.crop(
            (
                round(crop_box[0] / 1000 * width),
                round(crop_box[1] / 1000 * height),
                round(crop_box[2] / 1000 * width),
                round(crop_box[3] / 1000 * height),
            )
        )
        buffer = io.BytesIO()
        crop.save(buffer, format="JPEG", quality=92)
    return base64.b64encode(buffer.getvalue()).decode("ascii"), crop_box


def _tip_check_to_full_observation(
    check: LooseFilamentTipCheck,
    crop_box: list[int],
) -> FilamentRegionObservation:
    def map_point(point: list[int]) -> list[int]:
        return [
            round(crop_box[0] + point[0] / 1000 * (crop_box[2] - crop_box[0])),
            round(crop_box[1] + point[1] / 1000 * (crop_box[3] - crop_box[1])),
        ]

    box = check.bbox_0_1000
    mapped_box = [*map_point(box[:2]), *map_point(box[2:])]
    return FilamentRegionObservation(
        visible="yes",
        bbox_0_1000=mapped_box,
        target_point_0_1000=map_point(check.target_point_0_1000),
        confidence=check.confidence,
        visible_evidence=check.visible_evidence,
    )


def compile_filament_prompt(
    observation: FilamentRegionObservation,
    object_type: str,
    raw_image: bytes,
) -> tuple[list[int] | None, list[int] | None, str | None]:
    if observation.bbox_0_1000 is None or observation.target_point_0_1000 is None:
        return None, None, "Qwen did not provide current-frame geometry"
    if observation.confidence < 0.60:
        return None, None, (
            f"Qwen region confidence {observation.confidence:.3f} is below 0.60"
        )
    semantic = observation.bbox_0_1000
    point = observation.target_point_0_1000
    if object_type == "feeder_module":
        compiled = list(semantic)
        # The dark translucent housing can make a Qwen point land on a gear,
        # opening, or background visible through the cover. The semantic box
        # is already task-gated to the Feeder Unit, so use its interior center
        # as the stable positive SAM point. This keeps the point away from the
        # white mounting frame and box edges without inventing any geometry.
        point = [
            round((semantic[0] + semantic[2]) / 2),
            round((semantic[1] + semantic[3]) / 2),
        ]
    else:
        compiled = _expand_box(semantic, 1.22, minimum_padding=6)
        orange_ratio, orange_centroid, orange_box = _orange_foreground_geometry(
            raw_image,
            semantic,
        )
        minimum_orange_ratio = {
            "filament_tip": 0.0012,
            "inserted_filament": 0.0020,
            "ptfe_filament": 0.0,
        }.get(object_type, 0.012)
        if orange_ratio < minimum_orange_ratio:
            return None, None, (
                "region lacks current-frame orange filament evidence "
                f"({orange_ratio:.4f} < {minimum_orange_ratio:.4f})"
            )
        # Thin curved filament is a difficult point-prompt target. Qwen's point
        # can land on background by a few pixels even when its tight box is
        # correct, so compile the point to the centroid of current-frame orange
        # pixels. This is deterministic current evidence, not exemplar geometry.
        if orange_centroid is not None:
            point = orange_centroid
        # A distant loose tip can occupy far below one percent of Qwen's box.
        # Retain the current-frame colour gate, but compile SAM around the actual
        # orange foreground rather than around the surrounding background.
        if orange_box is not None and object_type in {"filament_tip", "inserted_filament"}:
            compiled = _expand_box(orange_box, 1.65, minimum_padding=7)
    if not (compiled[0] <= point[0] <= compiled[2] and compiled[1] <= point[1] <= compiled[3]):
        return None, None, "target point is outside the compiled segmentation prompt"
    return compiled, point, None


def _visible_with_confidence(
    observation: FilamentRegionObservation,
    threshold: float,
) -> bool:
    return observation.visible == "yes" and observation.confidence >= threshold


def _observation_to_raw(
    observation: FilamentRegionObservation,
    rotation: int,
) -> FilamentRegionObservation:
    updates: dict[str, Any] = {}
    if observation.bbox_0_1000 is not None:
        updates["bbox_0_1000"] = _box_to_raw(observation.bbox_0_1000, rotation)
    if observation.target_point_0_1000 is not None:
        updates["target_point_0_1000"] = _point_to_raw(
            observation.target_point_0_1000,
            rotation,
        )
    return observation.model_copy(update=updates)


def _expand_box(box: list[int], factor: float, minimum_padding: int) -> list[int]:
    width = box[2] - box[0]
    height = box[3] - box[1]
    pad_x = max(minimum_padding, round(width * (factor - 1.0) * 0.5))
    pad_y = max(minimum_padding, round(height * (factor - 1.0) * 0.5))
    return [
        max(0, box[0] - pad_x),
        max(0, box[1] - pad_y),
        min(1000, box[2] + pad_x),
        min(1000, box[3] + pad_y),
    ]


def _compile_insertion_anchor(
    feeder_box: list[int],
    loose_tip_point: list[int],
) -> list[int]:
    """Project the loose tip onto the feeder's lower insertion boundary."""

    return [
        max(feeder_box[0], min(feeder_box[2], loose_tip_point[0])),
        feeder_box[3],
    ]


def _loose_tip_is_distinct_from_inserted(
    loose_tip: FilamentRegionObservation | None,
    inserted: FilamentRegionObservation,
) -> bool:
    if (
        loose_tip is None
        or loose_tip.bbox_0_1000 is None
        or inserted.visible != "yes"
        or inserted.bbox_0_1000 is None
    ):
        return True
    loose = loose_tip.bbox_0_1000
    reference = inserted.bbox_0_1000
    intersection_width = max(0, min(loose[2], reference[2]) - max(loose[0], reference[0]))
    intersection_height = max(0, min(loose[3], reference[3]) - max(loose[1], reference[1]))
    intersection = intersection_width * intersection_height
    reference_area = max(1, (reference[2] - reference[0]) * (reference[3] - reference[1]))
    # A genuine free endpoint can be close to the inlet, but it must not be
    # mostly the same pixels already used as direct evidence of insertion.
    return intersection / reference_area < 0.35


def _loose_tip_candidate_quality(
    loose_tip: FilamentRegionObservation | None,
    image_bytes: bytes,
) -> tuple[bool, dict[str, Any]]:
    """Reject broad/mid-strand masks masquerading as a free filament end."""

    if (
        loose_tip is None
        or loose_tip.visible != "yes"
        or loose_tip.confidence < 0.65
        or loose_tip.bbox_0_1000 is None
        or loose_tip.target_point_0_1000 is None
    ):
        return False, {"passed": False, "reason": "no confident loose-tip geometry"}
    box = loose_tip.bbox_0_1000
    width = box[2] - box[0]
    height = box[3] - box[1]
    area = _box_area_ratio(box)
    orange_ratio, orange_point, orange_box = _orange_foreground_geometry(
        image_bytes,
        box,
    )
    orange_width = 0 if orange_box is None else orange_box[2] - orange_box[0]
    orange_height = 0 if orange_box is None else orange_box[3] - orange_box[1]
    point_distance = 10_000.0
    if orange_point is not None:
        point_distance = (
            (orange_point[0] - loose_tip.target_point_0_1000[0]) ** 2
            + (orange_point[1] - loose_tip.target_point_0_1000[1]) ** 2
        ) ** 0.5
    passed = (
        orange_ratio >= MIN_LOOSE_TIP_ORANGE_RATIO
        and width <= 135
        and height <= 170
        and area <= 0.013
        and orange_width <= 125
        and orange_height <= 155
        and point_distance <= 80
    )
    return passed, {
        "passed": passed,
        "bbox_width": width,
        "bbox_height": height,
        "bbox_area_ratio": round(area, 6),
        "orange_ratio": round(orange_ratio, 6),
        "orange_box_0_1000": orange_box,
        "target_to_orange_distance": round(point_distance, 3),
        "reason": (
            "short current-frame orange endpoint passed"
            if passed
            else "candidate is blank, broad, or a continuous mid-strand region"
        ),
    }


def _orange_evidence(
    image_bytes: bytes,
    box: list[int],
) -> tuple[float, list[int] | None]:
    ratio, centroid, _ = _orange_foreground_geometry(image_bytes, box)
    return ratio, centroid


def _orange_foreground_geometry(
    image_bytes: bytes,
    box: list[int],
) -> tuple[float, list[int] | None, list[int] | None]:
    with Image.open(io.BytesIO(image_bytes)) as image:
        image = image.convert("RGB")
        width, height = image.size
        left = max(0, min(width - 1, round(box[0] / 1000 * width)))
        top = max(0, min(height - 1, round(box[1] / 1000 * height)))
        right = max(left + 1, min(width, round(box[2] / 1000 * width)))
        bottom = max(top + 1, min(height, round(box[3] / 1000 * height)))
        crop = image.crop((left, top, right, bottom))
        pixels = list(crop.getdata())
    if not pixels:
        return 0.0, None, None
    orange_indices = [
        index
        for index, (red, green, blue) in enumerate(pixels)
        if red >= 125
        and red >= green * 1.18
        and red >= blue * 1.35
        and 28 <= green <= 205
        and blue <= 155
    ]
    if not orange_indices:
        return 0.0, None, None
    crop_width = right - left
    mean_x = sum(index % crop_width for index in orange_indices) / len(orange_indices)
    mean_y = sum(index // crop_width for index in orange_indices) / len(orange_indices)
    representative_index = min(
        orange_indices,
        key=lambda index: (
            (index % crop_width - mean_x) ** 2
            + (index // crop_width - mean_y) ** 2
        ),
    )
    representative_x = representative_index % crop_width
    representative_y = representative_index // crop_width
    centroid = [
        max(0, min(1000, round((left + representative_x) / width * 1000))),
        max(0, min(1000, round((top + representative_y) / height * 1000))),
    ]
    xs = [index % crop_width for index in orange_indices]
    ys = [index // crop_width for index in orange_indices]
    orange_box = [
        max(0, min(1000, round((left + min(xs)) / width * 1000))),
        max(0, min(1000, round((top + min(ys)) / height * 1000))),
        max(0, min(1000, round((left + max(xs) + 1) / width * 1000))),
        max(0, min(1000, round((top + max(ys) + 1) / height * 1000))),
    ]
    return len(orange_indices) / len(pixels), centroid, orange_box
