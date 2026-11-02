from __future__ import annotations

import base64
import io
import threading
import uuid
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

from manual2ar_contracts.perception import GuidanceTarget, TrackedComponent


@dataclass
class _TrackingState:
    component_id: str
    gray: np.ndarray
    mask: np.ndarray
    points: np.ndarray | None
    prompt_box: tuple[int, int, int, int]
    # The detector / VLM proposal must remain immutable during a tracking
    # session.  A propagated mask is only a motion hypothesis; replacing this
    # semantic box with that hypothesis lets a drifting mask validate itself.
    semantic_box: tuple[int, int, int, int] | None = None
    guidance_target: GuidanceTarget | None = None
    color_guard_enabled: bool = False
    frames_since_resegmentation: int = 0
    frame_index: int = 0
    relocalization_count: int = 0
    last_centroid: tuple[float, float] | None = None
    drift_ratio: float = 0.0

    def __post_init__(self) -> None:
        if self.semantic_box is None:
            self.semantic_box = self.prompt_box


class OpenCvMaskTracker:
    """CPU baseline with the same contract as a future SAM 2 service.

    The first frame is initialized from a detector box. A blue-pen demo gets a
    color-derived pixel mask; other components use GrabCut to turn the detector
    box into a real foreground pixel mask. Later frames propagate the mask with
    pyramidal Lucas-Kanade optical flow and a robust affine transform. This
    keeps the protocol and UI testable on a Mac without claiming SAM 2 quality.
    """

    provider_name = "opencv-grabcut-lk-baseline"

    def __init__(self) -> None:
        self._states: dict[str, _TrackingState] = {}
        self._lock = threading.Lock()

    def start(
        self,
        image_bytes: bytes,
        component_id: str,
        bbox_0_1000: list[int],
        guidance_target: GuidanceTarget | None = None,
    ) -> tuple[str, TrackedComponent]:
        image = self._decode(image_bytes)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        box = self._normalized_box_to_pixels(bbox_0_1000, image.shape)
        mask = self._initial_mask(image, component_id, box, guidance_target)
        points = self._sample_points(gray, mask)
        color_guard_enabled = bool(
            (
                self._is_pen(component_id)
                and cv2.countNonZero(self._blue_pen_mask(image)) > 0
            )
            or (
                self._is_filament_component(component_id)
                and cv2.countNonZero(mask) > 0
            )
            or (
                self._is_plate_anomaly_component(component_id)
                and cv2.countNonZero(mask) > 0
            )
        )
        session_id = uuid.uuid4().hex
        state = _TrackingState(
            component_id=component_id,
            gray=gray,
            mask=mask,
            points=points,
            prompt_box=box,
            semantic_box=box,
            guidance_target=guidance_target,
            color_guard_enabled=color_guard_enabled,
            last_centroid=self._mask_centroid(mask),
        )
        with self._lock:
            self._states[session_id] = state
        passed, _, _, _ = self._mask_quality(state)
        return session_id, self._describe(
            state,
            quality=1.0 if passed else 0.0,
            status="tracking" if passed else "lost",
        )

    def update(self, session_id: str, image_bytes: bytes) -> TrackedComponent:
        image = self._decode(image_bytes)
        next_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        with self._lock:
            state = self._states.get(session_id)
            if state is None:
                raise KeyError(session_id)

            next_mask, quality = self._propagate(state, next_gray)
            state.frames_since_resegmentation += 1
            # The controlled blue-pen task has an observable color cue. Use it
            # as a re-detection path when motion blur or camera movement causes
            # optical flow to lose the object.
            current_evidence_validated = False
            if (
                (
                    state.component_id.lower().startswith("paper_figure_")
                    or state.component_id.lower() == "ams_lite_empty_spool_spindle"
                )
                and self._overview_motion_is_plausible(
                    state.mask,
                    next_mask,
                    next_gray.shape,
                    quality,
                )
            ):
                # The overview demo tracks three independent image-space
                # objects.  Its semantic box is immutable only on the Qwen +
                # SAM keyframe; keeping that screen rectangle forever makes a
                # correctly moving LK mask fail containment on the very first
                # camera movement.  A RANSAC-supported, small, shape-preserving
                # motion is current-frame evidence, so advance the contract to
                # the propagated object before applying the quality gate.
                current_evidence_validated = True
            if (
                state.component_id.lower() == "a1_mini_build_plate"
                and quality >= 0.60
            ):
                # A high-quality LK/RANSAC propagation is the current-frame
                # evidence for the broad plate surface. Refresh its screen
                # contract before checking the separately tracked anomalies.
                current_evidence_validated = True
            if state.color_guard_enabled:
                if self._is_pen(state.component_id):
                    redetected = self._blue_pen_mask(image)
                elif self._is_filament_component(state.component_id):
                    propagated_box = self._mask_box(next_mask)
                    if propagated_box is None:
                        propagated_box = self._mask_box(state.mask)
                    if propagated_box is None:
                        propagated_box = state.prompt_box
                    filament_search_box = self._expanded_box(
                        propagated_box,
                        image.shape,
                        fraction=0.90,
                    )
                    redetected = self._refine_filament_mask(
                        image,
                        state.component_id,
                        filament_search_box,
                        candidate_mask=None,
                    )
                else:
                    propagated_box = self._mask_box(next_mask)
                    if propagated_box is None:
                        propagated_box = self._mask_box(state.mask)
                    if propagated_box is None:
                        propagated_box = state.prompt_box
                    search_box = self._expanded_anomaly_search_box(
                        propagated_box,
                        image.shape,
                        is_residue="residue" in state.component_id.lower(),
                    )
                    redetected = self._refine_plate_anomaly_mask(
                        image,
                        state.component_id,
                        search_box,
                        candidate_mask=None,
                        target_point_0_1000=self._box_center_0_1000(
                            propagated_box,
                            image.shape,
                        ),
                    )
                comparison_mask = (
                    next_mask
                    if self._is_plate_anomaly_component(state.component_id)
                    else state.mask
                )
                consistent = self._redetection_consistent(comparison_mask, redetected)
                if not consistent:
                    quality = 0.0
                elif self._is_filament_component(state.component_id):
                    # Use fresh image evidence on every sampled frame so a
                    # warped thin mask cannot grow into a background patch.
                    next_mask = redetected
                    quality = max(quality, 0.78)
                    current_evidence_validated = True
                elif self._is_plate_anomaly_component(state.component_id):
                    next_mask = redetected
                    quality = max(quality, 0.86)
                    current_evidence_validated = True
                elif quality < 0.35 or self._mask_iou(next_mask, redetected) < 0.15:
                    next_mask = redetected
                    quality = max(quality, 0.72)
                    current_evidence_validated = True

            next_mask, quality, resegmented = self._maybe_resegment(
                image,
                state,
                next_mask,
                quality,
            )
            if resegmented:
                state.relocalization_count += 1
                state.frames_since_resegmentation = 0
                current_evidence_validated = True

            if current_evidence_validated:
                self._refresh_tracking_contract(state, next_mask)

            next_centroid = self._mask_centroid(next_mask)
            if state.last_centroid is not None and next_centroid is not None:
                frame_diagonal = max(
                    1.0,
                    float(np.hypot(next_gray.shape[1], next_gray.shape[0])),
                )
                state.drift_ratio = float(
                    np.hypot(
                        next_centroid[0] - state.last_centroid[0],
                        next_centroid[1] - state.last_centroid[1],
                    )
                    / frame_diagonal
                )
            else:
                state.drift_ratio = 1.0
            state.last_centroid = next_centroid
            state.frame_index += 1

            state.gray = next_gray
            state.mask = next_mask
            state.points = self._sample_points(next_gray, next_mask)
            quality_passed, _, _, _ = self._mask_quality(state)
            if not quality_passed:
                quality = 0.0
            status = "tracking" if quality >= 0.35 else "lost"
            return self._describe(state, quality=quality, status=status)

    def _maybe_resegment(
        self,
        image: np.ndarray,
        state: _TrackingState,
        propagated_mask: np.ndarray,
        quality: float,
    ) -> tuple[np.ndarray, float, bool]:
        """Provider hook for periodic key-frame segmentation."""

        del image, state
        return propagated_mask, quality, False

    @staticmethod
    def _mask_centroid(mask: np.ndarray) -> tuple[float, float] | None:
        if cv2.countNonZero(mask) <= 0:
            return None
        moments = cv2.moments(mask)
        if moments["m00"] <= 0:
            return None
        return moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]

    @staticmethod
    def _mask_box(mask: np.ndarray) -> tuple[int, int, int, int] | None:
        if cv2.countNonZero(mask) <= 0:
            return None
        x, y, width, height = cv2.boundingRect(mask)
        return x, y, x + width, y + height

    @staticmethod
    def _expanded_box(
        box: tuple[int, int, int, int],
        shape: tuple[int, ...],
        fraction: float = 0.20,
    ) -> tuple[int, int, int, int]:
        height, width = shape[:2]
        x1, y1, x2, y2 = box
        pad_x = max(4, round((x2 - x1) * fraction))
        pad_y = max(4, round((y2 - y1) * fraction))
        return (
            max(0, x1 - pad_x),
            max(0, y1 - pad_y),
            min(width, x2 + pad_x),
            min(height, y2 + pad_y),
        )

    def close(self, session_id: str) -> bool:
        with self._lock:
            return self._states.pop(session_id, None) is not None

    @staticmethod
    def _decode(image_bytes: bytes) -> np.ndarray:
        image = cv2.imdecode(
            np.frombuffer(image_bytes, dtype=np.uint8),
            cv2.IMREAD_COLOR,
        )
        if image is None:
            raise ValueError("image_base64 is not a valid image")
        return image

    @staticmethod
    def _normalized_box_to_pixels(
        bbox: list[int],
        shape: tuple[int, ...],
    ) -> tuple[int, int, int, int]:
        height, width = shape[:2]
        x1 = max(0, min(width - 1, round(bbox[0] / 1000 * width)))
        y1 = max(0, min(height - 1, round(bbox[1] / 1000 * height)))
        x2 = max(x1 + 1, min(width, round(bbox[2] / 1000 * width)))
        y2 = max(y1 + 1, min(height, round(bbox[3] / 1000 * height)))
        return x1, y1, x2, y2

    def _initial_mask(
        self,
        image: np.ndarray,
        component_id: str,
        box: tuple[int, int, int, int],
        guidance_target: GuidanceTarget | None = None,
    ) -> np.ndarray:
        if self._is_pen(component_id):
            color_mask = self._blue_pen_mask(image)
            if cv2.countNonZero(color_mask) > 0:
                return color_mask

        if self._is_filament_component(component_id):
            filament_mask = self._refine_filament_mask(
                image,
                component_id,
                box,
                candidate_mask=None,
                target_point_0_1000=(
                    guidance_target.target_point_0_1000
                    if guidance_target is not None
                    else None
                ),
            )
            if cv2.countNonZero(filament_mask) > 0:
                return filament_mask

        if self._is_plate_anomaly_component(component_id):
            anomaly_mask = self._refine_plate_anomaly_mask(
                image,
                component_id,
                box,
                candidate_mask=None,
                target_point_0_1000=(
                    guidance_target.target_point_0_1000
                    if guidance_target is not None
                    else None
                ),
            )
            if cv2.countNonZero(anomaly_mask) > 0:
                return anomaly_mask

        foreground_mask = self._grabcut_mask(image, box)
        if cv2.countNonZero(foreground_mask) > 0:
            return foreground_mask

        # For exact small AMS controls, a detector rectangle is never a valid
        # segmentation. Broad legacy demo objects may retain a conservative
        # box fallback so older non-safety examples remain inspectable.
        if self._is_small_component(component_id):
            return np.zeros(image.shape[:2], dtype=np.uint8)
        mask = np.zeros(image.shape[:2], dtype=np.uint8)
        x1, y1, x2, y2 = box
        mask[y1:y2, x1:x2] = 255
        return mask

    @staticmethod
    def _is_small_component(component_id: str) -> bool:
        value = component_id.lower()
        return any(
            marker in value
            for marker in (
                "送料口",
                "进料口",
                "release button",
                "释放按钮",
                "料盘轴",
                "spindle",
                "inlet",
                "filament_tip",
                "inserted_filament",
                "ptfe_filament",
            )
        )

    @staticmethod
    def _is_filament_component(component_id: str) -> bool:
        value = component_id.lower()
        return any(
            marker in value
            for marker in (
                "filament_tip",
                "inserted_filament",
                "ptfe_filament",
            )
        )

    @staticmethod
    def _is_plate_anomaly_component(component_id: str) -> bool:
        value = component_id.lower()
        return "a1_mini_build_plate_" in value and any(
            marker in value for marker in ("foreign_object", "residue")
        )

    @classmethod
    def _refine_plate_anomaly_mask(
        cls,
        image: np.ndarray,
        component_id: str,
        box: tuple[int, int, int, int],
        candidate_mask: np.ndarray | None,
        target_point_0_1000: list[int] | None = None,
    ) -> np.ndarray:
        """Constrain a SAM anomaly mask to current-frame orange foreground."""

        empty = np.zeros(image.shape[:2], dtype=np.uint8)
        if not cls._is_plate_anomaly_component(component_id):
            return candidate_mask if candidate_mask is not None else empty
        blue, green, red = cv2.split(image)
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        hue, saturation, value = cv2.split(hsv)
        red_f = red.astype(np.float32)
        green_f = green.astype(np.float32)
        blue_f = blue.astype(np.float32)
        orange = (
            (hue <= 32)
            # The A1 build plate itself is warm gold and can satisfy a loose
            # orange hue test. The controlled orange block/residue has much
            # stronger chroma, so reject the plate texture before connected
            # component selection.
            & (saturation >= 100)
            & (value >= 65)
            & (red >= 120)
            & (red_f >= green_f * 1.16)
            & (red_f >= blue_f * 1.28)
        )
        x1, y1, x2, y2 = box
        region = np.zeros_like(empty)
        region[y1:y2, x1:x2] = 255
        mask = cv2.bitwise_and(np.where(orange, 255, 0).astype(np.uint8), region)
        if candidate_mask is not None:
            nearby_sam = cv2.dilate(
                candidate_mask,
                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11)),
                iterations=1,
            )
            mask = cv2.bitwise_and(mask, nearby_sam)
        kernel = (3, 3) if "residue" in component_id.lower() else (7, 7)
        mask = cv2.morphologyEx(
            mask,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, kernel),
            iterations=1,
        )
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        if count <= 1:
            return empty
        target_x = target_y = None
        if target_point_0_1000 is not None:
            target_x = target_point_0_1000[0] / 1000 * image.shape[1]
            target_y = target_point_0_1000[1] / 1000 * image.shape[0]
        best_label = 0
        best_score = float("-inf")
        for label in range(1, count):
            area = int(stats[label, cv2.CC_STAT_AREA])
            minimum_area = 3 if "residue" in component_id.lower() else 18
            if area < minimum_area:
                continue
            center_x = stats[label, cv2.CC_STAT_LEFT] + stats[label, cv2.CC_STAT_WIDTH] / 2
            center_y = stats[label, cv2.CC_STAT_TOP] + stats[label, cv2.CC_STAT_HEIGHT] / 2
            distance = 0.0
            if target_x is not None and target_y is not None:
                distance = float(np.hypot(center_x - target_x, center_y - target_y))
            score = area - distance * (22.0 if "residue" in component_id.lower() else 2.0)
            if score > best_score:
                best_score = score
                best_label = label
        if best_label == 0:
            return empty
        selected = np.where(labels == best_label, 255, 0).astype(np.uint8)
        return cv2.dilate(
            selected,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
            iterations=1,
        )

    @staticmethod
    def _box_center_0_1000(
        box: tuple[int, int, int, int],
        shape: tuple[int, ...],
    ) -> list[int]:
        height, width = shape[:2]
        return [
            round((box[0] + box[2]) * 0.5 / max(1, width) * 1000),
            round((box[1] + box[3]) * 0.5 / max(1, height) * 1000),
        ]

    @staticmethod
    def _expanded_anomaly_search_box(
        box: tuple[int, int, int, int],
        shape: tuple[int, ...],
        *,
        is_residue: bool,
    ) -> tuple[int, int, int, int]:
        """Keep orange re-detection local to the propagated physical target.

        Residue is a very thin strip, so it gets extra vertical tolerance while
        remaining narrow in X. This prevents it from jumping to the much larger
        orange calibration block elsewhere on the plate.
        """

        height, width = shape[:2]
        x1, y1, x2, y2 = box
        box_width = max(1, x2 - x1)
        box_height = max(1, y2 - y1)
        if is_residue:
            pad_x = max(55, round(box_width * 0.35))
            pad_y = max(45, round(box_height * 2.5))
        else:
            pad_x = max(36, round(box_width * 0.35))
            pad_y = max(36, round(box_height * 0.35))
        return (
            max(0, x1 - pad_x),
            max(0, y1 - pad_y),
            min(width, x2 + pad_x),
            min(height, y2 + pad_y),
        )

    @classmethod
    def _refresh_tracking_contract(cls, state: _TrackingState, mask: np.ndarray) -> None:
        box = cls._mask_box(mask)
        centroid = cls._mask_centroid(mask)
        if box is None or centroid is None:
            return
        state.semantic_box = box
        if state.guidance_target is not None:
            height, width = mask.shape[:2]
            updates = {
                "target_point_0_1000": [
                    round(centroid[0] / max(1, width) * 1000),
                    round(centroid[1] / max(1, height) * 1000),
                ]
            }
            if cls._is_plate_anomaly_component(state.component_id):
                # These screen-space exclusions were compiled on the keyframe.
                # The current orange evidence plus the Unity plate-containment
                # gate replaces them after a validated camera movement.
                updates["forbidden_regions_0_1000"] = []
            state.guidance_target = state.guidance_target.model_copy(
                update=updates
            )

    @classmethod
    def _overview_motion_is_plausible(
        cls,
        previous_mask: np.ndarray,
        current_mask: np.ndarray,
        frame_shape: tuple[int, ...],
        quality: float,
    ) -> bool:
        """Accept only conservative LK/RANSAC motion for paper overview parts.

        This is deliberately stricter than the generic tracker: refreshing the
        semantic contract prevents false losses, but must not legitimize a mask
        that has jumped to a neighbouring AMS Lite part.
        """

        if quality < 0.38:
            return False
        previous_area = cv2.countNonZero(previous_mask)
        current_area = cv2.countNonZero(current_mask)
        if previous_area <= 0 or current_area <= 0:
            return False
        area_ratio = current_area / previous_area
        if area_ratio < 0.72 or area_ratio > 1.38:
            return False

        previous_box = cls._mask_box(previous_mask)
        current_box = cls._mask_box(current_mask)
        previous_centroid = cls._mask_centroid(previous_mask)
        current_centroid = cls._mask_centroid(current_mask)
        if (
            previous_box is None
            or current_box is None
            or previous_centroid is None
            or current_centroid is None
        ):
            return False

        previous_width = max(1, previous_box[2] - previous_box[0])
        previous_height = max(1, previous_box[3] - previous_box[1])
        current_width = max(1, current_box[2] - current_box[0])
        current_height = max(1, current_box[3] - current_box[1])
        if not (0.72 <= current_width / previous_width <= 1.38):
            return False
        if not (0.72 <= current_height / previous_height <= 1.38):
            return False

        height, width = frame_shape[:2]
        frame_diagonal = max(1.0, float(np.hypot(width, height)))
        shift_ratio = float(
            np.hypot(
                current_centroid[0] - previous_centroid[0],
                current_centroid[1] - previous_centroid[1],
            )
            / frame_diagonal
        )
        return shift_ratio <= 0.10

    @classmethod
    def _refine_filament_mask(
        cls,
        image: np.ndarray,
        component_id: str,
        box: tuple[int, int, int, int],
        candidate_mask: np.ndarray | None,
        target_point_0_1000: list[int] | None = None,
    ) -> np.ndarray:
        """Keep only current-frame orange filament supported by the prompt.

        This is a task-profile refinement after semantic/SAM grounding, not a
        global color detector: pixels are accepted only inside the compiled
        Qwen box and, for SAM2, close to the SAM foreground hypothesis.
        """

        empty = np.zeros(image.shape[:2], dtype=np.uint8)
        if not cls._is_filament_component(component_id):
            return candidate_mask if candidate_mask is not None else empty

        blue, green, red = cv2.split(image)
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        hue, saturation, value = cv2.split(hsv)
        red_f = red.astype(np.float32)
        green_f = green.astype(np.float32)
        blue_f = blue.astype(np.float32)
        core = (
            (hue <= 28)
            & (saturation >= 80)
            & (value >= 70)
            & (red >= 120)
            & (red_f >= green_f * 1.14)
            & (red_f >= blue_f * 1.28)
        )
        support = (
            (hue <= 34)
            & (saturation >= 42)
            & (value >= 55)
            & (red >= 100)
            & (red_f >= green_f * 1.06)
            & (red_f >= blue_f * 1.16)
        )

        x1, y1, x2, y2 = box
        region = np.zeros_like(empty)
        region[y1:y2, x1:x2] = 255
        core_mask = np.where(core, 255, 0).astype(np.uint8)
        color_mask = np.where(support, 255, 0).astype(np.uint8)
        core_mask = cv2.bitwise_and(core_mask, region)
        color_mask = cv2.bitwise_and(color_mask, region)
        if candidate_mask is not None:
            nearby_sam = cv2.dilate(
                candidate_mask,
                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)),
                iterations=1,
            )
            core_mask = cv2.bitwise_and(core_mask, nearby_sam)
            color_mask = cv2.bitwise_and(color_mask, nearby_sam)
        color_mask = cv2.morphologyEx(
            color_mask,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
            iterations=1,
        )
        count, labels, stats, _ = cv2.connectedComponentsWithStats(
            color_mask,
            connectivity=8,
        )
        best_label = 0
        best_score = float("-inf")
        target_x = target_y = None
        if target_point_0_1000 is not None:
            target_x = round(target_point_0_1000[0] / 1000 * image.shape[1])
            target_y = round(target_point_0_1000[1] / 1000 * image.shape[0])
        for label in range(1, count):
            component = np.where(labels == label, 255, 0).astype(np.uint8)
            core_overlap = cv2.countNonZero(cv2.bitwise_and(component, core_mask))
            area = int(stats[label, cv2.CC_STAT_AREA])
            if core_overlap < 2 or area < 3:
                continue
            score = float(core_overlap * 4 + area)
            if target_x is not None and target_y is not None:
                component_points = cv2.findNonZero(component)
                if component_points is not None:
                    delta = component_points.reshape(-1, 2).astype(np.float32)
                    delta[:, 0] -= target_x
                    delta[:, 1] -= target_y
                    distance = float(np.sqrt(np.min(np.sum(delta * delta, axis=1))))
                    score -= distance * 12.0
                    if distance <= 5.0:
                        score += 10000.0
            if score > best_score:
                best_score = score
                best_label = label
        if best_label == 0:
            return empty
        selected = np.where(labels == best_label, 255, 0).astype(np.uint8)
        return cv2.dilate(
            selected,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
            iterations=1,
        )

    @classmethod
    def _mask_quality(
        cls,
        state: _TrackingState,
    ) -> tuple[bool, list[str], float, float]:
        mask = state.mask
        height, width = mask.shape
        mask_area = cv2.countNonZero(mask)
        frame_area = max(1, height * width)
        area_ratio = mask_area / frame_area
        reasons: list[str] = []
        if mask_area <= 0:
            return False, ["segmentation_empty"], 0.0, 0.0

        x1, y1, x2, y2 = state.semantic_box
        prompt = np.zeros_like(mask)
        prompt[y1:y2, x1:x2] = 255
        inside = cv2.countNonZero(cv2.bitwise_and(mask, prompt))
        prompt_containment = inside / max(1, mask_area)
        target_point = (
            state.guidance_target.target_point_0_1000
            if state.guidance_target is not None
            else None
        )
        if target_point is not None:
            center_x = min(width - 1, max(0, round(target_point[0] / 1000 * width)))
            center_y = min(height - 1, max(0, round(target_point[1] / 1000 * height)))
        else:
            center_x = min(width - 1, max(0, round((x1 + x2) / 2)))
            center_y = min(height - 1, max(0, round((y1 + y2) / 2)))
        is_spindle = any(
            marker in state.component_id.lower()
            for marker in (
                "料盘轴",
                "spindle",
                "spool axis",
            )
        )
        # A spindle is an annular / partly hollow target in most handheld
        # views.  The semantic point commonly lands in the hole even when the
        # visible spindle surface is segmented correctly.  Treat every
        # explicitly named spindle as an assembly target; requiring the VLM to
        # emit the exact suffix "总成" made otherwise correct masks disappear.
        requires_whole_assembly = is_spindle
        center_is_supported = mask[center_y, center_x] != 0
        if not center_is_supported:
            # The semantic target point is only a prompt, not a guarantee that
            # the target is solid at that pixel. AMS Lite spool spindles and
            # feeder inlets are annular: a correct mask can surround a real
            # hole while its centre pixel remains background. Accept nearby
            # foreground support, while a genuinely remote point still fails.
            prompt_span = max(1, min(x2 - x1, y2 - y1))
            support_ratio = 0.30 if requires_whole_assembly else 0.08
            radius = max(4, round(prompt_span * support_ratio))
            local = mask[
                max(0, center_y - radius) : min(height, center_y + radius + 1),
                max(0, center_x - radius) : min(width, center_x + radius + 1),
            ]
            center_is_supported = cv2.countNonZero(local) > 0
        if not center_is_supported:
            reasons.append("target_point_not_inside_mask")
        if prompt_containment < 0.60:
            reasons.append("mask_leaves_prompt_region")
        if (
            state.component_id.lower().startswith("paper_figure_")
            and prompt_containment < 0.86
        ):
            reasons.append("overview_mask_leaves_semantic_box")
        if (
            state.component_id.lower() == "ams_lite_empty_spool_spindle"
            and prompt_containment < 0.90
        ):
            reasons.append("slot4_mask_leaves_semantic_box")

        if state.guidance_target is not None:
            if area_ratio < state.guidance_target.expected_area_ratio_min:
                reasons.append("mask_smaller_than_expected_target")
            if area_ratio > state.guidance_target.expected_area_ratio_max:
                reasons.append("mask_larger_than_expected_target")
            for region in state.guidance_target.forbidden_regions_0_1000:
                fx1 = max(0, min(width, round(region[0] / 1000 * width)))
                fy1 = max(0, min(height, round(region[1] / 1000 * height)))
                fx2 = max(0, min(width, round(region[2] / 1000 * width)))
                fy2 = max(0, min(height, round(region[3] / 1000 * height)))
                overlap = cv2.countNonZero(mask[fy1:fy2, fx1:fx2])
                if overlap / max(1, mask_area) > 0.08:
                    reasons.append("mask_crosses_forbidden_component_region")
                    break

        prompt_area = max(1, (x2 - x1) * (y2 - y1))
        prompt_coverage = inside / prompt_area
        if requires_whole_assembly and prompt_coverage < 0.08:
            # Reject a detached fragment, but do not require a handheld view to
            # expose hidden/back surfaces of a spindle. The UI must describe
            # the result as the currently visible surface, not full 3-D coverage.
            reasons.append("whole_assembly_mask_incomplete")
        if cls._is_small_component(state.component_id):
            # A complete visible spindle assembly is intentionally broader
            # than a tiny inlet/button. Keep the strict 12% cap for those
            # controls, while allowing an explicitly requested assembly to
            # occupy up to the target contract's own maximum area.
            small_area_max = (
                state.guidance_target.expected_area_ratio_max
                if requires_whole_assembly and state.guidance_target is not None
                else 0.12
            )
            if area_ratio > small_area_max:
                reasons.append("small_component_mask_too_large")
            if mask_area > prompt_area * 4.0:
                reasons.append("mask_exceeds_small_component_prompt")
        elif area_ratio > 0.55:
            reasons.append("mask_covers_too_much_of_frame")
        return not reasons, reasons, area_ratio, prompt_containment

    @staticmethod
    def _grabcut_mask(
        image: np.ndarray,
        box: tuple[int, int, int, int],
    ) -> np.ndarray:
        """Convert a loose detector box into a conservative foreground mask."""

        height, width = image.shape[:2]
        x1, y1, x2, y2 = box
        x1 = max(0, min(width - 2, x1))
        y1 = max(0, min(height - 2, y1))
        x2 = max(x1 + 2, min(width, x2))
        y2 = max(y1 + 2, min(height, y2))
        prompt_area = max(1, (x2 - x1) * (y2 - y1))

        labels = np.full(
            (height, width),
            cv2.GC_BGD,
            dtype=np.uint8,
        )
        labels[y1:y2, x1:x2] = cv2.GC_PR_BGD
        inset_x = max(1, round((x2 - x1) * 0.12))
        inset_y = max(1, round((y2 - y1) * 0.12))
        labels[
            y1 + inset_y : y2 - inset_y,
            x1 + inset_x : x2 - inset_x,
        ] = cv2.GC_PR_FGD
        background_model = np.zeros((1, 65), dtype=np.float64)
        foreground_model = np.zeros((1, 65), dtype=np.float64)
        try:
            cv2.grabCut(
                image,
                labels,
                None,
                background_model,
                foreground_model,
                3,
                cv2.GC_INIT_WITH_MASK,
            )
        except cv2.error:
            return np.zeros((height, width), dtype=np.uint8)

        candidate = np.where(
            (labels == cv2.GC_FGD) | (labels == cv2.GC_PR_FGD),
            255,
            0,
        ).astype(np.uint8)
        candidate = cv2.morphologyEx(
            candidate,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)),
        )
        contours, _ = cv2.findContours(
            candidate,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        if not contours:
            return np.zeros((height, width), dtype=np.uint8)

        contour = max(contours, key=cv2.contourArea)
        contour_area = cv2.contourArea(contour)
        # Reject degenerate and near-full-box results. A rectangle fallback is
        # preferable to presenting a broken mask as successful segmentation.
        if contour_area < prompt_area * 0.03 or contour_area > prompt_area * 0.90:
            return np.zeros((height, width), dtype=np.uint8)

        result = np.zeros((height, width), dtype=np.uint8)
        cv2.drawContours(result, [contour], -1, 255, thickness=-1)
        return result

    @staticmethod
    def _is_pen(component_id: str) -> bool:
        value = component_id.lower()
        return "笔" in value or "pen" in value

    @staticmethod
    def _blue_pen_mask(image: np.ndarray) -> np.ndarray:
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(
            hsv,
            np.array([35, 40, 35], dtype=np.uint8),
            np.array([85, 255, 255], dtype=np.uint8),
        )
        mask = cv2.morphologyEx(
            mask,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
        )
        mask = cv2.morphologyEx(
            mask,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (21, 7)),
        )
        contours, _ = cv2.findContours(
            mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        if not contours:
            return np.zeros(image.shape[:2], dtype=np.uint8)
        contours = sorted(contours, key=cv2.contourArea, reverse=True)
        selected = [contours[0]]
        merged_box = cv2.boundingRect(contours[0])
        for contour in contours[1:]:
            candidate_box = cv2.boundingRect(contour)
            if OpenCvMaskTracker._collinear_boxes(merged_box, candidate_box):
                selected.append(contour)
                x1 = min(merged_box[0], candidate_box[0])
                y1 = min(merged_box[1], candidate_box[1])
                x2 = max(
                    merged_box[0] + merged_box[2],
                    candidate_box[0] + candidate_box[2],
                )
                y2 = max(
                    merged_box[1] + merged_box[3],
                    candidate_box[1] + candidate_box[3],
                )
                merged_box = (x1, y1, x2 - x1, y2 - y1)
        contour = cv2.convexHull(np.vstack(selected))
        result = np.zeros(image.shape[:2], dtype=np.uint8)
        cv2.drawContours(result, [contour], -1, 255, thickness=-1)
        return result

    @staticmethod
    def _collinear_boxes(
        left: tuple[int, int, int, int],
        right: tuple[int, int, int, int],
    ) -> bool:
        left_x, left_y, left_width, left_height = left
        right_x, right_y, right_width, right_height = right
        left_horizontal = left_width >= left_height
        right_horizontal = right_width >= right_height
        if left_horizontal != right_horizontal:
            return False
        if left_horizontal:
            perpendicular_offset = abs(
                left_y + left_height / 2 - right_y - right_height / 2
            )
            gap = max(
                0,
                max(left_x, right_x)
                - min(left_x + left_width, right_x + right_width),
            )
            thickness = max(left_height, right_height)
            length = max(left_width, right_width)
        else:
            perpendicular_offset = abs(
                left_x + left_width / 2 - right_x - right_width / 2
            )
            gap = max(
                0,
                max(left_y, right_y)
                - min(left_y + left_height, right_y + right_height),
            )
            thickness = max(left_width, right_width)
            length = max(left_height, right_height)
        return bool(
            perpendicular_offset <= max(8.0, thickness * 0.85)
            and gap <= max(45.0, length * 0.75)
        )

    @staticmethod
    def _redetection_consistent(
        previous_mask: np.ndarray,
        candidate_mask: np.ndarray,
    ) -> bool:
        previous_area = cv2.countNonZero(previous_mask)
        candidate_area = cv2.countNonZero(candidate_mask)
        if previous_area <= 0 or candidate_area <= 0:
            return False
        area_ratio = candidate_area / previous_area
        if area_ratio < 0.35 or area_ratio > 2.8:
            return False

        previous_x, previous_y, previous_width, previous_height = cv2.boundingRect(
            previous_mask
        )
        candidate_x, candidate_y, candidate_width, candidate_height = cv2.boundingRect(
            candidate_mask
        )
        previous_center = np.array(
            [
                previous_x + previous_width / 2.0,
                previous_y + previous_height / 2.0,
            ]
        )
        candidate_center = np.array(
            [
                candidate_x + candidate_width / 2.0,
                candidate_y + candidate_height / 2.0,
            ]
        )
        maximum_shift = max(
            40.0,
            1.5 * max(previous_width, previous_height),
        )
        return bool(np.linalg.norm(candidate_center - previous_center) <= maximum_shift)

    @staticmethod
    def _mask_iou(left: np.ndarray, right: np.ndarray) -> float:
        intersection = cv2.countNonZero(cv2.bitwise_and(left, right))
        union = cv2.countNonZero(cv2.bitwise_or(left, right))
        return intersection / union if union else 0.0

    @staticmethod
    def _sample_points(gray: np.ndarray, mask: np.ndarray) -> np.ndarray | None:
        points = cv2.goodFeaturesToTrack(
            gray,
            maxCorners=160,
            qualityLevel=0.005,
            minDistance=4,
            mask=mask,
            blockSize=5,
        )
        if points is not None and len(points) >= 4:
            return points.astype(np.float32)

        ys, xs = np.nonzero(mask)
        if len(xs) == 0:
            return None
        indices = np.linspace(0, len(xs) - 1, min(24, len(xs))).astype(int)
        return np.stack([xs[indices], ys[indices]], axis=1).reshape(-1, 1, 2).astype(
            np.float32
        )

    @staticmethod
    def _propagate(
        state: _TrackingState,
        next_gray: np.ndarray,
    ) -> tuple[np.ndarray, float]:
        if state.points is None or len(state.points) < 3:
            return state.mask.copy(), 0.0
        next_points, status, error = cv2.calcOpticalFlowPyrLK(
            state.gray,
            next_gray,
            state.points,
            None,
            winSize=(31, 31),
            maxLevel=3,
            criteria=(
                cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
                30,
                0.01,
            ),
        )
        if next_points is None or status is None:
            return state.mask.copy(), 0.0
        valid = status.reshape(-1).astype(bool)
        if error is not None:
            valid &= error.reshape(-1) < 35.0
        previous = state.points.reshape(-1, 2)[valid]
        current = next_points.reshape(-1, 2)[valid]
        if len(previous) < 3:
            return state.mask.copy(), len(previous) / max(1, len(state.points))

        matrix, inliers = cv2.estimateAffinePartial2D(
            previous,
            current,
            method=cv2.RANSAC,
            ransacReprojThreshold=4.0,
        )
        if matrix is None:
            return state.mask.copy(), 0.0
        height, width = next_gray.shape[:2]
        propagated = cv2.warpAffine(
            state.mask,
            matrix,
            (width, height),
            flags=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        )
        inlier_ratio = (
            float(np.mean(inliers.reshape(-1))) if inliers is not None else 0.5
        )
        visible_ratio = cv2.countNonZero(propagated) / max(
            1,
            cv2.countNonZero(state.mask),
        )
        quality = max(0.0, min(1.0, inlier_ratio * min(1.0, visible_ratio)))
        return propagated, quality

    def _describe(
        self,
        state: _TrackingState,
        quality: float,
        status: str,
    ) -> TrackedComponent:
        height, width = state.mask.shape
        quality_passed, quality_reasons, area_ratio, prompt_containment = (
            self._mask_quality(state)
        )
        contours, _ = cv2.findContours(
            state.mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        if not contours:
            return TrackedComponent(
                component_id=state.component_id,
                status="lost",
                quality=0.0,
                bbox_0_1000=[0, 0, 1, 1],
                polygon_0_1000=[],
                centroid_0_1000=[0, 0],
                overlay_png_base64="",
                provider=self.provider_name,
                requires_redetection=True,
                mask_quality_passed=False,
                mask_quality_reasons=quality_reasons,
                mask_area_ratio=round(area_ratio, 4),
                prompt_containment=round(prompt_containment, 4),
                overlay_semantic="insufficient",
                frame_index=state.frame_index,
                world_anchor_status="client_pending",
                drift_ratio=round(state.drift_ratio, 4),
                relocalization_count=state.relocalization_count,
            )
        contour = max(contours, key=cv2.contourArea)
        x, y, box_width, box_height = cv2.boundingRect(contour)
        epsilon = max(1.0, 0.01 * cv2.arcLength(contour, True))
        polygon = cv2.approxPolyDP(contour, epsilon, True).reshape(-1, 2)
        moments = cv2.moments(contour)
        center_x = (
            moments["m10"] / moments["m00"] if moments["m00"] else x + box_width / 2
        )
        center_y = (
            moments["m01"] / moments["m00"] if moments["m00"] else y + box_height / 2
        )
        overlay = np.zeros((height, width, 4), dtype=np.uint8)
        # OpenCV encodes PNG as BGRA. Cyan denotes the next action target.  The
        # alpha is high enough for paper/demo screenshots while keeping the
        # physical holder visible underneath.
        if quality_passed:
            overlay[state.mask > 0] = [233, 215, 22, 130]
        success, encoded = cv2.imencode(".png", overlay)
        overlay_base64 = (
            base64.b64encode(encoded.tobytes()).decode("ascii") if success else ""
        )
        return TrackedComponent(
            component_id=state.component_id,
            status=status if quality_passed else "lost",
            quality=round(float(quality if quality_passed else 0.0), 4),
            bbox_0_1000=[
                round(x / width * 1000),
                round(y / height * 1000),
                round((x + box_width) / width * 1000),
                round((y + box_height) / height * 1000),
            ],
            polygon_0_1000=[
                [round(px / width * 1000), round(py / height * 1000)]
                for px, py in polygon
            ],
            centroid_0_1000=[
                round(center_x / width * 1000),
                round(center_y / height * 1000),
            ],
            overlay_png_base64=overlay_base64,
            provider=self.provider_name,
            requires_redetection=(
                status == "lost" or quality < 0.35 or not quality_passed
            ),
            mask_quality_passed=quality_passed,
            mask_quality_reasons=quality_reasons,
            mask_area_ratio=round(area_ratio, 4),
            prompt_containment=round(prompt_containment, 4),
            overlay_semantic=("next_action" if quality_passed else "insufficient"),
            frame_index=state.frame_index,
            world_anchor_status="client_pending",
            drift_ratio=round(state.drift_ratio, 4),
            relocalization_count=state.relocalization_count,
        )


def decode_base64_image(value: str) -> bytes:
    try:
        payload = base64.b64decode(value, validate=True)
        with Image.open(io.BytesIO(payload)) as image:
            image.verify()
        return payload
    except (ValueError, OSError) as exc:
        raise ValueError("image_base64 is not a valid image") from exc
