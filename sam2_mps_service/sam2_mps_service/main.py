from __future__ import annotations

import os
import threading
import math
from contextlib import nullcontext
from pathlib import Path

import cv2
import numpy as np
import torch
from fastapi import FastAPI, HTTPException, Response

from app.models import (
    TrackedComponent,
    TrackingFrameRequest,
    TrackingSessionRequest,
    TrackingSessionResponse,
)
from app.tracking import OpenCvMaskTracker, decode_base64_image
from sam2.build_sam import build_sam2
from sam2.sam2_image_predictor import SAM2ImagePredictor


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CHECKPOINT = (
    PROJECT_ROOT
    / "third_party"
    / "sam2"
    / "checkpoints"
    / "sam2.1_hiera_tiny.pt"
)
DEFAULT_CONFIG = "configs/sam2.1/sam2.1_hiera_t.yaml"


class Sam2MpsLkTracker(OpenCvMaskTracker):
    """Official SAM 2.1 box mask followed by streaming LK/RANSAC tracking."""

    def __init__(
        self,
        predictor: SAM2ImagePredictor,
        device: str,
        model_name: str,
    ) -> None:
        super().__init__()
        self.predictor = predictor
        self.device = device
        self.provider_name = f"{model_name}-{device}+box-mask+lk"
        self._predictor_lock = threading.Lock()

    def _initial_mask(
        self,
        image: np.ndarray,
        component_id: str,
        box: tuple[int, int, int, int],
        guidance_target=None,
    ) -> np.ndarray:
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        prompt = np.asarray(box, dtype=np.float32)
        autocast = (
            torch.autocast(device_type="cuda", dtype=torch.bfloat16)
            if self.device == "cuda"
            else nullcontext()
        )
        with self._predictor_lock, torch.inference_mode(), autocast:
            self.predictor.set_image(rgb)
            point_coords = None
            point_labels = None
            component_key = component_id.lower()
            uses_semantic_point = (
                self._is_filament_component(component_id)
                or component_key.startswith("paper_figure_")
                or any(
                    marker in component_key
                    for marker in ("spindle", "spool axis", "料盘轴")
                )
            )
            if (
                uses_semantic_point
                and guidance_target is not None
                and guidance_target.target_point_0_1000
            ):
                point_coords = np.asarray(
                    [[
                        guidance_target.target_point_0_1000[0] / 1000 * image.shape[1],
                        guidance_target.target_point_0_1000[1] / 1000 * image.shape[0],
                    ]],
                    dtype=np.float32,
                )
                point_labels = np.asarray([1], dtype=np.int32)
            masks, scores, _ = self.predictor.predict(
                point_coords=point_coords,
                point_labels=point_labels,
                box=prompt,
                multimask_output=True,
            )
        if masks is None or len(masks) == 0:
            raise RuntimeError("SAM 2.1 returned no mask")
        best = self._select_box_mask(
            masks=np.asarray(masks),
            scores=np.asarray(scores).reshape(-1),
            box=box,
            component_id=component_id,
        )
        selected = np.asarray(masks[best]).squeeze().astype(bool)
        result = np.where(selected, 255, 0).astype(np.uint8)
        contours, _ = cv2.findContours(
            result,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        if not contours:
            raise RuntimeError("SAM 2.1 returned an empty mask")
        largest = max(contours, key=cv2.contourArea)
        result.fill(0)
        cv2.drawContours(result, [largest], -1, 255, thickness=-1)
        component_key = component_id.lower()
        semantic_locked_target = (
            component_key.startswith("paper_figure_")
            or component_key == "ams_lite_empty_spool_spindle"
        )
        if semantic_locked_target:
            # Qwen names the identity; SAM supplies the visible surface.  In a
            # crowded overview, box-only SAM can absorb a table patch, the
            # central rail, or a neighbouring AMS arm.  Those pixels contradict
            # the semantic proposal and must never reach Unity.  Crop first,
            # then keep the connected foreground supported by Qwen's positive
            # point (falling back to the largest remaining component).
            x1, y1, x2, y2 = box
            semantic_region = np.zeros_like(result)
            semantic_region[y1:y2, x1:x2] = 255
            result = cv2.bitwise_and(result, semantic_region)
            result = self._overview_supported_component(
                result,
                guidance_target,
            )
            if cv2.countNonZero(result) <= 0:
                raise RuntimeError(
                    "SAM 2.1 target mask has no foreground inside the semantic box"
                )
        if self._is_filament_component(component_id):
            refined = self._refine_filament_mask(
                image,
                component_id,
                box,
                candidate_mask=result,
                target_point_0_1000=(
                    guidance_target.target_point_0_1000
                    if guidance_target is not None
                    else None
                ),
            )
            if cv2.countNonZero(refined) <= 0:
                raise RuntimeError(
                    "SAM 2.1 filament mask lacks current-frame orange foreground support"
                )
            result = refined
        if self._is_plate_anomaly_component(component_id):
            refined = self._refine_plate_anomaly_mask(
                image,
                component_id,
                box,
                candidate_mask=result,
                target_point_0_1000=(
                    guidance_target.target_point_0_1000
                    if guidance_target is not None
                    else None
                ),
            )
            if cv2.countNonZero(refined) <= 0:
                raise RuntimeError(
                    "SAM 2.1 anomaly mask lacks current-frame orange foreground support"
                )
            result = refined
        return result

    @staticmethod
    def _overview_supported_component(mask: np.ndarray, guidance_target) -> np.ndarray:
        count, labels, stats, _ = cv2.connectedComponentsWithStats(
            (mask > 0).astype(np.uint8),
            connectivity=8,
        )
        if count <= 1:
            return mask
        selected_label = 0
        if guidance_target is not None and guidance_target.target_point_0_1000:
            height, width = mask.shape[:2]
            point_x = max(
                0,
                min(
                    width - 1,
                    round(guidance_target.target_point_0_1000[0] / 1000 * width),
                ),
            )
            point_y = max(
                0,
                min(
                    height - 1,
                    round(guidance_target.target_point_0_1000[1] / 1000 * height),
                ),
            )
            selected_label = int(labels[point_y, point_x])
        if selected_label <= 0:
            selected_label = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        return np.where(labels == selected_label, 255, 0).astype(np.uint8)

    def _maybe_resegment(
        self,
        image: np.ndarray,
        state,
        propagated_mask: np.ndarray,
        quality: float,
    ) -> tuple[np.ndarray, float, bool]:
        """Refresh the visible surface as the camera moves around the target.

        LK/RANSAC supplies low-latency inter-frame motion. Every third update,
        or sooner after a weak propagation, SAM 2.1 receives the propagated
        mask's expanded box in the current frame. This changes the mask to the
        component surface visible from the new viewpoint instead of warping the
        first-frame silhouette indefinitely.
        """

        component_key = state.component_id.lower()
        if "a1_mini_build_plate" in component_key:
            # Initial plate/anomaly masks are genuine SAM2 keyframes. During
            # live tracking the large plate uses LK/RANSAC, while anomalies are
            # revalidated against current orange pixels in the main backend.
            # Re-running box-only SAM here can jump to the printer base and is
            # too slow for three independent sessions.
            return propagated_mask, quality, False
        if component_key.startswith("paper_figure_"):
            # These overview targets already receive a real Qwen semantic box,
            # a positive point and a SAM2 keyframe. Re-segmenting later from a
            # propagated box lets SAM jump from one AMS Lite part to the whole
            # assembly. Keep the keyframe identity with LK/RANSAC and let the
            # backend quality gate clear/re-ground on loss.
            return propagated_mask, quality, False
        if state.frames_since_resegmentation < 3 and quality >= 0.55:
            return propagated_mask, quality, False

        # Empty-spindle guidance is re-grounded from Qwen + SAM2 on every
        # sampled camera frame by the dedicated endpoint.  Do not ask this LK
        # fallback to grow a propagated spindle box into a different nearby
        # component when the viewpoint changes.
        spindle_target = any(
            marker in state.component_id.lower()
            for marker in ("料盘轴", "spindle", "spool axis")
        )
        if spindle_target:
            return propagated_mask, quality, False
        tracked_box = self._mask_box(propagated_mask)
        if tracked_box is None:
            tracked_box = state.semantic_box
        prompt = self._expanded_box(tracked_box, image.shape, 0.28)
        try:
            candidate = self._initial_mask(image, state.component_id, prompt)
        except RuntimeError:
            return propagated_mask, quality, False
        if cv2.countNonZero(candidate) <= 0:
            return propagated_mask, quality, False
        if not self._resegmentation_consistent(
            propagated_mask,
            candidate,
            state.component_id,
        ):
            return propagated_mask, quality, False
        state.frames_since_resegmentation = 0
        return candidate, max(quality, 0.88), True

    def _resegmentation_consistent(
        self,
        previous_mask: np.ndarray,
        candidate_mask: np.ndarray,
        component_id: str,
    ) -> bool:
        """Allow a partial spindle cap to grow into the complete visible spindle.

        The generic tracker deliberately rejects abrupt area changes.  That is
        correct for buttons and feeder inlets, but it prevents recovery when an
        initial SAM mask contains only one small face of the spool spindle.  A
        spindle candidate may therefore grow by up to 6x, but only when it still
        overlaps the propagated target and its centre stays nearby.  This keeps
        the expansion component-specific rather than weakening every target.
        """

        if self._redetection_consistent(previous_mask, candidate_mask):
            return True
        spindle_target = any(
            marker in component_id.lower()
            for marker in (
                "料盘轴",
                "spindle",
                "spool axis",
            )
        )
        if not spindle_target:
            return False
        previous_area = cv2.countNonZero(previous_mask)
        candidate_area = cv2.countNonZero(candidate_mask)
        if previous_area <= 0 or candidate_area <= 0:
            return False
        area_ratio = candidate_area / previous_area
        if area_ratio < 0.25 or area_ratio > 6.0:
            return False

        px, py, pw, ph = cv2.boundingRect(previous_mask)
        cx, cy, cw, ch = cv2.boundingRect(candidate_mask)
        previous_center = np.array([px + pw / 2.0, py + ph / 2.0])
        candidate_center = np.array([cx + cw / 2.0, cy + ch / 2.0])
        maximum_shift = max(48.0, 1.8 * max(pw, ph))
        if np.linalg.norm(candidate_center - previous_center) > maximum_shift:
            return False

        retained_previous = (
            cv2.countNonZero(cv2.bitwise_and(previous_mask, candidate_mask))
            / previous_area
        )
        return retained_previous >= 0.22

    @staticmethod
    def _select_box_mask(
        *,
        masks: np.ndarray,
        scores: np.ndarray,
        box: tuple[int, int, int, int],
        component_id: str,
    ) -> int:
        """Prefer a confident mask whose area is plausible for the prompt box.

        SAM 2 can return a tiny high-confidence subpart, such as a button, for a
        box that names the complete feeder. The area-alignment term keeps the
        model score important while penalizing masks that occupy only a small
        fraction of the operator-reviewed prompt.
        """

        x1, y1, x2, y2 = box
        box_area = max(1.0, float((x2 - x1) * (y2 - y1)))
        whole_spindle = any(
            marker in component_id.lower()
            for marker in (
                "料盘轴",
                "spindle",
                "spool axis",
            )
        )
        component_key = component_id.lower()
        overview_target = component_key.startswith("paper_figure_")
        slot4_holder_target = component_key == "ams_lite_empty_spool_spindle"
        ranked: list[tuple[float, int]] = []
        diagnostics: list[dict[str, float | int]] = []
        for index, raw_mask in enumerate(masks):
            mask = np.asarray(raw_mask).squeeze().astype(bool)
            mask_area = max(1, int(np.count_nonzero(mask)))
            area_ratio = max(1e-6, float(mask_area) / box_area)
            inside_area = int(np.count_nonzero(mask[y1:y2, x1:x2]))
            prompt_containment = inside_area / mask_area
            area_penalty = 0.16 * abs(math.log(area_ratio))
            if area_ratio < 0.08:
                area_penalty += 0.50
            elif area_ratio < 0.22:
                area_penalty += 0.30
            elif area_ratio < 0.35:
                area_penalty += 0.10
            elif area_ratio > 3.0:
                area_penalty += 0.25
            if whole_spindle and not slot4_holder_target and area_ratio < 0.45:
                area_penalty += 0.40
            if overview_target:
                # The three overview objects are close together. Prefer the
                # SAM alternative that stays inside Qwen's immutable semantic
                # box instead of a higher-score mask that absorbs neighboring
                # AMS Lite structure.
                area_penalty += 1.20 * max(0.0, 0.88 - prompt_containment)
                if area_ratio > 1.50:
                    area_penalty += 0.45
            if slot4_holder_target:
                # Slot 4's white arm sits beside other white AMS/table
                # surfaces. Prefer the SAM alternative supported by Qwen's
                # tight task-profile box; a larger connected white region is
                # precisely the failure mode this route must reject.
                area_penalty += 1.80 * max(0.0, 0.92 - prompt_containment)
                if area_ratio > 1.35:
                    area_penalty += 0.80
                if area_ratio < 0.16:
                    area_penalty += 0.22
            model_score = float(scores[index]) if index < len(scores) else 0.0
            combined_score = model_score - area_penalty
            ranked.append((combined_score, index))
            diagnostics.append(
                {
                    "index": index,
                    "model_score": round(model_score, 4),
                    "area_ratio": round(area_ratio, 4),
                    "prompt_containment": round(prompt_containment, 4),
                    "combined_score": round(combined_score, 4),
                }
            )
        if not ranked:
            raise RuntimeError("SAM 2.1 returned no rankable mask")
        selected = max(ranked)[1]
        if os.getenv("MANUAL2AR_SAM2_DEBUG", "0") == "1":
            print(
                {
                    "event": "sam2_mask_selection",
                    "selected": selected,
                    "candidates": diagnostics,
                },
                flush=True,
            )
        return selected


class Sam2Runtime:
    def __init__(self) -> None:
        requested = os.getenv("MANUAL2AR_SAM2_DEVICE", "auto").strip().lower()
        if requested == "auto":
            self.device = "mps" if torch.backends.mps.is_available() else "cpu"
        elif requested in {"mps", "cpu"}:
            self.device = requested
        else:
            raise RuntimeError("MANUAL2AR_SAM2_DEVICE must be auto, mps, or cpu")
        if self.device == "mps" and not torch.backends.mps.is_available():
            raise RuntimeError("MPS was requested but is unavailable")

        checkpoint = Path(
            os.getenv("MANUAL2AR_SAM2_CHECKPOINT", str(DEFAULT_CHECKPOINT))
        )
        config = os.getenv("MANUAL2AR_SAM2_CONFIG", DEFAULT_CONFIG)
        if not checkpoint.exists():
            raise RuntimeError(f"SAM 2.1 checkpoint not found: {checkpoint}")

        model = build_sam2(
            config,
            str(checkpoint),
            device=self.device,
            apply_postprocessing=True,
        )
        predictor = SAM2ImagePredictor(model)
        self.model_name = checkpoint.stem
        self.tracker = Sam2MpsLkTracker(
            predictor,
            self.device,
            self.model_name,
        )


runtime = Sam2Runtime()
app = FastAPI(
    title="Manual2AR SAM 2.1 Apple-Silicon Service",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "tracking_provider": runtime.tracker.provider_name,
        "device": runtime.device,
        "model": runtime.model_name,
        "mps_available": torch.backends.mps.is_available(),
    }


@app.post(
    "/api/tracking/sessions",
    response_model=TrackingSessionResponse,
    status_code=201,
)
def create_tracking_session(
    request: TrackingSessionRequest,
) -> TrackingSessionResponse:
    try:
        session_id, tracked = runtime.tracker.start(
            decode_base64_image(request.image_base64),
            request.component_id,
            request.bbox_0_1000,
            request.guidance_target,
        )
        return TrackingSessionResponse(session_id=session_id, tracked=tracked)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post(
    "/api/tracking/sessions/{session_id}/frames",
    response_model=TrackedComponent,
)
def update_tracking_session(
    session_id: str,
    request: TrackingFrameRequest,
) -> TrackedComponent:
    try:
        return runtime.tracker.update(
            session_id,
            decode_base64_image(request.image_base64),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Tracking session not found") from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete(
    "/api/tracking/sessions/{session_id}",
    status_code=204,
    response_class=Response,
)
def delete_tracking_session(session_id: str) -> Response:
    if not runtime.tracker.close(session_id):
        raise HTTPException(status_code=404, detail="Tracking session not found")
    return Response(status_code=204)
