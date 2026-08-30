from __future__ import annotations

import base64
import hashlib
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_ROOT = (
    PROJECT_ROOT
    / "examples"
    / "bambu_a1_mini_plate_inspection_v1"
    / "references"
)
FILAMENT_LOADING_REFERENCE_ROOT = (
    PROJECT_ROOT
    / "examples"
    / "bambu_ams_lite_filament_loading_v1"
    / "references"
)


@dataclass(frozen=True)
class AnomalySegmentationPolicy:
    anomaly_type: Literal["foreign_object", "residue"]
    expected_area_ratio_min: float
    expected_area_ratio_max: float
    minimum_box_overlap_with_plate: float
    minimum_mask_containment_in_plate: float
    minimum_current_frame_orange_ratio: float
    correction_instruction: str


@dataclass(frozen=True)
class TaskVisionProfile:
    profile_id: str
    profile_version: str
    prompt_version: str
    method_label: str
    device_description: str
    allowed_target: str
    excluded_visuals: tuple[str, ...]
    clean_reference_path: Path
    dirty_reference_path: Path
    plate_area_ratio_min: float
    plate_area_ratio_max: float
    minimum_plate_confidence: float
    anomaly_policies: dict[str, AnomalySegmentationPolicy]
    display_predicates: tuple[str, ...]
    internal_predicates: tuple[str, ...]

    def reference_hashes(self) -> dict[str, str]:
        return {
            "clean_p2_sha256": _sha256(self.clean_reference_path),
            "dirty_p1_sha256": _sha256(self.dirty_reference_path),
        }

    def ordered_reference_images_base64(self) -> list[str]:
        """Return P2 then P1; the caller always prepends the current frame."""
        return [
            _labeled_reference(self.clean_reference_path, "IMAGE 2 · CLEAN P2 REFERENCE"),
            _labeled_reference(self.dirty_reference_path, "IMAGE 3 · DIRTY P1 REFERENCE"),
        ]


@dataclass(frozen=True)
class FilamentLoadingVisionProfile:
    profile_id: str
    profile_version: str
    prompt_version: str
    method_label: str
    device_description: str
    loaded_reference_path: Path
    not_inserted_reference_path: Path
    minimum_state_confidence: float
    object_area_limits: dict[str, tuple[float, float]]

    def reference_hashes(self) -> dict[str, str]:
        return {
            "loaded_sha256": _sha256(self.loaded_reference_path),
            "not_inserted_sha256": _sha256(self.not_inserted_reference_path),
        }

    def ordered_reference_images_base64(self) -> list[str]:
        """Return loaded then not-inserted exemplars after the current frame."""
        return [
            _labeled_reference(
                self.loaded_reference_path,
                "IMAGE 2 · LOADED REFERENCE · FILAMENT ENTERS FEEDER AND PTFE",
            ),
            _labeled_reference(
                self.not_inserted_reference_path,
                "IMAGE 3 · NOT INSERTED REFERENCE · LOOSE FILAMENT TIP",
            ),
        ]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _labeled_reference(path: Path, label: str) -> str:
    """Burn an identity banner into exemplars to reduce cross-image leakage."""
    with Image.open(path) as source:
        source = source.convert("RGB")
        banner_height = max(54, source.height // 18)
        labeled = Image.new("RGB", (source.width, source.height + banner_height), (8, 20, 28))
        labeled.paste(source, (0, banner_height))
        draw = ImageDraw.Draw(labeled)
        draw.text(
            (20, banner_height // 2),
            label,
            fill=(40, 225, 245),
            font=ImageFont.load_default(size=max(14, banner_height // 3)),
            anchor="lm",
        )
        buffer = io.BytesIO()
        labeled.save(buffer, format="JPEG", quality=90)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


PREPRINT_PLATE_INSPECTION_V1 = TaskVisionProfile(
    profile_id="preprint_plate_inspection_v1",
    profile_version="1.0.0",
    prompt_version="preprint-plate-qwen-v1.0.0",
    method_label=(
        "manual-compiled task-conditioned vision profile + "
        "constraint-guided segmentation prompt compilation"
    ),
    device_description=(
        "Bambu Lab A1 mini viewed from above. Its removable build plate is the "
        "large gold/brown rectangular textured metal sheet inside the printer frame."
    ),
    allowed_target=(
        "Only the visible gold textured A1 mini build plate and material physically "
        "resting on its surface or attached to its visible edge."
    ),
    excluded_visuals=(
        "orange scraps in the purge/waste box outside the plate",
        "the plate's normal gold texture and engraved calibration lines",
        "black pull tabs and dark edge hardware",
        "shadows, reflections, the printer base, and the surrounding table",
    ),
    clean_reference_path=REFERENCE_ROOT / "p2_clean_build_plate.jpg",
    dirty_reference_path=REFERENCE_ROOT / "p1_foreign_object_and_residue.jpg",
    plate_area_ratio_min=0.07,
    plate_area_ratio_max=0.58,
    minimum_plate_confidence=0.75,
    anomaly_policies={
        "foreign_object": AnomalySegmentationPolicy(
            anomaly_type="foreign_object",
            expected_area_ratio_min=0.0015,
            expected_area_ratio_max=0.075,
            minimum_box_overlap_with_plate=0.72,
            minimum_mask_containment_in_plate=0.82,
            minimum_current_frame_orange_ratio=0.12,
            correction_instruction="REMOVE FOREIGN OBJECT",
        ),
        "residue": AnomalySegmentationPolicy(
            anomaly_type="residue",
            expected_area_ratio_min=0.00012,
            expected_area_ratio_max=0.025,
            minimum_box_overlap_with_plate=0.64,
            minimum_mask_containment_in_plate=0.72,
            minimum_current_frame_orange_ratio=0.10,
            correction_instruction="CLEAN BUILD PLATE BEFORE PRINTING",
        ),
    },
    display_predicates=("PLATE ALIGNED", "SURFACE CLEAR", "NO RESIDUE"),
    internal_predicates=(
        "plate_present",
        "plate_aligned",
        "surface_clear",
        "no_residue",
    ),
)


AMS_LITE_FILAMENT_LOADING_V1 = FilamentLoadingVisionProfile(
    profile_id="ams_lite_filament_loading_v1",
    profile_version="1.0.0",
    prompt_version="ams-lite-filament-loading-qwen-v1.0.0",
    method_label=(
        "manual-compiled task-conditioned vision profile + "
        "constraint-guided segmentation prompt compilation"
    ),
    device_description=(
        "A close view of an AMS Lite spool and its dark translucent feeder module. "
        "The orange filament must enter the small inlet at the feeder's lower edge "
        "and continue through the gray PTFE tube leaving the feeder at the top."
    ),
    loaded_reference_path=(
        FILAMENT_LOADING_REFERENCE_ROOT / "loaded_filament_reference.jpg"
    ),
    not_inserted_reference_path=(
        FILAMENT_LOADING_REFERENCE_ROOT / "loose_filament_tip_reference.jpg"
    ),
    minimum_state_confidence=0.68,
    object_area_limits={
        "feeder_module": (0.012, 0.34),
        "filament_tip": (0.000015, 0.030),
        "inserted_filament": (0.000015, 0.045),
        "ptfe_filament": (0.00002, 0.080),
    },
)


def load_task_vision_profile(profile_id: str) -> TaskVisionProfile:
    if profile_id != PREPRINT_PLATE_INSPECTION_V1.profile_id:
        raise ValueError(f"unknown task vision profile: {profile_id}")
    profile = PREPRINT_PLATE_INSPECTION_V1
    missing = [
        str(path)
        for path in (profile.clean_reference_path, profile.dirty_reference_path)
        if not path.is_file()
    ]
    if missing:
        raise ValueError("task vision profile reference image is missing: " + ", ".join(missing))
    return profile


def load_filament_loading_profile(profile_id: str) -> FilamentLoadingVisionProfile:
    if profile_id != AMS_LITE_FILAMENT_LOADING_V1.profile_id:
        raise ValueError(f"unknown filament loading profile: {profile_id}")
    profile = AMS_LITE_FILAMENT_LOADING_V1
    missing = [
        str(path)
        for path in (
            profile.loaded_reference_path,
            profile.not_inserted_reference_path,
        )
        if not path.is_file()
    ]
    if missing:
        raise ValueError(
            "filament loading profile reference image is missing: " + ", ".join(missing)
        )
    return profile
