from __future__ import annotations

import base64
import io
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np
from PIL import Image, ImageOps
from pydantic import ValidationError
from pypdf import PdfReader

from .device_profiles import (
    DeviceProfile,
    DeviceProfileError,
    load_device_profile,
    profile_for_procedure,
)
from .ams_lite_tasks import (
    build_ams_lite_bundle,
    instantiate_ams_task,
)
from .grounding import DemoGrounder, PixelBox, rotate_jpeg_for_vlm
from .models import (
    AmsOverviewScanRequest,
    AmsOverviewScanResult,
    AmsSlotObservation,
    ComponentBox,
    EmptySpoolAxleCandidate,
    EmptySpoolAxleLocateRequest,
    ManualJob,
    MultiComponentLocateRequest,
    ManualTaskSelectionRequest,
    ManualTaskSelectionResult,
    PredicateEvidence,
    ProcedureDocument,
    SemanticComponentCandidate,
    SemanticComponentCandidateBatch,
    StateLocalizationRequest,
    StateLocalizationResult,
    VerificationRequest,
    VerificationResult,
)
from .ollama_client import OllamaError
from .vision_client import VisionClient


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[2]
OVERVIEW_HOLDER_EXEMPLAR_PATH = (
    BACKEND_ROOT
    / "output"
    / "latest_slot4_raw_verification_after_fix"
    / "67f2911e5d3e7b16c007d7e5d47240a5_raw_raw_20260826T134133Z"
    / "67f2911e5d3e7b16c007d7e5d47240a5_raw_raw_raw.jpg"
)
# Manual task-profile annotations in the exemplar image.  They are reference
# coordinates, never screen ROIs in a live frame.  RANSAC must prove their
# current-frame projection before they can become a SAM prompt.
OVERVIEW_EMPTY_HOLDER_EXEMPLAR_BOXES = (
    (245, 884, 430, 1044),
    (600, 884, 780, 1044),
)
# The accepted Slot 4 keyframe contains the actual upper-right empty white
# holder. This annotation is only projected after SIFT/RANSAC proves the
# current camera frame is geometrically compatible; it is not a live-screen
# fixed ROI. SAM2 still determines the current-frame visible surface pixels.
SLOT4_EMPTY_HOLDER_EXEMPLAR_BOX = (602, 157, 819, 334)
SLOT4_EMPTY_HOLDER_EXEMPLAR_POINT = (706, 225)
MOCK_PROCEDURE_PATH = (
    PROJECT_ROOT / "examples" / "proxy_book_v1" / "procedure.json"
)
HOME_MOCK_PROCEDURE_PATH = (
    PROJECT_ROOT / "examples" / "home_desk_kit_v1" / "procedure.json"
)
HOME_RELOCATION_MOCK_PROCEDURE_PATH = (
    PROJECT_ROOT
    / "examples"
    / "home_object_relocation_v1"
    / "procedure.json"
)
TWO_OBJECT_MOCK_PROCEDURE_PATH = (
    PROJECT_ROOT / "examples" / "two_object_book_pen_v1" / "procedure.json"
)
TRAINING_DATA_DIR = BACKEND_ROOT / "data" / "training_samples"
DEBUG_CAPTURE_DIR = BACKEND_ROOT / "data" / "debug_captures"
JOB_DATA_DIR = BACKEND_ROOT / "data" / "jobs"

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_MANUAL_PAGES = 8
MAX_IMAGE_SIDE = 1600
MAX_LIVE_IMAGE_SIDE = 1024
SAFE_ADVANCE_CONFIDENCE = 0.70


class ManualJobStore:
    def __init__(self, storage_dir: Path = JOB_DATA_DIR) -> None:
        self._jobs: dict[str, ManualJob] = {}
        self._lock = threading.Lock()
        self._storage_dir = storage_dir
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id: str) -> Path:
        # Job IDs are generated internally, but keep disk access constrained
        # even if a stale or malformed mobile client sends an arbitrary ID.
        safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", job_id)
        return self._storage_dir / f"{safe_id}.json"

    def _persist(self, job: ManualJob) -> None:
        path = self._path(job.job_id)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            job.model_dump_json(indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)

    def _load(self, job_id: str) -> ManualJob | None:
        path = self._path(job_id)
        if not path.is_file():
            return None
        try:
            return ManualJob.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError):
            # A corrupt cache must not prevent the backend from starting. The
            # caller can still use the explicit profile recovery path.
            return None

    def create(self) -> ManualJob:
        job = ManualJob(
            job_id=uuid.uuid4().hex,
            status="queued",
            stage="queued",
            progress=0.0,
        )
        with self._lock:
            self._jobs[job.job_id] = job
            self._persist(job)
        return job

    def get(self, job_id: str) -> ManualJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                job = self._load(job_id)
                if job is not None:
                    self._jobs[job_id] = job
            return job.model_copy(deep=True) if job else None

    def update(self, job_id: str, **changes: Any) -> None:
        with self._lock:
            current = self._jobs[job_id]
            updated = current.model_copy(update=changes)
            self._jobs[job_id] = updated
            self._persist(updated)

    def restore_completed(
        self,
        job_id: str,
        procedure: ProcedureDocument,
    ) -> ManualJob:
        job = ManualJob(
            job_id=job_id,
            status="completed",
            stage="completed",
            progress=1.0,
            procedure_id=job_id,
            procedure=procedure,
        )
        with self._lock:
            self._jobs[job_id] = job
            self._persist(job)
        return job.model_copy(deep=True)


class ManualService:
    def __init__(self) -> None:
        self.jobs = ManualJobStore()
        # Keep the historical attribute name so existing evaluation scripts
        # and monkeypatched tests remain compatible. The object itself is now
        # a provider switch for Qwen, local Ollama, or OpenAI Responses.
        self.ollama = VisionClient()
        self.grounder = DemoGrounder()
        self.save_debug_captures = os.getenv(
            "MANUAL2AR_SAVE_DEBUG_CAPTURES",
            "0",
        ).strip().lower() in {"1", "true", "yes", "on"}
        self._reference_image_cache: dict[str, str] = {}
        # Predicate completion is server-owned. Client-supplied retained IDs are
        # treated as display hints only and can never unlock a safety gate.
        self._verified_predicates: dict[tuple[str, str, str], set[str]] = {}

    def create_job(self) -> ManualJob:
        return self.jobs.create()

    def _get_or_recover_job(self, procedure_id: str) -> ManualJob | None:
        job = self.jobs.get(procedure_id)
        if job is not None:
            return job
        recovery_profile_id = os.getenv(
            "MANUAL2AR_RECOVERY_DEVICE_PROFILE",
            "",
        ).strip()
        if not recovery_profile_id:
            return None
        profile = load_device_profile(recovery_profile_id)
        if profile is None:
            return None
        procedure = self._normalize_procedure(profile.load_procedure("zh"))
        return self.jobs.restore_completed(procedure_id, procedure)

    def process_job(
        self,
        job_id: str,
        uploads: list[tuple[str, str, bytes]],
        mode: str,
        device_profile_id: str | None = None,
        guidance_language: str = "zh",
    ) -> None:
        try:
            bundle = None
            if device_profile_id == "bambu_a1_mini_ams_lite":
                bundle = build_ams_lite_bundle()

            self.jobs.update(
                job_id,
                status="running",
                stage="reading_pages",
                progress=0.15,
            )
            # Device profiles are explicit evaluation/safety baselines. Never
            # infer one from a filename: the generic import entry must exercise
            # the same automatic manual-to-state pipeline for every PDF,
            # including an A1 mini manual used in an ablation comparison.
            device_profile = load_device_profile(device_profile_id)
            if device_profile is not None:
                # The official manual is still uploaded and shown to the user,
                # while tomorrow's physical baseline uses an audited state graph
                # instead of letting a small zero-shot model silently invent
                # safety-critical steps. Live scene understanding remains VLM.
                procedure = device_profile.load_procedure(guidance_language)
            elif mode == "mock":
                procedure = self._load_mock_procedure(uploads)
            else:
                text, images = self._prepare_manual_inputs(uploads)
                self.jobs.update(
                    job_id,
                    stage="extracting_procedure",
                    progress=0.45,
                )
                procedure = self._analyze_with_ollama(
                    text,
                    images,
                    guidance_language=guidance_language,
                    on_constraint_repair=lambda: self.jobs.update(
                        job_id,
                        stage="building_constraints",
                        progress=0.72,
                    ),
                )

            self.jobs.update(
                job_id,
                stage="building_constraints",
                progress=0.85,
            )
            procedure = self._normalize_procedure(procedure)
            self.jobs.update(
                job_id,
                status="completed",
                stage="completed",
                progress=1.0,
                procedure_id=job_id,
                procedure=procedure,
                bundle_id=(f"{job_id}:ams-lite-bundle" if bundle else None),
                bundle=bundle,
                error=None,
            )
        except (
            ValueError,
            ValidationError,
            OllamaError,
            OSError,
            DeviceProfileError,
        ) as exc:
            self.jobs.update(
                job_id,
                status="failed",
                stage="failed",
                progress=1.0,
                error=str(exc),
            )

    def select_ams_task(
        self,
        job_id: str,
        request: ManualTaskSelectionRequest,
    ) -> ManualTaskSelectionResult:
        job = self.jobs.get(job_id)
        if job is None or job.status != "completed" or job.bundle is None:
            raise ValueError("Unknown or incomplete AMS Lite task bundle")
        selected = instantiate_ams_task(job.bundle, request)
        self.jobs.restore_completed(selected.procedure_id, selected.procedure)
        return selected

    def scan_ams_overview(
        self,
        request: AmsOverviewScanRequest,
    ) -> AmsOverviewScanResult:
        if request.mode == "mock":
            slots = [
                AmsSlotObservation(
                    slot_id=slot_id,
                    occupied="no",
                    spool_visible="no",
                    feeder_inlet_visible="yes",
                    filament_inserted="no",
                    ptfe_filament_visible="no",
                    confidence=0.95,
                    evidence=f"模拟结果：{slot_id}号槽为空。",
                )
                for slot_id in range(1, 5)
            ]
            return AmsOverviewScanResult(
                topology_valid=True,
                slots=slots,
                suggested_slot_id=3 if request.task_type == "load_spool" else None,
                suggestion_reason="模拟结果仅用于验证四槽选择界面。",
                requires_user_confirmation=True,
            )

        try:
            image_bytes = base64.b64decode(request.image_base64, validate=True)
            normalized = self._normalize_image(
                rotate_jpeg_for_vlm(image_bytes, request.image_rotation_degrees),
                MAX_LIVE_IMAGE_SIDE,
            )
        except (ValueError, OSError) as exc:
            raise ValueError("image_base64 is not a valid image") from exc

        prompt = (
            "Analyze one overview image of a Bambu Lab AMS Lite. Return exactly four "
            "physical slot observations. The embossed digits on the four feeder caps "
            "are the primary identity cue. The screen quadrant is NOT reliable under "
            "an oblique, overhead, mirrored, or rotated camera view. Use this immutable "
            "physical topology only after resolving those embossed digits: slot 1 is "
            "left-upper, slot 2 left-lower, slot 3 right-lower, slot 4 right-upper; "
            "the numbering is counterclockwise. Do not treat spool color as correctness. "
            "Record color only as optional visual metadata. Use uncertain for occluded "
            "spools, feeder inlets, filament insertion, or PTFE evidence. Never infer "
            "hidden loading from a nearby filament end. topology_valid means that the "
            "visible geometry is compatible with this mapping, not that every slot is "
            "visible. A slot with a visible spool disk mounted on its matching spindle "
            "is occupied even when the feeder inlet looks empty. For load_spool, suggest "
            "a slot only when BOTH occupied=no AND spool_visible=no are directly visible "
            "with confidence at least 0.72. For unload_spool or jam recovery require a "
            "directly visible spool. The suggestion is advisory and always needs user "
            "confirmation. Return JSON only.\n"
            f"TASK TYPE: {request.task_type}"
        )
        raw = self.ollama.chat_structured(
            prompt=prompt,
            schema=AmsOverviewScanResult.model_json_schema(),
            images_base64=[normalized],
            max_tokens=1100,
        )
        result = AmsOverviewScanResult.model_validate(raw)
        for slot in result.slots:
            # A mounted spool is stronger visible evidence than a possibly
            # occluded feeder opening. Never recommend that physical slot as
            # empty merely because the inlet itself appears clear.
            if slot.spool_visible == "yes":
                slot.occupied = "yes"
            elif slot.occupied == "no" and slot.spool_visible != "no":
                slot.occupied = "uncertain"

        eligible: list[int]
        if request.task_type == "load_spool":
            eligible = [
                slot.slot_id
                for slot in result.slots
                if slot.occupied == "no"
                and slot.spool_visible == "no"
                and slot.confidence >= 0.72
            ]
        else:
            eligible = [
                slot.slot_id
                for slot in result.slots
                if slot.occupied == "yes"
                and slot.spool_visible == "yes"
                and slot.confidence >= 0.72
            ]
        # The paper capture protocol prefers the lower-right slot because it
        # keeps the spindle and feeder module visible in one oblique view. This
        # is only a tie-breaker among slots directly observed as eligible; it
        # can never override occupancy evidence or user confirmation.
        preference = [3, 4, 2, 1] if request.task_type == "load_spool" else [1, 2, 3, 4]
        deterministic_suggestion = next(
            (slot_id for slot_id in preference if slot_id in eligible),
            None,
        )
        if result.suggested_slot_id != deterministic_suggestion:
            result.suggested_slot_id = deterministic_suggestion
            result.suggestion_reason = (
                "系统只根据明确可见的槽位状态给出建议；请人工确认目标槽。"
                if eligible
                else "没有足够可见证据建议槽位，请换角度重拍。"
            )
        result.requires_user_confirmation = True
        return result

    def locate_components(
        self,
        request: MultiComponentLocateRequest,
    ) -> SemanticComponentCandidateBatch:
        """Ground three distinct paper-figure targets in one Qwen call.

        Qwen supplies semantic boxes and interior prompt points only.  Each
        candidate is segmented and tracked by its own SAM2 session downstream;
        the boxes must therefore remain separate and must never be merged into
        one broad region.
        """
        try:
            image_bytes = base64.b64decode(request.image_base64, validate=True)
            normalized = self._normalize_image(image_bytes, MAX_LIVE_IMAGE_SIDE)
        except (ValueError, OSError) as exc:
            raise ValueError("image_base64 is not a valid image") from exc

        # Unity retries only the targets missing from the first overview pass.
        # A holder-only retry should therefore use the narrow holder profile
        # immediately instead of paying for another broad three-object prompt
        # and then a third focused Qwen call.
        if request.component_ids == ["empty_spool_holder"]:
            candidate = self._compile_overview_holder_from_exemplar(normalized)
            if candidate is None:
                candidate = self._relocate_overview_empty_spool_holder(normalized)
            return SemanticComponentCandidateBatch(components=[candidate])

        requested = ", ".join(request.component_ids)
        prompt = "".join(
            [
                "TASK-CONDITIONED COMPONENT PROFILE. You receive exactly one CURRENT "
                "CAMERA FRAME containing a Bambu Lab A1 mini and/or AMS Lite. Locate "
                "each requested physical component as a "
                "SEPARATE object. Requested component ids: ",
                requested,
                ". Return exactly one record for every requested id, in the same "
                "order. Coordinates are normalized integers from 0 to 1000. Every "
                "found object needs a tight bounding box around that object only and "
                "one target point on a solid, clearly visible surface inside it. "
                "Never return a union box and never include the table, monitor, tubes, "
                "adjacent components, or handwritten annotations. Definitions: "
                "filament_spool is one complete circular reel with two broad perforated "
                "flanges, a central hub, and wound filament between the flanges; if "
                "several are visible, prefer the clearly mounted orange-filament reel "
                "on AMS Lite rather than a loose spare reel at an image edge. In the "
                "configured paper view, this can also be the mounted gray-filament reel; "
                "choose the mounted reel with the clearest two flange boundaries, not a "
                "loose edge reel. Its box must stop at both flange boundaries and cover "
                "one reel only. The long pale horizontal/vertical AMS support bar beside "
                "the reel, black cables, PTFE tubes, feeder cap and table must be outside "
                "the box. Put the target point on wound filament, never on that support. "
                "empty_spool_holder is one fixed pale-white/light-gray empty AMS Lite "
                "spool-support arm physically attached to the central structure, visibly "
                "elongated and without any circular reel mounted. In the usual overview, "
                "the clearest empty holders are the two bare lower arms extending away "
                "from and below the dark feeder caps numbered 1-2 and 3-4. The dark "
                "round numbered cap is the FEEDER, not the holder, and must be completely "
                "outside the holder box. Each holder has an elongated trough "
                "body, a raised outer end, two parallel dark slots near that outer end, "
                "and a darker triangular underside. Camera rotation may make the arm look "
                "horizontal, vertical, or diagonal; choose by structure, not direction. "
                "Prefer one fully visible lower bare arm; exclude all loose "
                "spools, dark numbered feeder caps, yellow buttons, tubes, and the "
                "central column. A round perforated disk can never be this target. "
                "build_plate is the removable gold/brown rectangular textured A1 mini "
                "sheet with straight outer edges and clipped/tabbed corners; exclude "
                "the white table, printer base, gantry, shadows, and any object resting "
                "on the sheet. Trace all four visible metal-sheet edges before emitting "
                "the box: the box may contain the rectangular gold sheet but must stop "
                "at its edges and may not extend into the white table. Place its target "
                "point on unobstructed gold texture. "
                "Before returning, verify that the three boxes do not overlap each "
                "other except for minor perspective contact and that every target point "
                "falls on the named object's visible foreground. If a requested object "
                "is not clearly visible, return found=false instead of guessing. Use "
                "only evidence in the current frame. Return JSON only."
            ]
        )
        component_id_schema = {
            "type": "string",
            "enum": list(request.component_ids),
        }
        compact_schema = {
            "type": "object",
            "properties": {
                "components": {
                    "type": "array",
                    "minItems": len(request.component_ids),
                    "maxItems": len(request.component_ids),
                    "items": {
                        "type": "object",
                        "properties": {
                            "component_id": component_id_schema,
                            "found": {"type": "boolean"},
                            "bbox_0_1000": {
                                "type": ["array", "null"],
                                "items": {
                                    "type": "integer",
                                    "minimum": 0,
                                    "maximum": 1000,
                                },
                                "minItems": 4,
                                "maxItems": 4,
                            },
                            "target_point_0_1000": {
                                "type": ["array", "null"],
                                "items": {
                                    "type": "integer",
                                    "minimum": 0,
                                    "maximum": 1000,
                                },
                                "minItems": 2,
                                "maxItems": 2,
                            },
                            "confidence": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 1,
                            },
                            "visible_evidence": {"type": "string"},
                            "failure_reason": {"type": ["string", "null"]},
                        },
                        "required": [
                            "component_id",
                            "found",
                            "bbox_0_1000",
                            "target_point_0_1000",
                            "confidence",
                            "visible_evidence",
                            "failure_reason",
                        ],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["components"],
            "additionalProperties": False,
        }
        raw = self.ollama.chat_structured(
            prompt=prompt,
            schema=compact_schema,
            images_base64=[normalized],
            max_tokens=1200,
        )
        batch = SemanticComponentCandidateBatch.model_validate(raw)
        by_id = {candidate.component_id: candidate for candidate in batch.components}
        normalized_candidates: list[SemanticComponentCandidate] = []
        for component_id in request.component_ids:
            candidate = by_id.get(component_id)
            if candidate is None:
                candidate = SemanticComponentCandidate(
                    component_id=component_id,
                    found=False,
                    confidence=0.0,
                    visible_evidence="",
                    failure_reason="Qwen omitted the requested component",
                )
            elif candidate.found and candidate.bbox_0_1000 is not None:
                x1, y1, x2, y2 = candidate.bbox_0_1000
                point = candidate.target_point_0_1000
                if point is None or not (x1 <= point[0] <= x2 and y1 <= point[1] <= y2):
                    candidate.target_point_0_1000 = [
                        (x1 + x2) // 2,
                        (y1 + y2) // 2,
                    ]
            # Do not hide a weak broad-pass holder behind an expensive nested
            # Qwen retry. Unity will issue one holder-only request, which is
            # routed to the focused profile above.
            if component_id == "empty_spool_holder" and (
                not candidate.found
                or candidate.bbox_0_1000 is None
                or self._overview_holder_is_probably_a_spool(candidate)
                or candidate.target_point_0_1000 is None
                or not self._point_patch_is_pale_holder(
                    normalized,
                    candidate.target_point_0_1000,
                )
            ):
                # The broad proposal usually lands on the nearby numbered
                # feeder cap. Use that rejected box only to compile a tighter
                # current-frame crop, then ask the focused holder profile. The
                # crop is derived from Qwen's current semantic evidence, not a
                # fixed screen ROI.
                # Do not synthesize the final holder box by extending the
                # feeder rectangle in a fixed screen direction.  A rotated
                # overhead camera can put the holder on either side, and a
                # pale table patch can pass a colour-only check.  The rejected
                # feeder remains a current-frame anchor solely for compiling a
                # focused crop; Qwen must prove the arm geometry inside it.
                exemplar_candidate = self._compile_overview_holder_from_exemplar(
                    normalized
                )
                candidate = (
                    exemplar_candidate
                    if exemplar_candidate is not None
                    else self._relocate_overview_empty_spool_holder(
                        normalized,
                        candidate.bbox_0_1000,
                    )
                )
            normalized_candidates.append(candidate)

        by_normalized_id = {
            candidate.component_id: candidate for candidate in normalized_candidates
        }
        spool = by_normalized_id.get("filament_spool")
        holder = by_normalized_id.get("empty_spool_holder")
        if (
            spool is not None
            and holder is not None
            and spool.found
            and holder.found
            and self._box_overlap_over_smaller(
                spool.bbox_0_1000,
                holder.bbox_0_1000,
            )
            > 0.18
        ):
            rejected_holder = SemanticComponentCandidate(
                component_id="empty_spool_holder",
                found=False,
                confidence=0.0,
                visible_evidence=holder.visible_evidence,
                failure_reason=(
                    "Holder proposal overlaps the filament spool; focused "
                    "holder re-grounding is required"
                ),
            )
            normalized_candidates = [
                rejected_holder
                if candidate.component_id == "empty_spool_holder"
                else candidate
                for candidate in normalized_candidates
            ]
        return SemanticComponentCandidateBatch(components=normalized_candidates)

    @staticmethod
    def _clockwise_candidate_to_original(
        candidate: SemanticComponentCandidate,
    ) -> SemanticComponentCandidate:
        """Map normalized top-left coordinates from a 90-degree CW view."""
        box = candidate.bbox_0_1000
        point = candidate.target_point_0_1000
        if box is None or point is None:
            return candidate
        return candidate.model_copy(
            update={
                "bbox_0_1000": [box[1], 1000 - box[2], box[3], 1000 - box[0]],
                "target_point_0_1000": [point[1], 1000 - point[0]],
                "visible_evidence": (
                    candidate.visible_evidence
                    + "; semantic orientation retry mapped back to raw frame"
                ),
            }
        )

    @staticmethod
    def _overview_holder_is_probably_a_spool(
        candidate: SemanticComponentCandidate,
    ) -> bool:
        box = candidate.bbox_0_1000 or []
        if len(box) != 4:
            return False
        evidence = candidate.visible_evidence.lower()
        touches_image_edge = (
            box[0] <= 10
            or box[1] <= 10
            or box[2] >= 990
            or box[3] >= 990
        )
        width = max(1, box[2] - box[0])
        height = max(1, box[3] - box[1])
        proposal_area_ratio = width * height / 1_000_000.0
        # A visible AMS Lite holder is a narrow arm/trough.  A nearly square
        # proposal is much more likely to be the face of a loose reel.
        looks_round = max(width, height) / min(width, height) < 1.20
        names_spool_geometry = any(
            phrase in evidence
            for phrase in (
                "flange",
                "perforated",
                "circular reel",
                "spool disk",
                "loose spool",
            )
        )
        # Broad prompts repeatedly boxed a numbered feeder disk plus its short
        # neck and described it as "below feeder cap labeled 1". Route that
        # ambiguous proposal to the focused profile instead of letting SAM2
        # faithfully segment the wrong feeder assembly.
        names_numbered_feeder_context = any(
            phrase in evidence
            for phrase in (
                "feeder cap labeled",
                "numbered feeder cap",
                "labeled '1'",
                'labeled "1"',
                "labeled '2'",
                'labeled "2"',
                "labeled '3'",
                'labeled "3"',
                "labeled '4'",
                'labeled "4"',
            )
        )
        return (
            touches_image_edge
            or looks_round
            or proposal_area_ratio > 0.09
            or names_spool_geometry
            or names_numbered_feeder_context
        )

    @staticmethod
    def _box_overlap_over_smaller(
        first: list[int] | None,
        second: list[int] | None,
    ) -> float:
        if first is None or second is None or len(first) != 4 or len(second) != 4:
            return 0.0
        intersection_width = max(0, min(first[2], second[2]) - max(first[0], second[0]))
        intersection_height = max(0, min(first[3], second[3]) - max(first[1], second[1]))
        intersection = intersection_width * intersection_height
        first_area = max(1, (first[2] - first[0]) * (first[3] - first[1]))
        second_area = max(1, (second[2] - second[0]) * (second[3] - second[1]))
        return intersection / min(first_area, second_area)

    def _compile_holder_from_feeder_anchor(
        self,
        normalized_image_base64: str,
        rejected: SemanticComponentCandidate,
    ) -> SemanticComponentCandidate | None:
        """Compile a holder prompt from a Qwen-grounded feeder anchor.

        In the configured landscape overview, each front empty holder extends
        from the lower edge of its numbered feeder toward the lower image edge.
        The relation is task-profile geometry, while the anchor remains Qwen's
        current-frame observation; this is not a fixed screen ROI.
        """
        box = rejected.bbox_0_1000
        if box is None or len(box) != 4:
            return None
        evidence = rejected.visible_evidence.lower()
        if not any(word in evidence for word in ("feeder", "holder", "support arm")):
            return None
        x1, y1, x2, y2 = box
        width = max(1, x2 - x1)
        height = max(1, y2 - y1)
        compiled_box = [
            max(0, round(x1 - 0.05 * width)),
            max(0, round(y2 - 0.02 * height)),
            min(1000, round(x2 + 0.55 * width)),
            min(1000, round(y2 + 1.00 * height)),
        ]
        target_point = [
            max(0, min(1000, round(x1 + 0.70 * width))),
            max(0, min(1000, round(y2 + 0.55 * height))),
        ]
        if (
            compiled_box[0] >= compiled_box[2]
            or compiled_box[1] >= compiled_box[3]
            or not self._point_patch_is_pale_holder(
                normalized_image_base64,
                target_point,
            )
        ):
            return None
        return SemanticComponentCandidate(
            component_id="empty_spool_holder",
            found=True,
            bbox_0_1000=compiled_box,
            target_point_0_1000=target_point,
            confidence=min(max(rejected.confidence, 0.75), 0.88),
            visible_evidence=(
                "Task-profile holder prompt compiled from the current-frame "
                "Qwen feeder anchor; target point verified on pale holder plastic"
            ),
        )

    def _compile_overview_holder_from_exemplar(
        self,
        normalized_image_base64: str,
    ) -> SemanticComponentCandidate | None:
        """Map labelled empty-holder arms from a task exemplar into this frame.

        The mapping is accepted only when local SIFT features support one
        coherent RANSAC homography.  This is the task-profile predefinition
        requested for the paper demo: it refines Qwen's semantic decision into
        a current-frame SAM prompt without using a fixed live-camera ROI.
        """

        if not OVERVIEW_HOLDER_EXEMPLAR_PATH.exists():
            return None
        try:
            current_bytes = base64.b64decode(
                normalized_image_base64,
                validate=True,
            )
            current = cv2.imdecode(
                np.frombuffer(current_bytes, dtype=np.uint8),
                cv2.IMREAD_COLOR,
            )
            exemplar = cv2.imread(str(OVERVIEW_HOLDER_EXEMPLAR_PATH))
        except (ValueError, OSError):
            return None
        if current is None or exemplar is None:
            return None

        detector = cv2.SIFT_create(nfeatures=3200)
        exemplar_points, exemplar_descriptors = detector.detectAndCompute(
            cv2.cvtColor(exemplar, cv2.COLOR_BGR2GRAY),
            None,
        )
        current_points, current_descriptors = detector.detectAndCompute(
            cv2.cvtColor(current, cv2.COLOR_BGR2GRAY),
            None,
        )
        if exemplar_descriptors is None or current_descriptors is None:
            return None
        matches = cv2.BFMatcher().knnMatch(
            exemplar_descriptors,
            current_descriptors,
            k=2,
        )
        good = [
            first
            for pair in matches
            if len(pair) == 2
            for first, second in [pair]
            if first.distance < 0.72 * second.distance
        ]
        if len(good) < 12:
            return None
        source = np.float32(
            [exemplar_points[match.queryIdx].pt for match in good]
        ).reshape(-1, 1, 2)
        destination = np.float32(
            [current_points[match.trainIdx].pt for match in good]
        ).reshape(-1, 1, 2)
        homography, inliers = cv2.findHomography(
            source,
            destination,
            cv2.RANSAC,
            5.0,
        )
        if homography is None or inliers is None or not np.isfinite(homography).all():
            return None
        inlier_count = int(np.count_nonzero(inliers))
        # Live frames are JPEG-normalized to 1024 px before the VLM call; that
        # resampling lowers the inlier fraction slightly even when the same
        # device geometry is recovered. Ten coherent inliers plus a 24% ratio
        # remains stricter than accepting an isolated local match.
        if inlier_count < 10 or inlier_count / len(good) < 0.24:
            return None

        current_height, current_width = current.shape[:2]
        candidates: list[tuple[float, list[int], list[int]]] = []
        for reference_index, reference_box in enumerate(
            OVERVIEW_EMPTY_HOLDER_EXEMPLAR_BOXES
        ):
            x1, y1, x2, y2 = reference_box
            corners = np.float32(
                [[[x1, y1], [x2, y1], [x2, y2], [x1, y2]]]
            )
            projected = cv2.perspectiveTransform(corners, homography)[0]
            if not np.isfinite(projected).all():
                continue
            px1 = max(0, int(np.floor(projected[:, 0].min())))
            py1 = max(0, int(np.floor(projected[:, 1].min())))
            px2 = min(current_width, int(np.ceil(projected[:, 0].max())))
            py2 = min(current_height, int(np.ceil(projected[:, 1].max())))
            if px2 <= px1 or py2 <= py1:
                continue
            area_ratio = (
                (px2 - px1) * (py2 - py1)
                / max(1, current_width * current_height)
            )
            if area_ratio < 0.003 or area_ratio > 0.075:
                continue
            if px1 <= 2 or py1 <= 2 or px2 >= current_width - 2 or py2 >= current_height - 2:
                continue

            patch = current[py1:py2, px1:px2]
            rgb = cv2.cvtColor(patch, cv2.COLOR_BGR2RGB)
            maximum = rgb.max(axis=2)
            minimum = rgb.min(axis=2)
            brightness = rgb.mean(axis=2)
            pale = (
                (brightness >= 125)
                & (brightness <= 242)
                & ((maximum - minimum) <= 55)
            )
            dark_detail = brightness < 105
            pale_ratio = float(np.mean(pale))
            detail_ratio = float(np.mean(dark_detail))
            # A real holder combines pale plastic with dark slots/ribs.  A
            # plain white table has high brightness but almost no dark detail.
            if pale_ratio < 0.20 or detail_ratio < 0.006 or detail_ratio > 0.45:
                continue

            target_x = round((px1 + px2) / 2)
            target_y = round(py1 + 0.42 * (py2 - py1))
            target_0_1000 = [
                round(target_x / max(1, current_width) * 1000),
                round(target_y / max(1, current_height) * 1000),
            ]
            if not self._point_patch_is_pale_holder(
                normalized_image_base64,
                target_0_1000,
            ):
                continue
            box_0_1000 = [
                round(px1 / current_width * 1000),
                round(py1 / current_height * 1000),
                round(px2 / current_width * 1000),
                round(py2 / current_height * 1000),
            ]
            # In the paper capture exemplar the second bare arm is farther
            # from the printer and has the cleanest unobstructed outline.  Use
            # that reference preference only after both candidates have passed
            # current-frame appearance and homography gates.
            score = (
                pale_ratio
                + min(detail_ratio, 0.12)
                + inlier_count / 100.0
                + 0.18 * reference_index
            )
            candidates.append((score, box_0_1000, target_0_1000))

        if not candidates:
            return None
        _, selected_box, selected_point = max(candidates, key=lambda item: item[0])
        return SemanticComponentCandidate(
            component_id="empty_spool_holder",
            found=True,
            bbox_0_1000=selected_box,
            target_point_0_1000=selected_point,
            confidence=min(0.96, 0.74 + inlier_count / 100.0),
            visible_evidence=(
                "Task-profile holder exemplar mapped to the current frame by "
                f"SIFT/RANSAC ({inlier_count}/{len(good)} inliers); pale slotted "
                "holder appearance verified before SAM2"
            ),
        )

    def _relocate_overview_empty_spool_holder(
        self,
        normalized_image_base64: str,
        rejected_overview_box: list[int] | None = None,
    ) -> SemanticComponentCandidate:
        """Retry a common overview error: a loose reel mistaken for its holder."""
        focus_box: list[int] | None = None
        focused_image = normalized_image_base64
        if rejected_overview_box is not None and len(rejected_overview_box) == 4:
            try:
                source = Image.open(
                    io.BytesIO(base64.b64decode(normalized_image_base64, validate=True))
                ).convert("RGB")
                x1, y1, x2, y2 = rejected_overview_box
                box_width = max(1, x2 - x1)
                box_height = max(1, y2 - y1)
                focus_box = [
                    max(0, round(x1 - max(160, box_width * 2.2))),
                    max(0, round(y1 - max(100, box_height * 0.5))),
                    min(1000, round(x2 + max(160, box_width * 2.2))),
                    min(1000, round(y2 + max(180, box_height * 1.4))),
                ]
                crop = source.crop(
                    (
                        round(focus_box[0] / 1000 * source.width),
                        round(focus_box[1] / 1000 * source.height),
                        round(focus_box[2] / 1000 * source.width),
                        round(focus_box[3] / 1000 * source.height),
                    )
                )
                buffer = io.BytesIO()
                crop.save(buffer, format="JPEG", quality=90)
                focused_image = base64.b64encode(buffer.getvalue()).decode("ascii")
            except (OSError, ValueError):
                focus_box = None
                focused_image = normalized_image_base64
        prompt = (
            "This is a task-compiled CURRENT-FRAME crop around an AMS Lite feeder "
            "cluster. Enumerate every clearly visible EMPTY AMS Lite spool support ARM "
            "in this crop, then let geometry choose one. Coordinates must describe this "
            "crop only. "
            "A previous overview proposal was rejected because it selected a loose "
            "filament spool/reel. The required object is a fixed pale-white structural "
            "elongated rail, trough, fork, or axle arm physically attached to the AMS "
            "Lite central support, with no reel mounted on it. In this specific device, "
            "look directly beyond the compact cluster of dark feeder caps numbered 1, 2, "
            "3 and 4: the two lower bare spool-support arms extend toward the lower/front "
            "edge of the image and have a raised pale outer end, two parallel dark slots "
            "near that outer end, and a darker triangular underside. The round part with "
            "a printed 1, 2, 3 or 4 is a FEEDER CAP and is forbidden: it must not be inside "
            "a candidate box or used as the target point. The holder itself has no printed "
            "slot number. "
            "Choose the more completely visible one. The camera can rotate this structure, "
            "so do not require the arm to be horizontal in image coordinates. It must not "
            "have two large circular flange disks. Never select the orange mounted spool, any loose "
            "gray or white spool at an image edge, a dark numbered feeder cap, tubing, "
            "or the central column. First locate the compact cluster of four dark numbered "
            "feeder caps and the tall pale central support. Then inspect the elongated "
            "white trough-like arms extending from that support. Include each plausible "
            "empty lower arm as a separate candidate. Each box should be visibly longer "
            "than it is wide; it should describe "
            "a rail/fork/trough, not a disk. A valid holder is never isolated at the image "
            "edge and never has a large circular center hole or perforated flange disk. "
            "Return the feeder-cluster box as geometric evidence plus 0 to 4 separate "
            "candidate arms. For each candidate include a tight box, a point on solid "
            "white plastic, confidence, visible evidence, and whether it is physically "
            "attached to the AMS Lite. Return an empty candidate array rather than a reel. "
            "JSON only."
        )
        holder_candidate_schema = {
            "type": "object",
            "properties": {
                "bbox_0_1000": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0, "maximum": 1000},
                    "minItems": 4,
                    "maxItems": 4,
                },
                "target_point_0_1000": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0, "maximum": 1000},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "visible_evidence": {"type": "string"},
                "is_attached_to_ams_lite": {"type": "boolean"},
            },
            "required": [
                "bbox_0_1000",
                "target_point_0_1000",
                "confidence",
                "visible_evidence",
                "is_attached_to_ams_lite",
            ],
            "additionalProperties": False,
        }
        schema = {
            "type": "object",
            "properties": {
                "feeder_cluster_bbox_0_1000": {
                    "type": ["array", "null"],
                    "items": {"type": "integer", "minimum": 0, "maximum": 1000},
                    "minItems": 4,
                    "maxItems": 4,
                },
                "candidate_holders": {
                    "type": "array",
                    "items": holder_candidate_schema,
                    "minItems": 0,
                    "maxItems": 4,
                },
            },
            "required": [
                "feeder_cluster_bbox_0_1000",
                "candidate_holders",
            ],
            "additionalProperties": False,
        }
        raw = self.ollama.chat_structured(
            prompt=prompt,
            schema=schema,
            # Coordinates in the response are crop coordinates whenever a
            # rejected overview anchor produced focused_image.  Passing the
            # full frame here and then mapping it as a crop displaced correct
            # proposals onto the white table.
            images_base64=[focused_image],
            max_tokens=600,
        )
        feeder_box = raw.get("feeder_cluster_bbox_0_1000")
        proposals = raw.get("candidate_holders")
        valid: list[SemanticComponentCandidate] = []
        if isinstance(feeder_box, list) and len(feeder_box) == 4 and isinstance(proposals, list):
            feeder_center = (
                (feeder_box[0] + feeder_box[2]) / 2,
                (feeder_box[1] + feeder_box[3]) / 2,
            )
            for proposal in proposals:
                if not isinstance(proposal, dict) or not proposal.get("is_attached_to_ams_lite"):
                    continue
                holder_box = proposal.get("bbox_0_1000")
                point = proposal.get("target_point_0_1000")
                if not isinstance(holder_box, list) or len(holder_box) != 4:
                    continue
                if not isinstance(point, list) or len(point) != 2:
                    continue
                width = max(1, holder_box[2] - holder_box[0])
                height = max(1, holder_box[3] - holder_box[1])
                elongated = max(width, height) / min(width, height) >= 1.05
                touches_edge = (
                    holder_box[0] <= 18
                    or holder_box[1] <= 18
                    or holder_box[2] >= 982
                    or holder_box[3] >= 982
                )
                holder_center = (
                    (holder_box[0] + holder_box[2]) / 2,
                    (holder_box[1] + holder_box[3]) / 2,
                )
                close_to_feeders = math.hypot(
                    holder_center[0] - feeder_center[0],
                    holder_center[1] - feeder_center[1],
                ) <= 430
                overlaps_feeder_cluster = (
                    self._box_overlap_over_smaller(holder_box, feeder_box) > 0.22
                )
                evidence = str(proposal.get("visible_evidence", "")).lower()
                names_reel = any(
                    word in evidence
                    for word in ("flange", "perforated", "reel", "spool disk", "circular hole")
                )
                names_numbered_cap_as_target = any(
                    phrase in evidence
                    for phrase in (
                        "numbered feeder cap",
                        "round feeder cap",
                    )
                )
                if (
                    touches_edge
                    or not elongated
                    or not close_to_feeders
                    or overlaps_feeder_cluster
                    or names_reel
                    or names_numbered_cap_as_target
                ):
                    continue
                try:
                    valid.append(
                        SemanticComponentCandidate(
                            component_id="empty_spool_holder",
                            found=True,
                            bbox_0_1000=holder_box,
                            target_point_0_1000=point,
                            confidence=float(proposal.get("confidence", 0.0)),
                            visible_evidence=str(proposal.get("visible_evidence", "")),
                        )
                    )
                except (TypeError, ValueError, ValidationError):
                    continue
        if valid:
            selected = max(valid, key=lambda item: item.confidence)
            if focus_box is not None:
                span_x = focus_box[2] - focus_box[0]
                span_y = focus_box[3] - focus_box[1]
                box = selected.bbox_0_1000 or [0, 0, 0, 0]
                point = selected.target_point_0_1000 or [0, 0]
                selected = selected.model_copy(
                    update={
                        "bbox_0_1000": [
                            round(focus_box[0] + box[0] / 1000 * span_x),
                            round(focus_box[1] + box[1] / 1000 * span_y),
                            round(focus_box[0] + box[2] / 1000 * span_x),
                            round(focus_box[1] + box[3] / 1000 * span_y),
                        ],
                        "target_point_0_1000": [
                            round(focus_box[0] + point[0] / 1000 * span_x),
                            round(focus_box[1] + point[1] / 1000 * span_y),
                        ],
                        "visible_evidence": (
                            selected.visible_evidence
                            + "; constraint-compiled current-frame crop"
                        ),
                    }
                )
            return selected
        return SemanticComponentCandidate(
            component_id="empty_spool_holder",
            found=False,
            confidence=0.0,
            visible_evidence="",
            failure_reason=(
                "Focused Qwen retry did not prove an elongated empty holder arm "
                "attached to the AMS Lite feeder cluster"
            ),
        )

    def locate_empty_spool_axle(
        self,
        request: EmptySpoolAxleLocateRequest,
    ) -> EmptySpoolAxleCandidate:
        """Use Qwen only for a tightly constrained empty-spindle proposal.

        The result is intentionally a semantic point and a generous prompt box.
        SAM2 is responsible for the pixel mask in the next stage.  Keeping this
        operation separate from overview/state-machine prompts makes the paper
        evidence path reproducible and avoids a task recommendation changing the
        visual target.
        """
        try:
            image_bytes = base64.b64decode(request.image_base64, validate=True)
            normalized = self._normalize_image(image_bytes, MAX_LIVE_IMAGE_SIDE)
        except (ValueError, OSError) as exc:
            raise ValueError("image_base64 is not a valid image") from exc

        preferred = (
            str(request.preferred_slot_id)
            if request.preferred_slot_id is not None
            else "none"
        )
        selected_slot_constraint = ""
        if request.preferred_slot_id == 4:
            selected_slot_constraint = (
                "For selected slot 4, first find the dark round feeder cap embossed "
                "with the digit 4, then identify the pale-white empty holder arm "
                "belonging to that same slot. Use this physical relationship, not a "
                "fixed screen quadrant: camera rotation and viewpoint can place Slot 4 "
                "near the center, left, or right of the image. The digit-4 cap itself "
                "is explicitly forbidden. A valid target point must land on the "
                "pale-white holder, never on a dark feeder surface or pale table. "
                "The holder should read as an elongated pale structural arm/trough, "
                "not a circular disk and not a compact dark cap. "
            )
        prompt = "".join(
            [
                "You receive exactly one photograph of a Bambu Lab AMS Lite. ",
                "Locate ONE visible EMPTY spool spindle (also called spool holder or ",
                "spool axle). On this device it appears as a pale-white horizontal ",
                "cylindrical, fork-like holder projecting outward from the central ",
                "vertical column; its open end accepts the circular hole of a filament ",
                "spool. It is NOT the dark four-slot feeder assembly below. An empty ",
                "spindle has no circular spool disk mounted on it. Return a generous ",
                "bounding box around the complete visible white holder surface plus one ",
                "target point clearly inside that white holder. Do NOT target a mounted spool, black feeder ",
                "module, numbered feeder cap, yellow release button, PTFE tube, central ",
                "support column, printer, background, or table. The embossed feeder-cap ",
                "digits define slots: 1=left-upper, 2=left-lower, 3=right-lower, ",
                "4=right-upper. Do not infer a slot from screen quadrant alone. If no ",
                "empty spindle is clearly visible, return found=false instead of guessing. ",
                "Set extension_direction to left, right, up, or down according to "
                "the direction the white holder projects away from the central "
                "support in this displayed image; use unknown only when found=false. ",
                "Preferred slot id is ",
                f"{preferred}; use it only if that same slot is visibly empty. ",
                selected_slot_constraint,
                "Your answer must start with the key found, for example ",
                "{\"found\":true,...}. Do not repeat or explain the JSON schema.",
            ]
        )
        # Keep this schema deliberately tiny.  A generated Pydantic schema
        # contains descriptions/titles that some OpenAI-compatible gateways
        # occasionally echo back instead of answering the visual question.
        # The Pydantic model below remains the authoritative validator.
        compact_schema = {
            "type": "object",
            "properties": {
                "found": {"type": "boolean"},
                "slot_id": {"type": ["integer", "null"], "minimum": 1, "maximum": 4},
                "bbox_0_1000": {
                    "type": ["array", "null"],
                    "items": {"type": "integer", "minimum": 0, "maximum": 1000},
                    "minItems": 4,
                    "maxItems": 4,
                },
                "target_point_0_1000": {
                    "type": ["array", "null"],
                    "items": {"type": "integer", "minimum": 0, "maximum": 1000},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "visible_evidence": {"type": "string"},
                "failure_reason": {"type": ["string", "null"]},
                "extension_direction": {
                    "type": "string",
                    "enum": ["left", "right", "up", "down", "unknown"],
                },
            },
            "required": [
                "found",
                "slot_id",
                "bbox_0_1000",
                "target_point_0_1000",
                "confidence",
                "visible_evidence",
                "failure_reason",
                "extension_direction",
            ],
            "additionalProperties": False,
        }
        raw = self.ollama.chat_structured(
            prompt=prompt,
            schema=compact_schema,
            images_base64=[normalized],
            max_tokens=600,
        )
        candidate = EmptySpoolAxleCandidate.model_validate(raw)
        candidate = self._repair_empty_spool_axle_candidate(
            candidate,
            request,
            normalized,
        )
        if (
            candidate.found
            and request.preferred_slot_id == 4
            and candidate.slot_id == 4
        ):
            compiled = self._compile_slot4_holder_from_exemplar(
                request.image_base64,
                candidate,
            )
            if compiled is not None:
                return compiled
            # The task exemplar is a geometry refinement, not a second
            # semantic detector. A single historical view cannot match every
            # valid camera pose. If Qwen has already identified Slot 4 and its
            # prompt survived the pale-holder repair/validation above, keep
            # that current-frame proposal and let SAM2 plus the strict mask
            # quality gate decide whether an overlay is safe to show.
            tightened = self._tighten_slot4_current_frame_prompt(
                request.image_base64,
                candidate,
            )
            return tightened.model_copy(
                update={
                    "visible_evidence": (
                        f"{tightened.visible_evidence} The historical geometry "
                        "exemplar did not match this camera pose; retained the "
                        "current-frame Qwen Slot 4 holder proposal and compiled "
                        "a local, direction-aware SAM2 prompt that excludes the "
                        "central support column."
                    ).strip(),
                }
            )
        return candidate

    def _tighten_slot4_current_frame_prompt(
        self,
        current_image_base64: str,
        candidate: EmptySpoolAxleCandidate,
    ) -> EmptySpoolAxleCandidate:
        """Remove the support-column side from a valid Qwen holder proposal.

        The white holder is physically connected to a much larger white AMS
        support, so SAM can merge both when Qwen returns a generous box. Qwen
        supplies the current-frame extension direction; a strong image edge on
        the attachment side then defines a tighter box. No absolute screen
        coordinates are used, so a rotated camera remains supported.
        """

        box = candidate.bbox_0_1000 or []
        point = candidate.target_point_0_1000 or []
        direction = candidate.extension_direction
        if len(box) != 4 or len(point) != 2 or direction == "unknown":
            return candidate
        try:
            data = base64.b64decode(current_image_base64, validate=True)
            image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        except (ValueError, OSError):
            return candidate
        if image is None:
            return candidate

        height, width = image.shape[:2]
        x1 = max(0, min(width - 2, round(box[0] / 1000 * width)))
        y1 = max(0, min(height - 2, round(box[1] / 1000 * height)))
        x2 = max(x1 + 2, min(width, round(box[2] / 1000 * width)))
        y2 = max(y1 + 2, min(height, round(box[3] / 1000 * height)))
        point_x = max(x1 + 1, min(x2 - 1, round(point[0] / 1000 * width)))
        point_y = max(y1 + 1, min(y2 - 1, round(point[1] / 1000 * height)))
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gradient_x = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3))
        gradient_y = np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3))

        def strongest_edge(scores: np.ndarray, offset: int) -> int | None:
            if scores.size < 4 or not np.isfinite(scores).all():
                return None
            index = int(np.argmax(scores))
            if float(scores[index]) < 8.0:
                return None
            return offset + index

        pad_x = max(3, round(width * 0.004))
        pad_y = max(3, round(height * 0.006))
        if direction in {"left", "right"}:
            band_y1 = max(y1, point_y - max(18, (y2 - y1) // 3))
            band_y2 = min(y2, point_y + max(18, (y2 - y1) // 3))
            if direction == "right" and point_x - x1 >= 12:
                scores = gradient_x[band_y1:band_y2, x1 : point_x - 6].mean(axis=0)
                edge = strongest_edge(scores, x1)
                if edge is not None:
                    x1 = max(x1, edge - pad_x)
            elif direction == "left" and x2 - point_x >= 12:
                scores = gradient_x[band_y1:band_y2, point_x + 6 : x2].mean(axis=0)
                edge = strongest_edge(scores, point_x + 6)
                if edge is not None:
                    x2 = min(x2, edge + pad_x)

            # The outward half contains the holder silhouette rather than the
            # vertical support. Find the first persistent horizontal boundary
            # above the semantic point; this removes pale table pixels while
            # retaining the complete fork/trough surface.
            if point_y - y1 >= 18:
                if direction == "right":
                    sample_x1 = min(x2 - 2, point_x + max(2, (x2 - point_x) // 6))
                    sample_x2 = x2
                else:
                    sample_x1 = x1
                    sample_x2 = max(x1 + 2, point_x - max(2, (point_x - x1) // 6))
                scores = gradient_y[y1 : point_y - 6, sample_x1:sample_x2].mean(axis=1)
                if scores.size >= 4:
                    threshold = max(3.5, float(scores.max()) * 0.14)
                    supported = np.flatnonzero(scores >= threshold)
                    for relative in supported:
                        if relative + 1 < scores.size and scores[relative + 1] >= threshold:
                            y1 = max(y1, y1 + int(relative) - pad_y)
                            break
        elif direction in {"up", "down"}:
            band_x1 = max(x1, point_x - max(18, (x2 - x1) // 3))
            band_x2 = min(x2, point_x + max(18, (x2 - x1) // 3))
            if direction == "down" and point_y - y1 >= 12:
                scores = gradient_y[y1 : point_y - 6, band_x1:band_x2].mean(axis=1)
                edge = strongest_edge(scores, y1)
                if edge is not None:
                    y1 = max(y1, edge - pad_y)
            elif direction == "up" and y2 - point_y >= 12:
                scores = gradient_y[point_y + 6 : y2, band_x1:band_x2].mean(axis=1)
                edge = strongest_edge(scores, point_y + 6)
                if edge is not None:
                    y2 = min(y2, edge + pad_y)

        if x2 - x1 < max(24, width // 30) or y2 - y1 < max(24, height // 30):
            return candidate
        tightened_box = [
            round(x1 / width * 1000),
            round(y1 / height * 1000),
            round(x2 / width * 1000),
            round(y2 / height * 1000),
        ]
        if tightened_box == box:
            return candidate
        return candidate.model_copy(
            update={
                "bbox_0_1000": tightened_box,
                "visible_evidence": (
                    f"{candidate.visible_evidence} Direction-aware prompt "
                    f"compiler: holder extends {direction}; attachment-side "
                    "support pixels were removed before SAM2."
                ).strip(),
            }
        )

    def _repair_empty_spool_axle_candidate(
        self,
        candidate: EmptySpoolAxleCandidate,
        request: EmptySpoolAxleLocateRequest,
        normalized_image_base64: str,
    ) -> EmptySpoolAxleCandidate:
        """Repair a common Slot 4 VLM failure before SAM2 segmentation.

        Qwen occasionally names the correct slot but places the prompt box on
        the dark feeder module or the numbered cap below the actual empty white
        spool holder.  For the paper/demo capture route this is worse than
        returning no overlay, because SAM2 will accurately segment the wrong
        object.  This repair is deliberately narrow: it only applies to the
        selected Slot 4 standard AMS Lite view, only after Qwen has identified
        Slot 4, and only when the candidate is visually too low or its target
        point is not on a pale holder-like surface.
        """
        if (
            not candidate.found
            or request.preferred_slot_id != 4
            or candidate.slot_id != 4
            or candidate.bbox_0_1000 is None
            or candidate.target_point_0_1000 is None
        ):
            return candidate
        if not self._slot4_empty_holder_candidate_needs_repair(
            candidate,
            normalized_image_base64,
        ):
            return candidate

        repaired_box = self._slot4_white_holder_prompt_box(candidate.bbox_0_1000)
        x1, y1, x2, y2 = repaired_box
        repaired_target = [(x1 + x2) // 2, y1 + (y2 - y1) // 3]
        return candidate.model_copy(
            update={
                "bbox_0_1000": repaired_box,
                "target_point_0_1000": repaired_target,
                "confidence": min(candidate.confidence, 0.88),
                "proposal_source": "qwen_flash_white_holder_repair",
                "visible_evidence": (
                    f"{candidate.visible_evidence} Topology repair: Qwen named "
                    "Slot 4, but the original prompt landed on the lower feeder "
                    "area; the SAM2 prompt was moved to the corresponding pale "
                    "white empty spool holder surface."
                ).strip(),
            }
        )

    def _slot4_empty_holder_candidate_needs_repair(
        self,
        candidate: EmptySpoolAxleCandidate,
        normalized_image_base64: str,
    ) -> bool:
        box = candidate.bbox_0_1000 or []
        point = candidate.target_point_0_1000 or []
        if len(box) != 4 or len(point) != 2:
            return False
        x1, y1, x2, y2 = box
        center_y = (y1 + y2) / 2
        # In the standardized AMS Lite capture used for this figure, Slot 4's
        # empty white holder is above the feeder-cap row.  A candidate centered
        # in the lower half almost always means Qwen chose the dark feeder.
        if center_y > 430:
            return True
        return not self._point_patch_is_pale_holder(normalized_image_base64, point)

    def _compile_slot4_holder_from_exemplar(
        self,
        current_image_base64: str,
        qwen_candidate: EmptySpoolAxleCandidate,
    ) -> EmptySpoolAxleCandidate | None:
        """Compile a tight current-frame Slot 4 SAM prompt from a task exemplar.

        Qwen remains the semantic/empty-slot gate. The exemplar contributes
        only geometry, and only after a coherent RANSAC homography plus a
        current-frame pale-plastic appearance check. This prevents the broad
        Qwen box from letting SAM merge the white holder with the adjacent
        white table, loose spool, or AMS Lite support structure.
        """

        if not OVERVIEW_HOLDER_EXEMPLAR_PATH.exists():
            return None
        try:
            current_bytes = base64.b64decode(current_image_base64, validate=True)
            current = cv2.imdecode(
                np.frombuffer(current_bytes, dtype=np.uint8),
                cv2.IMREAD_COLOR,
            )
            exemplar = cv2.imread(str(OVERVIEW_HOLDER_EXEMPLAR_PATH))
        except (ValueError, OSError):
            return None
        if current is None or exemplar is None:
            return None

        detector = cv2.SIFT_create(nfeatures=4000)
        exemplar_points, exemplar_descriptors = detector.detectAndCompute(
            cv2.cvtColor(exemplar, cv2.COLOR_BGR2GRAY),
            None,
        )
        current_points, current_descriptors = detector.detectAndCompute(
            cv2.cvtColor(current, cv2.COLOR_BGR2GRAY),
            None,
        )
        if exemplar_descriptors is None or current_descriptors is None:
            return None
        matches = cv2.BFMatcher().knnMatch(
            exemplar_descriptors,
            current_descriptors,
            k=2,
        )
        good = [
            first
            for pair in matches
            if len(pair) == 2
            for first, second in [pair]
            if first.distance < 0.72 * second.distance
        ]
        if len(good) < 14:
            return None
        source = np.float32(
            [exemplar_points[match.queryIdx].pt for match in good]
        ).reshape(-1, 1, 2)
        destination = np.float32(
            [current_points[match.trainIdx].pt for match in good]
        ).reshape(-1, 1, 2)
        homography, inliers = cv2.findHomography(
            source,
            destination,
            cv2.RANSAC,
            5.0,
        )
        if homography is None or inliers is None or not np.isfinite(homography).all():
            return None
        inlier_count = int(np.count_nonzero(inliers))
        if inlier_count < 7 or inlier_count / len(good) < 0.18:
            return None

        ref_x1, ref_y1, ref_x2, ref_y2 = SLOT4_EMPTY_HOLDER_EXEMPLAR_BOX
        reference_corners = np.float32(
            [[
                [ref_x1, ref_y1],
                [ref_x2, ref_y1],
                [ref_x2, ref_y2],
                [ref_x1, ref_y2],
            ]]
        )
        projected = cv2.perspectiveTransform(reference_corners, homography)[0]
        if not np.isfinite(projected).all():
            return None
        current_height, current_width = current.shape[:2]
        px1 = max(0, int(np.floor(projected[:, 0].min())))
        py1 = max(0, int(np.floor(projected[:, 1].min())))
        px2 = min(current_width, int(np.ceil(projected[:, 0].max())))
        py2 = min(current_height, int(np.ceil(projected[:, 1].max())))
        if px2 <= px1 or py2 <= py1:
            return None
        projected_area_ratio = (
            (px2 - px1) * (py2 - py1)
            / max(1, current_width * current_height)
        )
        projected_aspect = (px2 - px1) / max(1, py2 - py1)
        if (
            projected_area_ratio < 0.002
            or projected_area_ratio > 0.065
            or projected_aspect < 0.65
            or projected_aspect > 4.8
        ):
            return None

        # A small margin lets SAM recover the silhouette while still excluding
        # the neighboring loose spool/table region that caused the screenshot
        # leak.
        pad_x = max(3, round((px2 - px1) * 0.07))
        pad_y = max(3, round((py2 - py1) * 0.07))
        px1 = max(0, px1 - pad_x)
        py1 = max(0, py1 - pad_y)
        px2 = min(current_width, px2 + pad_x)
        py2 = min(current_height, py2 + pad_y)

        patch = current[py1:py2, px1:px2]
        rgb = cv2.cvtColor(patch, cv2.COLOR_BGR2RGB)
        brightness = rgb.mean(axis=2)
        chroma = rgb.max(axis=2) - rgb.min(axis=2)
        pale_ratio = float(np.mean((brightness >= 120) & (chroma <= 70)))
        dark_detail_ratio = float(np.mean(brightness < 105))
        if pale_ratio < 0.20 or dark_detail_ratio > 0.55:
            return None

        reference_point = np.float32(
            [[[SLOT4_EMPTY_HOLDER_EXEMPLAR_POINT[0], SLOT4_EMPTY_HOLDER_EXEMPLAR_POINT[1]]]]
        )
        projected_point = cv2.perspectiveTransform(reference_point, homography)[0][0]
        target_0_1000 = [
            round(float(projected_point[0]) / max(1, current_width) * 1000),
            round(float(projected_point[1]) / max(1, current_height) * 1000),
        ]
        box_0_1000 = [
            round(px1 / current_width * 1000),
            round(py1 / current_height * 1000),
            round(px2 / current_width * 1000),
            round(py2 / current_height * 1000),
        ]
        target_0_1000[0] = max(box_0_1000[0], min(box_0_1000[2], target_0_1000[0]))
        target_0_1000[1] = max(box_0_1000[1], min(box_0_1000[3], target_0_1000[1]))

        # Do not require proximity to Qwen's pixel box here. Qwen is the
        # semantic/empty-slot gate, while this compiler exists specifically to
        # correct its coarse or misplaced pixel geometry. Requiring both boxes
        # to be close caused a correct RANSAC projection to be discarded in a
        # rotated live view, allowing the erroneous table/background box to
        # reach SAM2.
        if not self._point_patch_is_pale_holder(current_image_base64, target_0_1000):
            return None

        return qwen_candidate.model_copy(
            update={
                "bbox_0_1000": box_0_1000,
                "target_point_0_1000": target_0_1000,
                "confidence": min(0.97, max(qwen_candidate.confidence, 0.82)),
                "proposal_source": "qwen_flash_task_profile_exemplar",
                "visible_evidence": (
                    f"{qwen_candidate.visible_evidence} Task-profile Slot 4 "
                    f"exemplar mapped by SIFT/RANSAC ({inlier_count}/{len(good)} "
                    "inliers); current pale holder appearance verified and the "
                    "SAM2 prompt tightened to the visible holder surface."
                ).strip(),
            }
        )

    def _point_patch_is_pale_holder(
        self,
        image_base64: str,
        point_0_1000: list[int],
    ) -> bool:
        try:
            data = base64.b64decode(image_base64, validate=True)
            with Image.open(io.BytesIO(data)) as image:
                image = image.convert("RGB")
                width, height = image.size
                cx = round(point_0_1000[0] * width / 1000)
                cy = round(point_0_1000[1] * height / 1000)
                radius = max(10, min(width, height) // 48)
                crop = image.crop(
                    (
                        max(0, cx - radius),
                        max(0, cy - radius),
                        min(width, cx + radius),
                        min(height, cy + radius),
                    )
                )
                pixels = list(crop.getdata())
        except (ValueError, OSError, IndexError):
            return False
        if not pixels:
            return False
        count = len(pixels)
        red = sum(pixel[0] for pixel in pixels) / count
        green = sum(pixel[1] for pixel in pixels) / count
        blue = sum(pixel[2] for pixel in pixels) / count
        brightness = (red + green + blue) / 3
        chroma = max(red, green, blue) - min(red, green, blue)
        # The target surface is the pale white plastic holder.  This rejects
        # dark gray feeder caps, black table/background, and orange filament.
        return (
            brightness >= 145
            and chroma <= 65
            and red >= 115
            and green >= 115
            and blue >= 115
        )

    def _slot4_white_holder_prompt_box(self, box_0_1000: list[int]) -> list[int]:
        x1, y1, x2, _ = box_0_1000
        # Empirically stable for the standardized top/front AMS Lite view:
        # Qwen's mistaken feeder prompt is directly below the white Slot 4
        # holder.  Preserve its horizontal neighborhood but move the prompt to
        # the upper white holder surface and keep it tight enough for SAM2.
        repaired = [
            # The mistaken Slot 4 feeder box is already on the right side.
            # Extending it 115 units left admitted the central support column,
            # which SAM quite reasonably merged with the connected white
            # holder.  Keep the prompt on the projecting holder itself.
            max(0, x1 - 10),
            max(0, y1 - 350),
            min(1000, x2 - 160),
            min(1000, y1 - 150),
        ]
        if repaired[2] - repaired[0] < 80 or repaired[3] - repaired[1] < 80:
            return [610, 165, 845, 390]
        return repaired

    def verify(self, request: VerificationRequest) -> VerificationResult:
        job = self._get_or_recover_job(request.procedure_id)
        if job is None or job.status != "completed" or job.procedure is None:
            raise ValueError("Unknown or incomplete procedure_id")

        state = next(
            (
                item
                for item in job.procedure.states
                if item.state_id == request.current_step_id
            ),
            None,
        )
        if state is None:
            raise ValueError("current_step_id is not part of the procedure")

        try:
            if request.mode == "mock":
                result = self._mock_verification(request, state)
            elif request.comparison_mode == "before_after":
                result = self._verify_before_after_with_ollama(
                    request,
                    job.procedure,
                    state,
                )
            elif request.focus_condition:
                result = self._verify_focused_inspection_with_ollama(
                    request,
                    job.procedure,
                    state,
                )
            else:
                result = self._verify_with_ollama(request, job.procedure)
        except OllamaError as exc:
            # A cloud VLM can occasionally return HTTP 200 with an empty or
            # truncated message.  The client has already retried those
            # transient responses.  If all attempts fail, keep the task graph
            # intact and return a conservative, schema-valid uncertainty
            # result instead of turning one model response into an apparent
            # outage of the whole visual service.
            result = self._verification_service_uncertain(
                request=request,
                state=state,
                error=exc,
            )

        result.matched_step_id = request.current_step_id
        result.next_action = self._deterministic_next_action(
            result.status,
            state,
            job.procedure,
        )
        grounding_components = (
            request.focus_component_ids
            if request.focus_component_ids
            else state.target_components
        )
        if request.mode == "ollama" and self._allow_verification_grounding(
            result,
            state,
        ):
            # The verification response may already contain boxes in the
            # upright VLM image. Device profiles may additionally run a focused
            # grounding pass so that source and target arrow endpoints remain
            # separate. Unity and the
            # temporal tracker render in the uploaded sensor-image coordinate
            # system, so convert model boxes back to raw coordinates. Prefer
            # the deterministic local grounder for any component it supports.
            model_boxes = self._boxes_to_raw_coordinates(
                result.component_boxes_0_1000,
                request.image_rotation_degrees,
            )
            grounded_boxes = self._ground_components(
                request.image_base64,
                grounding_components,
                request.image_rotation_degrees,
                procedure=job.procedure,
                state_id=state.state_id,
            )
            grounded = self._merge_component_boxes(
                grounded_boxes,
                model_boxes,
            )
            if grounded:
                result.component_boxes_0_1000 = grounded
        elif request.mode == "ollama":
            result.component_boxes_0_1000 = []

        known_nodes = {node.inspection_id: node for node in state.observation_nodes}
        expected = list(dict.fromkeys(request.expected_inspection_ids))
        if not expected:
            expected = [node.inspection_id for node in state.observation_nodes]
        unknown_expected = [item for item in expected if item not in known_nodes]
        if unknown_expected:
            raise ValueError(
                "expected_inspection_ids contain unknown predicates: "
                + ", ".join(unknown_expected)
            )
        current_inspection_id = request.inspection_id
        if current_inspection_id is None and len(expected) == 1:
            current_inspection_id = expected[0]
        if current_inspection_id is not None and current_inspection_id not in known_nodes:
            raise ValueError("inspection_id is not part of the current step")

        run_key = (
            request.procedure_id,
            request.run_id or "default-run",
            request.current_step_id,
        )
        retained_server = self._verified_predicates.setdefault(run_key, set())
        legacy_bulk_verification = bool(
            job.procedure.task.task_type == "legacy"
            and request.inspection_id is None
            and not request.expected_inspection_ids
        )
        current_node = known_nodes.get(current_inspection_id or "")
        needs_region = bool(
            current_node is not None
            and current_node.verification_channel == "vision"
            and current_node.visualization != "none"
        )
        region_visible = bool(result.component_boxes_0_1000) or not needs_region
        current_passed = bool(
            current_inspection_id
            and result.status == "completed"
            and result.matched_step_id == request.current_step_id
            and result.confidence >= SAFE_ADVANCE_CONFIDENCE
            and str(result.evidence).strip()
            and region_visible
        )
        action_checkpoint_required = bool(
            state.state_type == "action"
            and request.request_purpose == "state_verification"
            and job.procedure.task.task_type
            in {"load_spool", "unload_spool", "swap_spool", "recover_visible_jam"}
        )
        if request.request_purpose == "guidance_localization":
            # This call only provides a semantic prompt for segmentation. It
            # may not retain evidence or move the task graph.
            current_passed = False
        elif action_checkpoint_required:
            current_passed = bool(
                current_passed
                and request.comparison_mode == "before_after"
                and result.same_area_visible
                and result.expected_change_visible
            )
        if current_passed and current_inspection_id:
            retained_server.add(current_inspection_id)
        elif legacy_bulk_verification and bool(
            result.status == "completed"
            and result.confidence >= SAFE_ADVANCE_CONFIDENCE
            and result.component_boxes_0_1000
        ):
            retained_server.update(expected)
            current_passed = True

        predicates: list[PredicateEvidence] = []
        for predicate_id in expected:
            is_current = predicate_id == current_inspection_id
            passed = predicate_id in retained_server
            if is_current:
                status = result.status if not passed else "completed"
                confidence = result.confidence
                regions = list(result.component_boxes_0_1000)
                visible = result.evidence
                failure_reason = None
                correction = None
                if result.status == "completed" and result.confidence < SAFE_ADVANCE_CONFIDENCE:
                    failure_reason = "该必要谓词置信度不足"
                    correction = "保持目标局部清晰，按指定视角补拍。"
                elif result.status == "completed" and not region_visible:
                    status = "uncertain"
                    failure_reason = "缺少可定位的可见证据区域"
                    correction = "靠近目标局部重拍；系统不会显示未经质量门的遮罩。"
                elif not passed:
                    failure_reason = result.evidence or "该必要谓词尚未通过"
                    correction = result.next_action
            elif passed:
                status = "completed"
                confidence = 1.0
                regions = []
                visible = "本次运行中已由服务器验证并保留。"
                failure_reason = None
                correction = None
            else:
                status = "not_started"
                confidence = 0.0
                regions = []
                visible = ""
                failure_reason = "尚未验证该必要谓词"
                correction = known_nodes[predicate_id].capture_instruction
            predicates.append(
                PredicateEvidence(
                    predicate_id=predicate_id,
                    status=status,
                    confidence=confidence,
                    evidence_region=regions,
                    visible_evidence=visible,
                    failure_reason=failure_reason,
                    correction_instruction=correction,
                )
            )

        # The last AMS Lite loading view is not, by itself, proof that loading
        # succeeded.  Reconstruct a fixed, paper-facing readiness checklist
        # from server-owned evidence retained across S0--S3.  This deliberately
        # ignores client-supplied history so a stale or optimistic phone cannot
        # unlock the final safety gate.
        load_completion_reasons: list[str] = []
        if (
            job.procedure.task.task_type == "load_spool"
            and state.state_id == "S3"
            and request.request_purpose == "state_verification"
        ):
            predicates, load_completion_reasons = self._ams_load_completion_predicates(
                request=request,
                procedure=job.procedure,
                current_result=result,
            )

        safety_reasons: list[str] = []
        if request.request_purpose == "guidance_localization":
            safety_reasons.append("本次请求只用于定位操作对象，禁止推进步骤")
        if action_checkpoint_required and request.comparison_mode != "before_after":
            safety_reasons.append("动作步骤缺少操作前后对比画面")
        if action_checkpoint_required and not result.same_area_visible:
            safety_reasons.append("操作前后画面不是可比较的同一局部")
        if action_checkpoint_required and not result.expected_change_visible:
            safety_reasons.append("没有看见该步骤要求的状态变化")
        missing = [item for item in expected if item not in retained_server]
        if missing:
            safety_reasons.append("必要状态谓词未全部通过：" + ", ".join(missing))
        safety_reasons.extend(load_completion_reasons)
        if not request.is_final_inspection:
            safety_reasons.append("当前不是本步骤最后一个观察点")
        elif (current_inspection_id or legacy_bulk_verification) and not current_passed:
            safety_reasons.append("最后一个必要谓词未在当前画面中通过")
        if result.matched_step_id != request.current_step_id:
            safety_reasons.append("视觉结果与当前步骤不一致")
        result.safe_to_advance = not safety_reasons
        result.predicates = predicates
        result.safety_gate_reasons = safety_reasons
        result.overlay_semantic = (
            "verified"
            if result.safe_to_advance
            else "error"
            if result.status == "wrong_operation"
            else "insufficient"
            if result.status == "uncertain" or not region_visible
            else "next_action"
        )
        result.inspection_id = current_inspection_id
        result.retained_inspection_ids = [
            item for item in expected if item in retained_server
        ]
        matched_node = next(
            (
                node
                for node in state.observation_nodes
                if node.inspection_id == current_inspection_id
            ),
            None,
        )
        result.visualization_type = (
            matched_node.visualization
            if matched_node is not None and result.component_boxes_0_1000
            else "none"
        )

        if request.mode == "ollama":
            self._save_debug_capture(
                "verify",
                request.image_base64,
                job.procedure,
                result.model_dump(),
                {
                    "current_step_id": request.current_step_id,
                    "history": request.history,
                    "inspection_id": request.inspection_id,
                    "focus_component_ids": request.focus_component_ids,
                    "focus_condition": request.focus_condition,
                    "completed_inspection_ids": request.completed_inspection_ids,
                    "expected_inspection_ids": request.expected_inspection_ids,
                    "is_final_inspection": request.is_final_inspection,
                },
            )

        if request.save_for_training:
            self._save_training_sample(request, result)
        return result

    def _ams_load_completion_predicates(
        self,
        *,
        request: VerificationRequest,
        procedure: ProcedureDocument,
        current_result: VerificationResult,
    ) -> tuple[list[PredicateEvidence], list[str]]:
        """Return the five mandatory, auditable AMS loading predicates.

        Earlier steps are considered complete only when this service retained
        every observation node for that state in the same run.  The final PTFE
        view supplies two related visible claims (continuous material evidence
        and absence of an obvious cross-slot/bend/tangle conflict), but both
        remain necessary and therefore both fail when S3 is not verified.
        """

        run_id = request.run_id or "default-run"
        state_by_id = {item.state_id: item for item in procedure.states}

        def state_passed(state_id: str) -> bool:
            candidate = state_by_id.get(state_id)
            if candidate is None or not candidate.observation_nodes:
                return False
            retained = self._verified_predicates.get(
                (request.procedure_id, run_id, state_id),
                set(),
            )
            expected_ids = {
                node.inspection_id for node in candidate.observation_nodes
            }
            return expected_ids.issubset(retained)

        s0_passed = state_passed("S0")
        s1_passed = state_passed("S1")
        s2_passed = state_passed("S2")
        s3_passed = state_passed("S3")

        rows = [
            (
                "selected_slot_identity_consistent",
                s0_passed,
                "服务器已验证用户确认的槽位身份与空槽起始状态。",
                "重新拍摄AMS Lite总览，确认槽位编号、空轴和同槽送料模块。",
                [],
                1.0 if s0_passed else 0.0,
            ),
            (
                "spool_stably_installed",
                s1_passed,
                "服务器已保留料盘稳定安装在目标轴上的操作后证据。",
                "回到料盘安装步骤，按同一局部补拍操作前后画面。",
                [],
                1.0 if s1_passed else 0.0,
            ),
            (
                "filament_entered_selected_slot_feeder",
                s2_passed,
                "服务器已保留料头进入同槽送料模块的操作后证据。",
                "近拍目标送料模块，证明料头已进入而不是仅靠近入口。",
                [],
                1.0 if s2_passed else 0.0,
            ),
            (
                "filament_visible_in_selected_slot_ptfe",
                s3_passed,
                current_result.evidence if s3_passed else "",
                "从上方斜视补拍同槽PTFE管，证明路径中存在连续耗材证据。",
                list(current_result.component_boxes_0_1000),
                current_result.confidence if s3_passed else 0.0,
            ),
            (
                "no_cross_slot_bend_or_tangle",
                s3_passed,
                current_result.evidence if s3_passed else "",
                "扩大局部视野补拍，排除跨槽、明显折弯或缠绕。",
                list(current_result.component_boxes_0_1000),
                current_result.confidence if s3_passed else 0.0,
            ),
        ]

        predicates: list[PredicateEvidence] = []
        missing: list[str] = []
        for predicate_id, passed, evidence, correction, regions, confidence in rows:
            if not passed:
                missing.append(predicate_id)
            predicates.append(
                PredicateEvidence(
                    predicate_id=predicate_id,
                    status="completed" if passed else "not_started",
                    confidence=confidence,
                    evidence_region=regions if passed else [],
                    visible_evidence=evidence,
                    failure_reason=(
                        None if passed else "该上料完成必要谓词缺少服务器保留证据"
                    ),
                    correction_instruction=None if passed else correction,
                    necessary=True,
                )
            )

        reasons = []
        if missing:
            reasons.append(
                "上料闭环五项证据未全部通过：" + ", ".join(missing)
            )
        return predicates, reasons

    def _verify_before_after_with_ollama(
        self,
        request: VerificationRequest,
        procedure: ProcedureDocument,
        state: Any,
    ) -> VerificationResult:
        """Compare explicit pre-action and post-action checkpoints.

        The model may use visible change as supporting evidence, but completion
        still depends on the manual-grounded postconditions.  Boxes must refer
        to the after frame so the phone can render correction guidance.
        """

        try:
            before_bytes = base64.b64decode(
                request.before_image_base64 or "",
                validate=True,
            )
            after_bytes = base64.b64decode(
                request.image_base64,
                validate=True,
            )
            before_image = self._normalize_image(
                rotate_jpeg_for_vlm(
                    before_bytes,
                    request.before_image_rotation_degrees,
                ),
                MAX_LIVE_IMAGE_SIDE,
            )
            after_image = self._normalize_image(
                rotate_jpeg_for_vlm(
                    after_bytes,
                    request.image_rotation_degrees,
                ),
                MAX_LIVE_IMAGE_SIDE,
            )
        except (ValueError, OSError) as exc:
            raise ValueError(
                "before_image_base64 and image_base64 must be valid images"
            ) from exc

        components = request.focus_component_ids or state.target_components
        condition = request.focus_condition or state.verification
        device_profile = profile_for_procedure(procedure)
        reference_images = self._reference_images_for_profile(
            device_profile,
            [state.state_id],
        )
        device_context = (
            device_profile.grounding_context(components)
            if device_profile is not None
            else ""
        )
        output_language = self._guidance_language_for_procedure(procedure)
        context = {
            "state_id": state.state_id,
            "instruction": state.instruction,
            "preconditions": state.preconditions,
            "postconditions": state.postconditions,
            "wrong_states": state.wrong_states,
            "visible_condition": condition,
            "requested_components": components,
            "manual_provenance": state.manual_provenance.model_dump(),
        }
        prompt = (
            "Act as a conservative before/after equipment-state verifier. "
            "IMAGE 1 is the live BEFORE checkpoint. IMAGE 2 is the live AFTER "
            "checkpoint. Any later images are manual references for component "
            "identity only. First confirm that both live images show the same "
            "device area and enough requested evidence. Then compare only "
            "visible facts. Return completed only when the AFTER image clearly "
            "satisfies the requested postcondition and does not match a wrong "
            "state. A visible change is supporting evidence, not proof by "
            "itself. Return wrong_operation only for a clear contradiction. "
            "Return uncertain when either checkpoint is blurred, occluded, "
            "poorly matched, outside the requested area, or when success would "
            "require inferring an internal or hidden state. matched_step_id "
            "must exactly equal the requested state_id. safe_to_advance is "
            "advisory and will be overwritten by the server. Return boxes only "
            "for clearly visible requested components in IMAGE 2, never IMAGE "
            "1 or a reference image. Set same_area_visible=true only when the "
            "same relevant local assembly is identifiable in both live frames. "
            "Set expected_change_visible=true only when the BEFORE frame visibly "
            "lacks the requested postcondition and the AFTER frame visibly gains "
            "it. Merely mounting a spool is not evidence that filament entered a "
            "feeder inlet or PTFE tube. Describe concrete before-to-after evidence "
            f"and write user-facing text in {output_language}.\n\n"
            f"CHECKPOINT CONTRACT: {json.dumps(context, ensure_ascii=False)}\n"
            f"DEVICE REFERENCE: {device_context}\n\n"
            "Return only one JSON object matching the supplied schema."
        )
        raw = self.ollama.chat_structured(
            prompt=prompt,
            schema=VerificationResult.model_json_schema(),
            images_base64=[
                before_image,
                after_image,
                *reference_images,
            ],
            max_tokens=720,
        )
        return VerificationResult.model_validate(raw)

    def _verify_focused_inspection_with_ollama(
        self,
        request: VerificationRequest,
        procedure: ProcedureDocument,
        state: Any,
    ) -> VerificationResult:
        """Verify one visible node without requiring the whole machine in view."""

        try:
            image_bytes = base64.b64decode(
                request.image_base64,
                validate=True,
            )
            normalized_image = self._normalize_image(
                rotate_jpeg_for_vlm(
                    image_bytes,
                    request.image_rotation_degrees,
                ),
                MAX_LIVE_IMAGE_SIDE,
            )
        except (ValueError, OSError) as exc:
            raise ValueError("image_base64 is not a valid image") from exc

        device_profile = profile_for_procedure(procedure)
        components = request.focus_component_ids or state.target_components
        device_context = (
            device_profile.grounding_context(components)
            if device_profile is not None
            else ""
        )
        reference_images = self._reference_images_for_profile(
            device_profile,
            [state.state_id],
        )
        output_language = self._guidance_language_for_procedure(procedure)
        prompt = (
            "Act as a conservative close-up equipment inspector. IMAGE 1 is "
            "the only live camera crop. Later images, if any, are manual "
            "references for identity only. Verify exactly ONE visible "
            "inspection condition; do not require the whole machine or infer "
            "hidden parts. Return completed only when the condition is clearly "
            "visible and satisfied, wrong_operation only when visible evidence "
            "contradicts it, and uncertain when the requested area is blurred, "
            "occluded, outside the crop, or not identifiable. matched_step_id "
            "must equal the requested step. safe_to_advance is advisory and "
            "will be overwritten by the server. Return tight boxes only for "
            "clearly visible requested components. "
            f"Write text in {output_language}.\n\n"
            f"STEP: {request.current_step_id}\n"
            f"INSPECTION NODE: {request.inspection_id or 'single'}\n"
            f"VISIBLE CONDITION: {request.focus_condition}\n"
            f"REQUESTED COMPONENTS: {json.dumps(components, ensure_ascii=False)}\n"
            f"MANUAL PAGE: {state.manual_provenance.page}\n"
            f"DEVICE REFERENCE: {device_context}\n\n"
            "Return only one JSON object matching the supplied schema."
        )
        raw = self.ollama.chat_structured(
            prompt=prompt,
            schema=VerificationResult.model_json_schema(),
            images_base64=[normalized_image, *reference_images],
            max_tokens=640,
        )
        return VerificationResult.model_validate(raw)

    def locate_state(
        self, request: StateLocalizationRequest
    ) -> StateLocalizationResult:
        job = self._get_or_recover_job(request.procedure_id)
        if job is None or job.status != "completed" or job.procedure is None:
            raise ValueError("Unknown or incomplete procedure_id")

        if request.mode == "mock":
            result = self._mock_state_localization(request, job.procedure)
        else:
            result = self._locate_observable_scene_state(
                request,
                job.procedure,
            )
        result = self._repair_ams_lite_overview_candidate(
            result,
            job.procedure,
        )
        result = self._validate_state_localization(result, job.procedure)
        recommended_state = next(
            state
            for state in job.procedure.states
            if state.state_id == result.recommended_step_id
        )
        if request.mode == "ollama" and self._allow_localization_grounding(
            result,
            recommended_state,
        ):
            model_boxes = self._boxes_to_raw_coordinates(
                result.component_boxes_0_1000,
                request.image_rotation_degrees,
            )
            grounded = self._ground_components(
                request.image_base64,
                recommended_state.target_components,
                request.image_rotation_degrees,
                procedure=job.procedure,
                state_id=recommended_state.state_id,
            )
            result.component_boxes_0_1000 = self._merge_component_boxes(
                grounded,
                model_boxes,
            )
        elif request.mode == "ollama":
            result.component_boxes_0_1000 = []
        if request.mode == "ollama":
            self._save_debug_capture(
                "locate",
                request.image_base64,
                job.procedure,
                result.model_dump(),
                {},
            )
        return result

    @staticmethod
    def _repair_ams_lite_overview_candidate(
        result: StateLocalizationResult,
        procedure: ProcedureDocument,
    ) -> StateLocalizationResult:
        """Route strong PTFE evidence to close-up review, never repeated loading."""
        if procedure.device.device_id != "bambu_a1_mini_ams_lite":
            return result
        # Keep the two identity fields internally consistent for the AMS-only
        # task.  The VLM often identifies the accessory correctly in one field
        # while leaving the other field uncertain.  This normalization does
        # not increase confidence or advance the state graph; it only prevents
        # a correctly recognized AMS Lite from being displayed as an unknown
        # A1 mini.
        result = result.model_copy(deep=True)
        identity_repaired = False
        if (
            result.device_configuration == "ams_lite"
            and result.device_identity in {"uncertain", "a1_mini"}
        ):
            result.device_identity = "ams_lite"
            identity_repaired = True
        elif (
            result.device_identity in {"ams_lite", "a1_mini_ams_lite"}
            and result.device_configuration == "uncertain"
        ):
            result.device_configuration = "ams_lite"
            identity_repaired = True
        if identity_repaired:
            result.unavailable_checks = [
                *result.unavailable_checks,
                "AMS Lite设备身份与配置字段已做一致性归一；未提高模型置信度。",
            ]
        state_ids = [state.state_id for state in procedure.states]
        if "S3" not in state_ids:
            return result
        evidence = f"{result.observed_summary} {result.evidence}"
        positive_ptfe = bool(
            re.search(r"PTFE\s*管内可见(?:连续)?橙色", evidence, re.I)
            or re.search(
                r"(?:orange|橙色).{0,30}(?:visible|可见).{0,20}PTFE",
                evidence,
                re.I,
            )
            or re.search(
                r"PTFE.{0,30}(?:visible|可见).{0,20}(?:orange|橙色)",
                evidence,
                re.I,
            )
        )
        if not positive_ptfe:
            return result

        repaired = result.model_copy(deep=True)
        repaired.completed_step_ids = state_ids[: state_ids.index("S3")]
        repaired.recommended_step_id = "S3"
        contradiction = bool(
            re.search(r"尚未插入|未插入|not[_ ]?inserted", evidence, re.I)
        )
        message = (
            "概览图已见1号PTFE管内橙色线材；为避免重复插料，"
            "服务器将起点改为S3近距离完成复核。"
        )
        if contradiction:
            repaired.confidence = min(max(repaired.confidence, 0.60), 0.72)
            message += "模型对送料口连接描述自相矛盾，必须多视角人工复核。"
        else:
            repaired.confidence = max(repaired.confidence, 0.78)
        repaired.unavailable_checks = [
            *repaired.unavailable_checks,
            message,
        ]
        return repaired

    def _locate_observable_scene_state(
        self,
        request: StateLocalizationRequest,
        procedure: ProcedureDocument,
    ) -> StateLocalizationResult:
        """Read visible facts first, then map facts to the manual state graph.

        The two-object demo is deliberately the first executable adapter. It
        avoids asking a small VLM to invent a step number from the whole graph.
        Other equipment can add scene-fact adapters behind the same contract.
        """
        device_profile = profile_for_procedure(procedure)
        if (
            device_profile is not None
            and device_profile.profile_id == "bambu_a1_mini"
        ):
            specialized = self._locate_a1_mini_facts(
                request,
                procedure,
                device_profile,
            )
            if specialized is not None:
                return specialized

        searchable = json.dumps(
            procedure.model_dump(),
            ensure_ascii=False,
        ).lower()
        is_book_pen_demo = (
            ("书" in searchable or "book" in searchable)
            and ("笔" in searchable or "pen" in searchable)
            and len(procedure.states) >= 3
        )
        if is_book_pen_demo:
            specialized = self._locate_book_pen_facts(request, procedure)
            if specialized is not None:
                return specialized
        return self._locate_state_with_ollama(request, procedure)

    def _locate_a1_mini_facts(
        self,
        request: StateLocalizationRequest,
        procedure: ProcedureDocument,
        device_profile: DeviceProfile,
    ) -> StateLocalizationResult | None:
        """Extract visible A1 mini facts before deterministic step mapping."""

        try:
            image_bytes = base64.b64decode(
                request.image_base64,
                validate=True,
            )
            normalized_image = self._normalize_image(
                rotate_jpeg_for_vlm(
                    image_bytes,
                    request.image_rotation_degrees,
                ),
                MAX_LIVE_IMAGE_SIDE,
            )
        except (ValueError, OSError):
            return None

        schema = {
            "type": "object",
            "properties": {
                "device_identity": {
                    "type": "string",
                    "enum": ["a1_mini", "not_a1_mini", "uncertain"],
                },
                "device_configuration": {
                    "type": "string",
                    "enum": ["external_spool", "ams_lite", "mixed", "uncertain"],
                },
                "spool_holder_base": {
                    "type": "string",
                    "enum": ["installed", "missing", "uncertain"],
                },
                "spool_holder": {
                    "type": "string",
                    "enum": ["installed", "missing", "uncertain"],
                },
                "ptfe_to_toolhead": {
                    "type": "string",
                    "enum": [
                        "connected_correctly",
                        "disconnected",
                        "wrong_location",
                        "uncertain",
                    ],
                },
                "external_spool": {
                    "type": "string",
                    "enum": [
                        "mounted_on_holder",
                        "not_mounted",
                        "wrong_location",
                        "unstable",
                        "uncertain",
                    ],
                },
                "filament_into_ptfe": {
                    "type": "string",
                    "enum": [
                        "inserted",
                        "not_inserted",
                        "wrong_opening",
                        "uncertain",
                    ],
                },
                "route_condition": {
                    "type": "string",
                    "enum": [
                        "clear",
                        "incomplete",
                        "bent_or_tangled",
                        "uncertain",
                    ],
                },
                "evidence": {"type": "string"},
            },
            "required": [
                "device_identity",
                "device_configuration",
                "spool_holder_base",
                "spool_holder",
                "ptfe_to_toolhead",
                "external_spool",
                "filament_into_ptfe",
                "route_condition",
                "evidence",
            ],
        }
        reference_images = self._reference_images_for_profile(
            device_profile,
            [state.state_id for state in procedure.states],
        )
        output_language = self._guidance_language_for_procedure(procedure)
        try:
            facts = self.ollama.chat_structured(
                prompt=(
                    "IMAGE 1 is a live camera view. Later images are official "
                    "A1 mini manual drawings for identity reference only. Read "
                    "only visible physical facts in IMAGE 1. Do not infer that "
                    "device_identity refers to the base printer only: an A1 mini "
                    "may have an AMS Lite unit, several PTFE tubes, or other "
                    "accessories beside it and must still be classified as "
                    "a1_mini when the base printer matches. "
                    "Do not classify identity from accessories alone. "
                    "Classify device_configuration from visible material input "
                    "hardware: external_spool for the single external holder, "
                    "ams_lite for an AMS Lite feeder, mixed only when both are "
                    "visibly connected, and uncertain when the relevant input "
                    "hardware is outside the crop. "
                    "power is off, the printer is cold, filament reached the "
                    "extruder, or an earlier action occurred. A spool mounted on "
                    "the holder visibly implies that the holder and its base are "
                    "installed. Use uncertain whenever a small connection point "
                    "is hidden or blurred. Return conservative JSON only.\n\n"
                    f"Write evidence in {output_language}.\n\n"
                    + device_profile.grounding_context(
                        [
                            component
                            for state in procedure.states
                            for component in state.target_components
                        ]
                    )
                ),
                schema=schema,
                images_base64=[normalized_image, *reference_images],
                max_tokens=768,
            )
        except (OllamaError, ValueError):
            return None

        identity = str(facts.get("device_identity", "uncertain"))
        configuration = str(facts.get("device_configuration", "uncertain"))
        base = str(facts.get("spool_holder_base", "uncertain"))
        holder = str(facts.get("spool_holder", "uncertain"))
        ptfe = str(facts.get("ptfe_to_toolhead", "uncertain"))
        spool = str(facts.get("external_spool", "uncertain"))
        filament = str(facts.get("filament_into_ptfe", "uncertain"))
        route = str(facts.get("route_condition", "uncertain"))

        # Later visible assemblies physically entail their mounting hardware.
        base_done = base == "installed" or holder == "installed" or spool == "mounted_on_holder"
        holder_done = holder == "installed" or spool == "mounted_on_holder"
        checks = [
            identity == "a1_mini",
            base_done,
            holder_done,
            ptfe == "connected_correctly",
            spool == "mounted_on_holder",
            filament == "inserted",
        ]
        completed_count = 0
        for satisfied in checks:
            if not satisfied:
                break
            completed_count += 1

        state_ids = [state.state_id for state in procedure.states]
        recommended_index = min(completed_count, len(state_ids) - 1)
        completed = state_ids[:recommended_index]
        recommended = state_ids[recommended_index]

        fact_summary = (
            f"A1_FACTS device={identity}; configuration={configuration}; "
            f"base={base}; holder={holder}; "
            f"ptfe={ptfe}; spool={spool}; filament={filament}; route={route}. "
            f"{str(facts.get('evidence', '')).strip()}"
        )
        uncertain_values = {
            identity,
            configuration,
            base,
            holder,
            ptfe,
            spool,
            filament,
            route,
        }
        confidence = 0.82 if "uncertain" not in uncertain_values else 0.62
        use_english = output_language == "English"
        unavailable = [
            (
                "The image alone cannot confirm power-off, cold state, internal feeding, temperature, or sensor state."
                if use_english
                else "仅凭画面不能确认断电、冷机、内部送料、温度或传感器状态。"
            )
        ]
        if identity != "a1_mini":
            confidence = min(confidence, 0.35)
            unavailable.append(
                "The device model is not reliably identified, so the starting step cannot be selected automatically."
                if use_english
                else "设备型号没有被可靠确认，不能自动选择操作起点。"
            )
            recommended = state_ids[0]
            completed = []
        if "uncertain" in uncertain_values:
            unavailable.append(
                "At least one small component or connection is not visible; move closer and adjust the angle."
                if use_english
                else "至少一个小部件或连接点不可见，请靠近并调整角度。"
            )

        return StateLocalizationResult(
            observed_summary=fact_summary,
            completed_step_ids=completed,
            recommended_step_id=recommended,
            evidence=fact_summary,
            confidence=confidence,
            requires_human_confirmation=True,
            unavailable_checks=unavailable,
            component_boxes_0_1000=[],
            device_identity=identity,
            device_configuration=configuration,
            procedure_compatible=(
                "true"
                if configuration == "external_spool"
                else (
                    "false"
                    if configuration in {"ams_lite", "mixed"}
                    else "uncertain"
                )
            ),
            capture_mode="manual_roi",
        )

    def _locate_book_pen_facts(
        self,
        request: StateLocalizationRequest,
        procedure: ProcedureDocument,
    ) -> StateLocalizationResult | None:
        try:
            image_bytes = base64.b64decode(
                request.image_base64,
                validate=True,
            )
            normalized_image = self._normalize_image(
                rotate_jpeg_for_vlm(
                    image_bytes,
                    request.image_rotation_degrees,
                ),
                MAX_LIVE_IMAGE_SIDE,
            )
        except (ValueError, OSError):
            return None

        schema = {
            "type": "object",
            "properties": {
                "book_state": {
                    "type": "string",
                    "enum": ["open", "closed", "uncertain"],
                },
                "pen_relation": {
                    "type": "string",
                    "enum": [
                        "left_of_book",
                        "on_book_lower_half",
                        "on_book_right_half",
                        "other",
                        "uncertain",
                    ],
                },
                "pen_orientation": {
                    "type": "string",
                    "enum": ["horizontal", "vertical", "uncertain"],
                },
                "evidence": {"type": "string"},
            },
            "required": [
                "book_state",
                "pen_relation",
                "pen_orientation",
                "evidence",
            ],
        }
        try:
            facts = self.ollama.chat_structured(
                prompt=(
                    "Inspect only the visible physical arrangement. Is the "
                    "main book open or closed? Where is the turquoise/blue pen "
                    "relative to the book, and is the pen horizontal or "
                    "vertical? Do not infer task history or a procedure step. "
                    "Return conservative JSON and use uncertain when unclear."
                ),
                schema=schema,
                images_base64=[normalized_image],
                max_tokens=512,
            )
        except (OllamaError, ValueError):
            return None

        state_ids = [state.state_id for state in procedure.states]
        book_state = str(facts.get("book_state", "uncertain"))
        pen_relation = str(facts.get("pen_relation", "uncertain"))
        orientation = str(facts.get("pen_orientation", "uncertain"))

        recommended_index = 0
        confidence = 0.45
        if book_state == "open" and pen_relation == "left_of_book":
            recommended_index = min(1, len(state_ids) - 1)
            confidence = 0.86
        elif book_state == "closed" and pen_relation == "left_of_book":
            recommended_index = min(2, len(state_ids) - 1)
            confidence = 0.88
        elif (
            book_state == "closed"
            and pen_relation == "on_book_lower_half"
            and orientation == "horizontal"
        ):
            recommended_index = min(3, len(state_ids) - 1)
            confidence = 0.88
        elif (
            book_state == "closed"
            and pen_relation == "on_book_right_half"
            and orientation == "vertical"
        ):
            recommended_index = len(state_ids) - 1
            confidence = 0.90
        elif book_state == "closed":
            # Closing the book is visibly complete even when the pen is in an
            # off-script arrangement. Resume from the pen-placement action
            # instead of incorrectly sending the user back to the initial state.
            recommended_index = min(2, len(state_ids) - 1)
            confidence = 0.70

        recommended = state_ids[recommended_index]
        facts_zh = (
            f"可见场景事实：书={book_state}；笔相对位置={pen_relation}；"
            f"笔方向={orientation}。{facts.get('evidence', '')}"
        )
        unavailable = []
        if "uncertain" in (book_state, pen_relation, orientation):
            unavailable.append("至少一个场景事实不确定，请调整角度后确认起点。")
            confidence = min(confidence, 0.45)
        return StateLocalizationResult(
            observed_summary=facts_zh,
            completed_step_ids=state_ids[:recommended_index],
            recommended_step_id=recommended,
            evidence=facts_zh,
            confidence=confidence,
            requires_human_confirmation=True,
            unavailable_checks=unavailable,
            component_boxes_0_1000=[],
        )

    def _load_mock_procedure(
        self, uploads: list[tuple[str, str, bytes]]
    ) -> ProcedureDocument:
        filenames = " ".join(filename.upper() for filename, _, _ in uploads)
        path = (
            TWO_OBJECT_MOCK_PROCEDURE_PATH
            if "TWO_OBJECT_BOOK_PEN" in filenames
            else (
                HOME_RELOCATION_MOCK_PROCEDURE_PATH
                if "HOME_OBJECT_RELOCATION" in filenames
                else (
                    HOME_MOCK_PROCEDURE_PATH
                    if "HOME_DESK_KIT" in filenames
                    else MOCK_PROCEDURE_PATH
                )
            )
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        return ProcedureDocument.model_validate(payload)

    def _prepare_manual_inputs(
        self, uploads: list[tuple[str, str, bytes]]
    ) -> tuple[str, list[str]]:
        if not uploads:
            raise ValueError("At least one PDF or image is required")

        total_bytes = sum(len(data) for _, _, data in uploads)
        if total_bytes > MAX_UPLOAD_BYTES:
            raise ValueError("Manual upload exceeds the 25 MB demo limit")

        extracted_text: list[str] = []
        images: list[str] = []
        for filename, content_type, data in uploads:
            suffix = Path(filename).suffix.lower()
            if content_type == "application/pdf" or suffix == ".pdf":
                text, rendered = self._read_pdf(data)
                extracted_text.extend(text)
                images.extend(rendered)
            elif content_type.startswith("image/") or suffix in {
                ".jpg",
                ".jpeg",
                ".png",
                ".webp",
            }:
                images.append(self._normalize_image(data))
            else:
                raise ValueError(f"Unsupported manual file: {filename}")

        if not images and not any(item.strip() for item in extracted_text):
            raise ValueError("No readable manual content was found")

        text_block = "\n\n".join(extracted_text)
        return text_block[:60_000], images[:MAX_MANUAL_PAGES]

    def _read_pdf(self, data: bytes) -> tuple[list[str], list[str]]:
        reader = PdfReader(io.BytesIO(data))
        texts = []
        for index, page in enumerate(reader.pages[:MAX_MANUAL_PAGES], start=1):
            page_text = page.extract_text() or ""
            texts.append(f"[PAGE {index}]\n{page_text}")

        executable = shutil.which("pdftoppm")
        if executable is None:
            return texts, []

        images = []
        with tempfile.TemporaryDirectory(prefix="manual2ar-pdf-") as directory:
            directory_path = Path(directory)
            pdf_path = directory_path / "manual.pdf"
            output_prefix = directory_path / "page"
            pdf_path.write_bytes(data)
            completed = subprocess.run(
                [
                    executable,
                    "-f",
                    "1",
                    "-l",
                    str(min(len(reader.pages), MAX_MANUAL_PAGES)),
                    "-jpeg",
                    "-r",
                    "110",
                    str(pdf_path),
                    str(output_prefix),
                ],
                check=False,
                capture_output=True,
                timeout=60,
            )
            if completed.returncode != 0:
                return texts, []
            for image_path in sorted(directory_path.glob("page-*.jpg")):
                images.append(self._normalize_image(image_path.read_bytes()))
        return texts, images

    def _normalize_image(
        self, data: bytes, max_side: int = MAX_IMAGE_SIDE
    ) -> str:
        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((max_side, max_side))
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=88)
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    def _extract_manual_action_evidence(
        self,
        extracted_text: str,
        images: list[str],
        output_language: str,
    ) -> dict[str, Any]:
        """Stage 1: collect grounded manual actions before planning states."""

        schema = {
            "type": "object",
            "properties": {
                "device_name": {"type": "string"},
                "manual_id": {"type": "string"},
                "actions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "order": {"type": "integer"},
                            "action_text": {"type": "string"},
                            "component_names": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "page": {"type": "integer"},
                            "section": {"type": "string"},
                            "source_text": {"type": "string"},
                            "warnings": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": [
                            "order",
                            "action_text",
                            "component_names",
                            "page",
                            "section",
                            "source_text",
                            "warnings",
                        ],
                    },
                },
            },
            "required": ["device_name", "manual_id", "actions"],
        }
        return self.ollama.chat_structured(
            prompt=(
                "Stage 1 of a manual compiler. Extract only user-executable "
                "equipment actions explicitly supported by the supplied manual. "
                "Keep the manual order and exact page provenance. Do not create "
                "AR, UI, software, progress, confidence, or inferred safety steps. "
                "If one sentence explicitly orders multiple actions, return one "
                "entry per action; otherwise do not invent an order. source_text "
                "must be a short exact manual excerpt. Write action_text, section, "
                f"component names, and warnings in {output_language}. Return JSON only.\n\n"
                f"EXTRACTED MANUAL TEXT:\n{extracted_text}"
            ),
            schema=schema,
            images_base64=images,
            max_tokens=2400,
        )

    def _compile_observation_nodes_with_ollama(
        self,
        payload: dict[str, Any],
        action_evidence: dict[str, Any],
        output_language: str,
    ) -> dict[str, Any]:
        """Stage 3: compile camera-sized checks for a locked state graph."""

        node_schema = {
            "type": "object",
            "properties": {
                "states": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "state_id": {"type": "string"},
                            "observation_nodes": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "condition": {"type": "string"},
                                        "component_ids": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "viewpoint": {
                                            "type": "string",
                                            "enum": [
                                                "front", "rear", "left", "right",
                                                "top", "bottom", "close_up", "overview",
                                            ],
                                        },
                                        "capture_instruction": {"type": "string"},
                                        "evidence_type": {
                                            "type": "string",
                                            "enum": [
                                                "presence", "connection", "position",
                                                "orientation", "display", "relation",
                                            ],
                                        },
                                        "visualization": {
                                            "type": "string",
                                            "enum": ["box", "mask", "arrow", "polyline", "none"],
                                        },
                                        "verification_channel": {
                                            "type": "string",
                                            "enum": ["vision", "sensor", "manual"],
                                        },
                                        "requires_same_frame": {"type": "boolean"},
                                    },
                                    "required": [
                                        "condition", "component_ids", "viewpoint",
                                        "capture_instruction", "evidence_type",
                                        "visualization", "verification_channel",
                                        "requires_same_frame",
                                    ],
                                },
                            },
                        },
                        "required": ["state_id", "observation_nodes"],
                    },
                }
            },
            "required": ["states"],
        }
        locked = [
            {
                "state_id": state.get("state_id"),
                "instruction": state.get("instruction"),
                "postconditions": state.get("postconditions"),
                "target_components": state.get("target_components"),
                "manual_provenance": state.get("manual_provenance"),
            }
            for state in payload.get("states", [])
        ]
        raw = self.ollama.chat_structured(
            prompt=(
                "Stage 3 of a manual compiler. The action graph is locked. For "
                "every postcondition, return exactly one camera-sized observation "
                "node with exactly the same condition text. Do not add, remove, "
                "merge, split, or reorder states. Choose a viewpoint and concise "
                "framing instruction. Use vision only for directly visible facts. "
                "Power-off, temperature, internal feeding, hidden sensor state, "
                "and other non-visible facts must use sensor or manual with "
                "visualization none. Use polyline for long tubes/routes, arrow for "
                "visible source-to-target relocation, mask for compact solid parts, "
                "and box when segmentation is inappropriate. Write user-facing "
                f"text in {output_language}. Return JSON only.\n\n"
                "LOCKED STATES:\n"
                + json.dumps(locked, ensure_ascii=False)
                + "\n\nEXTRACTED ACTION EVIDENCE:\n"
                + json.dumps(action_evidence, ensure_ascii=False)
            ),
            schema=node_schema,
            max_tokens=2400,
        )
        by_id = {
            str(item.get("state_id")): item.get("observation_nodes")
            for item in raw.get("states", [])
            if isinstance(item, dict)
        }
        for state in payload.get("states", []):
            nodes = by_id.get(str(state.get("state_id")))
            if not isinstance(nodes, list) or not nodes:
                raise ValueError(
                    f"No observation nodes returned for {state.get('state_id')}"
                )
            state["observation_nodes"] = nodes
        return payload

    def _analyze_with_ollama(
        self,
        extracted_text: str,
        images: list[str],
        guidance_language: str = "zh",
        on_constraint_repair: Callable[[], None] | None = None,
    ) -> ProcedureDocument:
        output_language = (
            "Simplified Chinese (zh-CN)"
            if guidance_language == "zh"
            else "English"
        )
        action_evidence = self._extract_manual_action_evidence(
            extracted_text,
            images,
            output_language,
        )
        prompt = (
            "Stage 2 of a multimodal manual compiler. Compile the extracted "
            "action evidence into an auditable "
            "procedure state graph. Use only the supplied pages and extracted "
            "text. Do not invent device capabilities or safety rules. Every "
            "state must include manual provenance, observable preconditions, "
            "observable postconditions, likely wrong states, target components, "
            "warnings, a verification type, and next_on_success. If information "
            "is missing, use conservative wording and require human review. "
            f"Write every user-facing instruction, condition, warning, section "
            f"label, verification description, and device name in {output_language}, "
            "regardless of the source manual language. Preserve model numbers "
            "and part identifiers accurately. "
            "For every relocation instruction, target_components must include "
            "exactly named source:<movable object> and target:<visible destination "
            "object or region> entries so a 2D arrow can be drawn.\n\n"
            "For a non-relocation action, target_components must contain only "
            "the manipulated object as source:<object>; objects that merely stay "
            "unchanged belong in preconditions/postconditions, not targets. Each "
            "action precondition must describe the visible state before action, "
            "each postcondition the distinct visible state after action, and each "
            "wrong state a concrete contradiction. Never copy one list into all "
            "three fields.\n\n"
            "A procedure state is either an observable initial_state checkpoint "
            "or a user-executable action. Exclude document titles, goals, system "
            "architecture, UI behavior, AR visualization descriptions, status "
            "labels, schema field names, error handling, completion messages, "
            "and explanations of how the guidance software works. In particular, "
            "never turn current-progress localization, next_on_success, automatic "
            "advancement, confidence, voice narration, Unity, VLM, or Mock notes "
            "into equipment steps.\n\n"
            "Each action state must contain only one primary user action. If the "
            "extracted evidence explicitly orders multiple actions, keep them as "
            "separate states. Do not split an action when the manual does not "
            "provide an order, and do not invent intermediate actions. You may "
            "leave observation_nodes empty in this stage; Stage 3 compiles them "
            "from the locked postconditions.\n\n"
            "Return only one JSON object that exactly matches the supplied JSON "
            "schema. Do not use Markdown fences or explanatory prose.\n\n"
            "EXTRACTED ACTION EVIDENCE:\n"
            + json.dumps(action_evidence, ensure_ascii=False)
            + "\n\n"
            f"EXTRACTED MANUAL TEXT:\n{extracted_text}"
        )
        raw = self.ollama.chat_structured(
            prompt=prompt,
            schema=ProcedureDocument.model_json_schema(),
            images_base64=images,
        )
        sanitized = self._sanitize_procedure_payload(raw)
        if self._constraints_need_repair(sanitized):
            if on_constraint_repair is not None:
                on_constraint_repair()
            sanitized = self._repair_observable_constraints(
                sanitized,
                extracted_text,
                guidance_language,
            )
        sanitized = self._compile_observation_nodes_with_ollama(
            sanitized,
            action_evidence,
            output_language,
        )
        sanitized = self._sanitize_procedure_payload(sanitized)
        return ProcedureDocument.model_validate(sanitized)

    def _repair_observable_constraints(
        self,
        payload: dict[str, Any],
        extracted_text: str,
        guidance_language: str = "zh",
    ) -> dict[str, Any]:
        """Repair weak predicates without allowing the MLLM to re-plan steps."""

        repair_schema = {
            "type": "object",
            "properties": {
                "states": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "state_id": {"type": "string"},
                            "preconditions": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "postconditions": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "wrong_states": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "target_components": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "verification": {"type": "string"},
                            "source_text": {"type": "string"},
                        },
                        "required": [
                            "state_id",
                            "preconditions",
                            "postconditions",
                            "wrong_states",
                            "target_components",
                            "verification",
                            "source_text",
                        ],
                    },
                }
            },
            "required": ["states"],
        }
        focused_states = [
            {
                "state_id": state.get("state_id"),
                "instruction": state.get("instruction"),
                "preconditions": state.get("preconditions"),
                "postconditions": state.get("postconditions"),
                "wrong_states": state.get("wrong_states"),
                "target_components": state.get("target_components"),
                "verification": state.get("verification"),
                "manual_provenance": state.get("manual_provenance"),
                "manual_excerpt": self._manual_excerpt_for_state(
                    extracted_text,
                    state,
                ),
            }
            for state in payload["states"]
        ]
        raw_repairs = self.ollama.chat_structured(
            prompt=(
                "Repair only observable state constraints in an already locked "
                "manual procedure. Preserve every state_id and instruction; do "
                "not add, remove, reorder, merge, or split states. Nearby prose "
                "is authoritative: do not reduce a condition to an object label "
                "when the manual states position, orientation, open/closed state, "
                "contact, display value, or another visible relation. Exclude UI, "
                "AR arrows/highlights, automatic advancement, software behavior, "
                "and research goals. source_text must be a short exact supporting "
                "manual excerpt. For relocation, use source:<object> and "
                "target:<visible destination>; otherwise use source:<manipulated "
                "object>. Return repairs for every supplied state and only the "
                "requested JSON object. Write repaired user-facing text in "
                + (
                    "Simplified Chinese (zh-CN)."
                    if guidance_language == "zh"
                    else "English."
                )
                + "\n\nLOCKED STATES:\n"
                + json.dumps(focused_states, ensure_ascii=False)
                + "\n\nMANUAL TEXT:\n"
                + extracted_text[:60_000]
            ),
            schema=repair_schema,
            max_tokens=1800,
        )
        known = {state["state_id"]: state for state in payload["states"]}
        repairs = raw_repairs.get("states")
        if not isinstance(repairs, list):
            return payload
        seen: set[str] = set()
        for repair in repairs:
            if not isinstance(repair, dict):
                continue
            state_id = str(repair.get("state_id", ""))
            if state_id not in known or state_id in seen:
                continue
            seen.add(state_id)
            target = known[state_id]
            for field in (
                "preconditions",
                "postconditions",
                "wrong_states",
                "target_components",
            ):
                value = repair.get(field)
                if isinstance(value, list) and value:
                    target[field] = value
            verification = str(repair.get("verification", "")).strip()
            if verification and not self._contains_guidance_meta(verification):
                target["verification"] = verification
            source_text = str(repair.get("source_text", "")).strip()
            if source_text:
                provenance = target.get("manual_provenance")
                if isinstance(provenance, dict):
                    provenance["source_text"] = source_text
        if seen != set(known):
            return payload

        # Small local MLLMs can still quote a heading and ignore the prose even
        # after a focused repair request. Fall back to exact observable clauses
        # from the locked initial-state section; this is manual-text based, not
        # a book/pen-specific state rule.
        for state in payload["states"]:
            excerpt = self._manual_excerpt_for_state(extracted_text, state)
            clauses = self._observable_clauses(excerpt)
            provenance = state.get("manual_provenance")
            if isinstance(provenance, dict) and not self._supporting_excerpt_ok(
                provenance.get("source_text"),
                state.get("instruction"),
            ):
                provenance["source_text"] = (
                    "；".join(clauses) if clauses else excerpt[:600].strip()
                )
            if state.get("state_type") == "initial_state":
                current = self._split_conditions(state.get("postconditions"))
                if self._condition_information_score(
                    clauses
                ) > self._condition_information_score(current):
                    state["postconditions"] = clauses
        return self._sanitize_procedure_payload(payload)

    @staticmethod
    def _sanitize_procedure_payload(raw: dict[str, Any]) -> dict[str, Any]:
        payload = json.loads(json.dumps(raw))
        states = payload.get("states")
        if not isinstance(states, list) or not states:
            raise ValueError("Model returned no procedure states")

        states = [
            state
            for state in states
            if isinstance(state, dict)
            and not ManualService._looks_like_meta_state(state)
        ]
        states = ManualService._deduplicate_states(states)
        if not states:
            raise ValueError("Model returned no executable or observable states")
        payload["states"] = states

        for index, state in enumerate(states):
            if not isinstance(state, dict):
                raise ValueError("Model returned an invalid procedure state")
            state["state_id"] = f"S{index}"
            state["step_index"] = index
            instruction_lower = str(state.get("instruction", "")).lower()
            state["state_type"] = (
                "initial_state"
                if index == 0
                and any(
                    marker in instruction_lower
                    for marker in (
                        "初始状态",
                        "开始前状态",
                        "确认初始",
                        "initial state",
                        "before starting",
                    )
                )
                else "action"
            )
            state["next_on_success"] = (
                f"S{index + 1}" if index < len(states) - 1 else None
            )
            postconditions = state.get("postconditions")
            if not isinstance(postconditions, list) or not postconditions:
                visible_conditions = state.get("preconditions")
                verification_fallback = str(
                    state.get("verification", "")
                ).strip()
                state["postconditions"] = (
                    list(visible_conditions)
                    if isinstance(visible_conditions, list)
                    and visible_conditions
                    else [
                        verification_fallback
                        or str(
                            state.get(
                                "instruction", "需要人工确认完成条件"
                            )
                        )
                    ]
                )
            preconditions = state.get("preconditions")
            postconditions = state.get("postconditions")
            verification = str(state.get("verification", "")).strip()
            if (
                index > 0
                and isinstance(preconditions, list)
                and isinstance(postconditions, list)
                and preconditions
                and preconditions == postconditions
                and verification
            ):
                state["postconditions"] = [verification]
            instruction = str(state.get("instruction", ""))
            components = state.get("target_components")
            if "合上" in instruction and "书" in instruction:
                state["target_components"] = ["source:书"]
                components = state["target_components"]
            if isinstance(components, list) and "移动到" in instruction:
                has_source = any(str(item).startswith("source:") for item in components)
                has_target = any(str(item).startswith("target:") for item in components)
                if not (has_source and has_target):
                    move_match = re.search(
                        r"把(.+?)移动到(.+?)(?:，|。|$)", instruction
                    )
                    if move_match is not None:
                        state["target_components"] = [
                            f"source:{move_match.group(1).strip()}",
                            f"target:{move_match.group(2).strip()}",
                        ]

        for index, state in enumerate(states):
            state["preconditions"] = ManualService._split_conditions(
                state.get("preconditions")
            )
            state["postconditions"] = ManualService._split_conditions(
                state.get("postconditions")
            )
            state["wrong_states"] = ManualService._split_conditions(
                state.get("wrong_states")
            )
            components = state.get("target_components")
            normalized_components: list[str] = []
            if isinstance(components, list):
                for raw_component in components:
                    component = str(raw_component).strip()
                    if not component:
                        continue
                    if not component.startswith(("source:", "target:")):
                        component = "source:" + component
                    if component not in normalized_components:
                        normalized_components.append(component)
            state["target_components"] = normalized_components

            verification = str(state.get("verification", "")).strip()
            if ManualService._contains_guidance_meta(verification):
                state["verification"] = "；".join(state["postconditions"])

            if state["state_type"] == "initial_state":
                state["preconditions"] = [
                    "说明书要求的目标部件完整入镜且无遮挡"
                ]

        # Compile one observable boundary state between each pair of actions.
        # MLLMs often describe the same boundary twice with different detail:
        # once as the previous postcondition and once as the next precondition.
        # Keep the richer description rather than blindly overwriting the next
        # step and losing useful visible predicates such as object position.
        for index in range(1, len(states)):
            previous = states[index - 1]
            current = states[index]
            previous_post = previous["postconditions"]
            current_pre = current["preconditions"]
            if not current_pre:
                boundary = list(previous_post)
            elif not previous_post:
                boundary = list(current_pre)
            elif ManualService._condition_information_score(
                current_pre
            ) > ManualService._condition_information_score(previous_post):
                boundary = list(current_pre)
            else:
                boundary = list(previous_post)
            previous["postconditions"] = list(boundary)
            current["preconditions"] = list(boundary)

        for index, state in enumerate(states):
            if state["preconditions"] == state["postconditions"]:
                verification_conditions = ManualService._split_conditions(
                    [state.get("verification", "")]
                )
                if (
                    verification_conditions
                    and verification_conditions != state["preconditions"]
                ):
                    state["postconditions"] = verification_conditions
                else:
                    raise ValueError(
                        f"Step S{index} has identical preconditions and "
                        "postconditions; the manual/model did not provide an "
                        "observable state change"
                    )

            if (
                not state["wrong_states"]
                or state["wrong_states"] == state["postconditions"]
                or state["wrong_states"] == state["preconditions"]
                or all(
                    str(condition).startswith(("不满足：", "not satisfied:"))
                    for condition in state["wrong_states"]
                )
            ):
                state["wrong_states"] = [
                    "不满足：" + condition
                    for condition in state["postconditions"]
                ]

            if ManualService._has_multiple_independent_actions(
                str(state.get("instruction", ""))
            ):
                raise ValueError(
                    f"Step S{index} contains multiple independently ordered "
                    "actions and must be split by the manual compiler"
                )

            state["observation_nodes"] = ManualService._normalize_observation_nodes(
                state,
                index,
            )

        task = payload.get("task")
        if not isinstance(task, dict):
            raise ValueError("Model returned no procedure task")
        manual_id = str(task.get("manual_id", "manual")).strip() or "manual"
        task_id = str(task.get("task_id", "")).strip()
        if not task_id or ManualService._contains_guidance_meta(task_id):
            task["task_id"] = manual_id + "_procedure"
        task["initial_state"] = "S0"
        task["terminal_states"] = [f"S{len(states) - 1}"]
        device = payload.get("device")
        if isinstance(device, dict):
            device["role"] = "manual_defined_equipment"
        return payload

    @staticmethod
    def _has_multiple_independent_actions(instruction: str) -> bool:
        text = instruction.strip().lower()
        if not text:
            return False
        # Only reject explicit sequential clauses. Coordinated descriptions
        # such as "insert and ensure fully seated" remain one physical action.
        separators = (
            "然后",
            "随后",
            "接着",
            "再将",
            "再把",
            " after that ",
            " then ",
            " next,",
        )
        return any(marker in text for marker in separators)

    @staticmethod
    def _normalize_observation_nodes(
        state: dict[str, Any],
        state_index: int,
    ) -> list[dict[str, Any]]:
        conditions = ManualService._split_conditions(state.get("postconditions"))
        supplied = state.get("observation_nodes")
        supplied_nodes = supplied if isinstance(supplied, list) else []
        provenance = state.get("manual_provenance")
        if not isinstance(provenance, dict):
            provenance = {
                "page": 1,
                "section": "需要人工核对来源",
                "source_text": None,
            }
            state["manual_provenance"] = provenance
        targets = [
            str(item).strip()
            for item in state.get("target_components", [])
            if str(item).strip()
        ] or ["source:设备当前操作区域"]

        normalized: list[dict[str, Any]] = []
        for condition_index, condition in enumerate(conditions, start=1):
            candidate = next(
                (
                    item
                    for item in supplied_nodes
                    if isinstance(item, dict)
                    and str(item.get("condition", "")).strip() == condition
                ),
                {},
            )
            components = candidate.get("component_ids")
            if not isinstance(components, list) or not any(
                str(item).strip() for item in components
            ):
                components = targets
            components = list(dict.fromkeys(str(item).strip() for item in components))

            lowered = condition.lower()
            non_visual_sensor = any(
                marker in lowered
                for marker in (
                    "温度", "temperature", "传感器", "sensor", "错误代码",
                    "error code", "屏幕显示", "display shows",
                )
            )
            non_visual_manual = any(
                marker in lowered
                for marker in (
                    "断电", "power off", "冷却", "cooled", "内部送料",
                    "internal feed", "已完成校准", "calibration complete",
                )
            )
            channel = str(candidate.get("verification_channel", "vision"))
            if non_visual_sensor:
                channel = "sensor"
            elif non_visual_manual:
                channel = "manual"
            elif channel not in {"vision", "sensor", "manual"}:
                channel = "vision"

            viewpoint = str(candidate.get("viewpoint", ""))
            if viewpoint not in {
                "front", "rear", "left", "right", "top", "bottom",
                "close_up", "overview",
            }:
                viewpoint = ManualService._viewpoint_for_condition(condition)
            evidence_type = str(candidate.get("evidence_type", ""))
            if evidence_type not in {
                "presence", "connection", "position", "orientation", "display", "relation",
            }:
                evidence_type = ManualService._evidence_type_for_condition(condition)
            visualization = str(candidate.get("visualization", ""))
            if channel != "vision":
                visualization = "none"
            elif visualization not in {"box", "mask", "arrow", "polyline", "none"}:
                visualization = ManualService._visualization_for_condition(
                    condition,
                    components,
                )

            capture = str(candidate.get("capture_instruction", "")).strip()
            if not capture:
                capture = ManualService._capture_instruction(
                    condition,
                    viewpoint,
                    channel,
                )
            normalized.append(
                {
                    "inspection_id": f"S{state_index}-C{condition_index}",
                    "condition": condition,
                    "component_ids": components,
                    "viewpoint": viewpoint,
                    "capture_instruction": capture,
                    "evidence_type": evidence_type,
                    "visualization": visualization,
                    "verification_channel": channel,
                    "manual_provenance": dict(provenance),
                    "requires_same_frame": bool(
                        candidate.get("requires_same_frame", len(components) > 1)
                    ),
                }
            )
        if not normalized:
            raise ValueError(
                f"Step S{state_index} has no observable completion condition"
            )
        return normalized

    @staticmethod
    def _viewpoint_for_condition(condition: str) -> str:
        lowered = condition.lower()
        if any(marker in lowered for marker in ("后方", "背面", "rear", "back")):
            return "rear"
        if any(marker in lowered for marker in ("顶部", "上方", "进料口", "top")):
            return "top"
        if any(marker in lowered for marker in ("左侧", "左边", "left")):
            return "left"
        if any(marker in lowered for marker in ("右侧", "右边", "料卷", "right", "spool")):
            return "right"
        if any(marker in lowered for marker in ("底部", "底座", "下方", "bottom", "base")):
            return "bottom"
        if any(marker in lowered for marker in ("整机", "整体", "全貌", "overview")):
            return "overview"
        return "close_up"

    @staticmethod
    def _evidence_type_for_condition(condition: str) -> str:
        lowered = condition.lower()
        if any(marker in lowered for marker in ("连接", "插入", "接口", "connected", "inserted")):
            return "connection"
        if any(marker in lowered for marker in ("屏幕", "显示", "display", "code")):
            return "display"
        if any(marker in lowered for marker in ("水平", "竖直", "朝向", "orientation")):
            return "orientation"
        if any(marker in lowered for marker in ("位于", "左边", "右边", "上方", "下方", "position")):
            return "position"
        if any(marker in lowered for marker in ("相邻", "接触", "之间", "relation")):
            return "relation"
        return "presence"

    @staticmethod
    def _visualization_for_condition(
        condition: str,
        components: list[str],
    ) -> str:
        lowered = condition.lower()
        if any(marker in lowered for marker in ("ptfe", "管路", "路径", "route", "tube")):
            return "polyline"
        if any(item.startswith("target:") for item in components):
            return "arrow"
        if any(marker in lowered for marker in ("屏幕", "显示", "接口", "display", "port")):
            return "box"
        return "mask"

    @staticmethod
    def _capture_instruction(
        condition: str,
        viewpoint: str,
        channel: str,
    ) -> str:
        if channel == "sensor":
            return f"读取设备屏幕或传感器数据以确认：{condition}"
        if channel == "manual":
            return f"请人工确认并记录：{condition}"
        viewpoint_zh = {
            "front": "移动到设备正面",
            "rear": "绕到设备后方",
            "left": "移动到设备左侧",
            "right": "移动到设备右侧",
            "top": "抬高手机，从上方向下拍摄",
            "bottom": "降低手机，从侧下方拍摄",
            "close_up": "靠近当前部件",
            "overview": "后退并让相关整体区域入镜",
        }[viewpoint]
        return f"{viewpoint_zh}，完整拍摄：{condition}"

    @staticmethod
    def _split_conditions(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        cleaned: list[str] = []
        for raw_item in value:
            for item in re.split(r"[；;]", str(raw_item)):
                item = re.sub(
                    r"^(?:完成条件|错误状态|前置条件)\s*[:：]?\s*",
                    "",
                    item.strip(),
                ).strip("。. ")
                if item and item not in cleaned:
                    cleaned.append(item)
        return cleaned

    @staticmethod
    def _condition_information_score(values: list[str]) -> int:
        return sum(len(value.strip()) for value in values) + len(values) * 4

    @staticmethod
    def _constraints_need_repair(payload: dict[str, Any]) -> bool:
        states = payload.get("states")
        if not isinstance(states, list) or not states:
            return False
        initial = states[0]
        postconditions = initial.get("postconditions")
        if not isinstance(postconditions, list) or not postconditions:
            return True
        observable_markers = (
            "打开",
            "关闭",
            "合上",
            "左",
            "右",
            "上",
            "下",
            "水平",
            "竖直",
            "接触",
            "亮",
            "灭",
            "锁",
            "插入",
            "移除",
            "显示",
            "open",
            "closed",
            "left",
            "right",
            "above",
            "below",
            "horizontal",
            "vertical",
            "touching",
            "inserted",
            "removed",
            "visible",
        )
        joined = " ".join(str(value).lower() for value in postconditions)
        if not any(marker in joined for marker in observable_markers):
            return True
        provenance = initial.get("manual_provenance")
        return not isinstance(provenance, dict) or not ManualService._supporting_excerpt_ok(
            provenance.get("source_text"),
            initial.get("instruction"),
        )

    @staticmethod
    def _supporting_excerpt_ok(value: Any, instruction: Any) -> bool:
        text = str(value or "").strip()
        title = str(instruction or "").strip()
        if len(text) < 14 or text == title:
            return False
        return not ManualService._contains_guidance_meta(text)

    @staticmethod
    def _manual_excerpt_for_state(
        extracted_text: str,
        state: dict[str, Any],
    ) -> str:
        text = str(extracted_text or "")
        instruction = str(state.get("instruction", "")).strip()
        candidates = [instruction, instruction.rstrip("。. ")]
        start = -1
        for candidate in candidates:
            if candidate:
                start = text.find(candidate)
                if start >= 0:
                    break
        if start < 0 and state.get("state_type") == "initial_state":
            for marker in (
                "开始前状态",
                "初始状态",
                "Before starting",
                "Initial state",
            ):
                start = text.lower().find(marker.lower())
                if start >= 0:
                    break
        if start < 0:
            return ""

        end = min(len(text), start + 1600)
        tail = text[start + max(1, len(instruction)) : end]
        boundaries = [
            match.start()
            for pattern in (
                r"\n\[PAGE\s+\d+\]",
                r"\n步骤\s*\d+",
                r"\nStep\s*\d+",
            )
            for match in re.finditer(pattern, tail, re.I)
            if match.start() > 8
        ]
        if boundaries:
            end = start + max(1, len(instruction)) + min(boundaries)
        return text[start:end].strip()

    @staticmethod
    def _observable_clauses(excerpt: str) -> list[str]:
        observable_markers = (
            "打开",
            "关闭",
            "合上",
            "摊开",
            "放在",
            "位于",
            "左",
            "右",
            "上",
            "下",
            "中央",
            "水平",
            "竖直",
            "接触",
            "碰到",
            "完整入镜",
            "无遮挡",
            "亮",
            "灭",
            "锁",
            "插入",
            "移除",
            "显示",
            "open",
            "closed",
            "left",
            "right",
            "above",
            "below",
            "horizontal",
            "vertical",
            "touching",
            "inserted",
            "removed",
        )
        excluded = (
            "摄像头",
            "camera",
            "二维指引",
            "高亮",
            "箭头",
            "自动推进",
            "重新识别",
            "unity",
        )
        clauses: list[str] = []
        for raw in re.split(r"[\n；;。.!！]+", str(excerpt)):
            clause = raw.strip(" \t→-—")
            lowered = clause.lower()
            if not clause or any(marker in lowered for marker in excluded):
                continue
            if not any(marker in lowered for marker in observable_markers):
                continue
            if clause not in clauses:
                clauses.append(clause)
        return clauses[:8]

    @staticmethod
    def _contains_guidance_meta(text: str) -> bool:
        normalized = str(text).strip().lower()
        markers = (
            "parse manual",
            "procedure state graph",
            "auditable procedure",
            "说明书自动拆步骤",
            "当前进度判断",
            "来源框",
            "目标框",
            "方向箭头",
            "完成核验",
            "unity",
            "minicpm",
            "safe_to_advance",
            "recommended_step_id",
            "自动推进",
            "语音播报",
            "界面显示",
            "系统行为",
        )
        return any(marker in normalized for marker in markers)

    @staticmethod
    def _looks_like_meta_state(state: dict[str, Any]) -> bool:
        instruction = str(state.get("instruction", "")).strip().lower()
        section = str(
            (state.get("manual_provenance") or {}).get("section", "")
        ).strip().lower()
        combined = f"{instruction} {section}"
        exact_meta = {
            "当前进度定位",
            "next_on_success",
            "next on success",
            "任务完成",
            "task complete",
        }
        if instruction in exact_meta:
            return True
        meta_markers = (
            "mock",
            "unity",
            "minicpm",
            "safe_to_advance",
            "recommended_step_id",
            "自动推进",
            "语音播报",
            "置信度",
            "界面显示",
            "系统行为",
            "当前进度定位",
        )
        return any(marker in combined for marker in meta_markers)

    @staticmethod
    def _deduplicate_states(states: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Remove text/image double parses without merging real repeated work.

        Multimodal PDFs often expose the same step through their text layer and
        again through a rendered page. An exact normalized instruction on the
        same source page is therefore one state, not two. A second initial-state
        heading is also never an executable action. The source-page condition
        intentionally preserves legitimate repeated instructions on later pages.
        """
        unique: list[dict[str, Any]] = []
        seen: set[tuple[str, int]] = set()
        initial_seen = False
        initial_markers = (
            "初始状态",
            "开始前状态",
            "确认初始",
            "initial state",
            "before starting",
        )
        for state in states:
            instruction = str(state.get("instruction", "")).strip()
            normalized = re.sub(
                r"[\s。．.!！,，:：;；_-]+",
                "",
                instruction.lower(),
            )
            page_raw = (state.get("manual_provenance") or {}).get("page", 0)
            try:
                page = int(page_raw)
            except (TypeError, ValueError):
                page = 0
            key = (normalized, page)
            if key in seen:
                continue

            is_initial = any(marker in instruction.lower() for marker in initial_markers)
            if is_initial and initial_seen:
                continue
            if is_initial:
                initial_seen = True

            seen.add(key)
            unique.append(state)
        return unique

    def _normalize_procedure(
        self, procedure: ProcedureDocument
    ) -> ProcedureDocument:
        procedure.schema_version = "0.9"
        ordered = sorted(procedure.states, key=lambda state: state.step_index)
        for index, state in enumerate(ordered):
            state.step_index = index
            if index < len(ordered) - 1:
                state.next_on_success = ordered[index + 1].state_id
            else:
                state.next_on_success = None

        procedure.states = ordered
        procedure.task.initial_state = ordered[0].state_id
        procedure.task.terminal_states = [ordered[-1].state_id]
        return ProcedureDocument.model_validate(procedure.model_dump())

    def _mock_verification(
        self, request: VerificationRequest, state: Any
    ) -> VerificationResult:
        status = request.mock_status
        confidence = 0.95 if status != "uncertain" else 0.25
        evidence = {
            "completed": "模拟结果：预期完成条件成立。",
            "wrong_operation": "模拟结果：当前状态与说明书约束冲突。",
            "uncertain": "模拟结果：无法确认目标部件状态。",
            "in_progress": "模拟结果：操作已经开始，但尚未完成。",
            "not_started": "模拟结果：预期变化尚未开始。",
        }[status]
        boxes = []
        for component in state.target_components:
            if component.startswith("source:"):
                box = [100, 330, 360, 620]
            elif component.startswith("target:"):
                box = [560, 280, 900, 700]
            else:
                box = [260, 260, 740, 680]
            boxes.append(
                ComponentBox(
                    component_id=component,
                    bbox_0_1000=box,
                    observation=evidence,
                )
            )
        return VerificationResult(
            status=status,
            matched_step_id=request.current_step_id,
            evidence=evidence,
            component_boxes_0_1000=boxes,
            manual_page=state.manual_provenance.page,
            manual_section=state.manual_provenance.section,
            confidence=confidence,
            same_area_visible=(
                status == "completed"
                and request.comparison_mode == "before_after"
            ),
            expected_change_visible=(
                status == "completed"
                and request.comparison_mode == "before_after"
            ),
            safe_to_advance=False,
            next_action=(
                "进入下一步。"
                if status == "completed"
                else "停留在当前步骤，并按照恢复提示重新操作。"
            ),
        )

    @staticmethod
    def _verification_service_uncertain(
        *,
        request: VerificationRequest,
        state: Any,
        error: OllamaError,
    ) -> VerificationResult:
        """Keep a live run safe when the remote VLM exhausts its retries."""

        # Keep provider diagnostics in the server log only.  The phone needs
        # a stable corrective action, not raw JSON or vendor error details.
        print(
            "Manual2AR verification degraded after VLM retries: "
            f"{type(error).__name__}: {error}"
        )
        return VerificationResult(
            status="uncertain",
            matched_step_id=request.current_step_id,
            evidence="本次模型响应不完整，当前画面尚未形成可验证证据。",
            component_boxes_0_1000=[],
            manual_page=state.manual_provenance.page,
            manual_section=state.manual_provenance.section,
            confidence=0.0,
            safe_to_advance=False,
            next_action="保持当前步骤，稍后重试或按指定角度补拍。",
            same_area_visible=False,
            expected_change_visible=False,
            visualization_type="none",
            overlay_semantic="insufficient",
        )

    def _mock_state_localization(
        self,
        request: StateLocalizationRequest,
        procedure: ProcedureDocument,
    ) -> StateLocalizationResult:
        states = procedure.states
        requested_id = request.mock_recommended_step_id
        recommended_index = next(
            (
                index
                for index, state in enumerate(states)
                if state.state_id == requested_id
            ),
            min(2, len(states) - 1),
        )
        recommended = states[recommended_index]
        return StateLocalizationResult(
            observed_summary="Mock 演示：未读取摄像头，假设前置步骤已经完成。",
            completed_step_ids=[
                state.state_id for state in states[:recommended_index]
            ],
            recommended_step_id=recommended.state_id,
            evidence="模拟结果仅用于测试起点确认页面和跳转逻辑。",
            confidence=0.95,
            requires_human_confirmation=True,
            unavailable_checks=["Mock 模式没有分析任何真实画面。"],
            component_boxes_0_1000=[],
        )

    def _locate_state_with_ollama(
        self,
        request: StateLocalizationRequest,
        procedure: ProcedureDocument,
    ) -> StateLocalizationResult:
        try:
            image_bytes = base64.b64decode(
                request.image_base64,
                validate=True,
            )
            normalized_image = self._normalize_image(
                rotate_jpeg_for_vlm(
                    image_bytes,
                    request.image_rotation_degrees,
                ),
                MAX_LIVE_IMAGE_SIDE,
            )
        except (ValueError, OSError) as exc:
            raise ValueError("image_base64 is not a valid image") from exc

        compact_states = [
            {
                "state_id": state.state_id,
                "step_index": state.step_index,
                "state_type": state.state_type,
                "instruction": state.instruction,
                "preconditions": state.preconditions,
                "postconditions": state.postconditions,
                "target_components": state.target_components,
                "warnings": state.warnings,
            }
            for state in procedure.states
        ]
        device_profile = profile_for_procedure(procedure)
        reference_images = self._reference_images_for_profile(
            device_profile,
            [state.state_id for state in procedure.states],
        )
        device_context = (
            device_profile.grounding_context(
                [
                    component
                    for state in procedure.states
                    for component in state.target_components
                ]
            )
            if device_profile is not None
            else ""
        )
        output_language = self._guidance_language_for_procedure(procedure)
        ams_identity_context = ""
        if procedure.device.device_id == "bambu_a1_mini_ams_lite":
            ams_identity_context = (
                "This procedure targets the AMS Lite accessory itself. "
                "For device_identity, identify AMS Lite independently of the "
                "base printer. Its distinctive overview has a central white "
                "mast, four numbered feeder modules in fixed topology "
                "(1 upper-left, 2 lower-left, 3 lower-right, 4 upper-right), "
                "spool-holder arms, and routed PTFE tubes. If those features "
                "are visible, use device_identity=ams_lite and "
                "device_configuration=ams_lite even when the A1 mini printer "
                "is outside the crop. Do not answer a1_mini merely because "
                "AMS Lite is compatible with that printer. "
            )
        prompt = (
            "Act as a conservative manual-grounded task progress localizer. "
            + ams_identity_context
            +
            "IMAGE 1 is the only live camera image. Compare it with every "
            "ordered procedure state. Any later images are manual reference "
            "drawings for component identity only; never return a box measured "
            "from a reference drawing. "
            "Return only the longest CONTIGUOUS prefix of steps whose visible "
            "postconditions are clearly satisfied. recommended_step_id must be "
            "the first step after that prefix, or the final step if the whole "
            "task appears complete. Do not claim hidden, historical, software, "
            "sensor, power, temperature, or safety conditions from appearance. "
            "List those in unavailable_checks. Use conservative confidence and "
            "require human confirmation. Ground visible objects with optional "
            "normalized 0-1000 boxes. observed_summary must describe only the "
            "physical arrangement visible in the image. For the recommended "
            "step, return boxes for every visible target_component and preserve "
            "source:<name> and target:<name> component IDs exactly, so the client "
            "can render the next action. Never infer that an action happened "
            "merely because an object is present. Write observed_summary, "
            f"evidence, and unavailable_checks in {output_language}.\n\n"
            "Return only one JSON object matching the supplied JSON schema. "
            "Do not use Markdown.\n\n"
            f"DEVICE REFERENCE: {device_context}\n\n"
            f"ORDERED PROCEDURE: {json.dumps(compact_states, ensure_ascii=False)}"
        )
        raw = self.ollama.chat_structured(
            prompt=prompt,
            schema=StateLocalizationResult.model_json_schema(),
            images_base64=[normalized_image, *reference_images],
        )
        return StateLocalizationResult.model_validate(
            self._normalize_state_localization_payload(raw)
        )

    @staticmethod
    def _normalize_state_localization_payload(
        raw: dict[str, Any],
    ) -> dict[str, Any]:
        """Normalize a common VLM percentage mistake without trusting it.

        Some small structured-output vision models return ``85`` or ``85%``
        even though the schema asks for a 0-1 confidence.  Treat values in the
        1-100 range as percentages.  Anything non-finite or outside that range
        becomes zero-confidence and is surfaced for human review.
        """

        payload = dict(raw)
        original = payload.get("confidence", 0.0)
        text = str(original).strip()
        explicit_percent = text.endswith("%")
        if explicit_percent:
            text = text[:-1].strip()
        warning: str | None = None
        try:
            confidence = float(text)
        except (TypeError, ValueError):
            confidence = 0.0
            warning = "模型返回的置信度无法解析，已按0处理。"
        if not math.isfinite(confidence):
            confidence = 0.0
            warning = "模型返回的置信度不是有限数值，已按0处理。"
        elif explicit_percent or 1.0 < confidence <= 100.0:
            confidence /= 100.0
            warning = "模型使用百分制置信度，服务器已转换为0到1范围。"
        elif confidence < 0.0 or confidence > 100.0:
            confidence = 0.0
            warning = "模型返回的置信度超出有效范围，已按0处理。"
        payload["confidence"] = confidence
        if warning:
            unavailable = payload.get("unavailable_checks")
            if not isinstance(unavailable, list):
                unavailable = []
            payload["unavailable_checks"] = [*unavailable, warning]
            payload["requires_human_confirmation"] = True
        return payload

    def _validate_state_localization(
        self,
        result: StateLocalizationResult,
        procedure: ProcedureDocument,
    ) -> StateLocalizationResult:
        state_ids = [state.state_id for state in procedure.states]
        warnings = list(result.unavailable_checks)
        recommended = self._normalize_step_reference(
            result.recommended_step_id, state_ids
        )
        if recommended is None:
            recommended = state_ids[0]
            result.confidence = min(result.confidence, 0.20)
            warnings.append(
                "模型建议的步骤无法映射到流程，已保守回到第一步。"
            )

        normalized_completed = []
        for value in result.completed_step_ids:
            normalized = self._normalize_step_reference(value, state_ids)
            if normalized is not None and normalized not in normalized_completed:
                normalized_completed.append(normalized)

        recommended_index = state_ids.index(recommended)
        expected_prefix = state_ids[:recommended_index]
        if normalized_completed != expected_prefix:
            result.confidence = min(result.confidence, 0.55)
            warnings.append(
                "模型返回的已完成列表不连续；服务器已按建议起点重建连续前缀。"
            )

        result.recommended_step_id = recommended
        result.completed_step_ids = expected_prefix
        result.unavailable_checks = warnings
        result.requires_human_confirmation = True
        return StateLocalizationResult.model_validate(result.model_dump())

    @staticmethod
    def _allow_localization_grounding(
        result: StateLocalizationResult,
        state: Any,
    ) -> bool:
        facts = result.observed_summary.lower()
        if result.confidence < 0.60:
            return False
        if "device=not_a1_mini" in facts or "device=uncertain" in facts:
            return False
        # A mask over a complete machine or a complete path is not actionable
        # and easily becomes a huge, misleading rectangle. Component-level
        # steps remain eligible for focused grounding and SAM.
        component_names = [
            str(value).split(":", 1)[-1].lower()
            for value in state.target_components
        ]
        # State localization is an overview decision, not the component-level
        # guidance stage.  Multiple components or a long path cannot be
        # represented honestly by one or more filled rectangles, so defer
        # their visualization to the subsequent focused observation nodes.
        if len(component_names) != 1:
            return False
        if any(
            token in component_names[0]
            for token in ("整机", "完整", "路径", "whole", "path")
        ):
            return False
        return True

    @staticmethod
    def _allow_verification_grounding(
        result: VerificationResult,
        state: Any,
    ) -> bool:
        if result.status == "uncertain" or result.confidence < 0.55:
            return False
        component_names = [
            str(value).split(":", 1)[-1].lower()
            for value in state.target_components
        ]
        if component_names and all(
            any(token in name for token in ("整机", "完整", "路径", "whole", "path"))
            for name in component_names
        ):
            return False
        return True

    @staticmethod
    def _normalize_step_reference(
        value: str, state_ids: list[str]
    ) -> str | None:
        if value in state_ids:
            return value
        text = str(value).strip()
        match = re.search(r"(?:^|\b)S\s*[-_:]?\s*(\d+)(?:\b|$)", text, re.I)
        if match is None:
            match = re.search(r"(?:步骤|step)\s*[-_:]?\s*(\d+)", text, re.I)
        if match is None:
            return None
        candidate = f"S{int(match.group(1))}"
        return candidate if candidate in state_ids else None

    def _verify_with_ollama(
        self,
        request: VerificationRequest,
        procedure: ProcedureDocument,
    ) -> VerificationResult:
        device_profile = profile_for_procedure(procedure)
        if (
            device_profile is not None
            and device_profile.profile_id == "bambu_a1_mini"
        ):
            localized = self._locate_a1_mini_facts(
                StateLocalizationRequest(
                    procedure_id=request.procedure_id,
                    image_base64=request.image_base64,
                    image_rotation_degrees=request.image_rotation_degrees,
                    mode="ollama",
                ),
                procedure,
                device_profile,
            )
            if localized is not None:
                requested_state = next(
                    state
                    for state in procedure.states
                    if state.state_id == request.current_step_id
                )
                return self._verification_from_a1_mini_localization(
                    requested_state,
                    procedure,
                    localized,
                )

        searchable = json.dumps(procedure.model_dump(), ensure_ascii=False).lower()
        is_book_pen_demo = (
            ("书" in searchable or "book" in searchable)
            and ("笔" in searchable or "pen" in searchable)
            and len(procedure.states) >= 3
        )
        if is_book_pen_demo:
            localized = self._locate_book_pen_facts(
                StateLocalizationRequest(
                    procedure_id=request.procedure_id,
                    image_base64=request.image_base64,
                    image_rotation_degrees=request.image_rotation_degrees,
                    mode="ollama",
                ),
                procedure,
            )
            if localized is not None:
                requested_state = next(
                    state
                    for state in procedure.states
                    if state.state_id == request.current_step_id
                )
                return self._verification_from_book_pen_localization(
                    requested_state,
                    procedure,
                    localized,
                )

        try:
            image_bytes = base64.b64decode(
                request.image_base64,
                validate=True,
            )
            normalized_image = self._normalize_image(
                rotate_jpeg_for_vlm(
                    image_bytes,
                    request.image_rotation_degrees,
                ),
                MAX_LIVE_IMAGE_SIDE,
            )
        except (ValueError, OSError) as exc:
            raise ValueError("image_base64 is not a valid image") from exc

        current_index = next(
            index
            for index, state in enumerate(procedure.states)
            if state.state_id == request.current_step_id
        )
        state = procedure.states[current_index]
        context = {
            "requested": state.model_dump(),
            "previous_postconditions": (
                procedure.states[current_index - 1].postconditions
                if current_index > 0
                else []
            ),
            "next_instruction": (
                procedure.states[current_index + 1].instruction
                if current_index + 1 < len(procedure.states)
                else None
            ),
        }
        device_profile = profile_for_procedure(procedure)
        reference_images = self._reference_images_for_profile(
            device_profile,
            [state.state_id],
        )
        device_context = (
            device_profile.grounding_context(state.target_components)
            if device_profile is not None
            else ""
        )
        output_language = self._guidance_language_for_procedure(procedure)
        prompt = (
            "Act as a conservative manual-grounded equipment state verifier. "
            "IMAGE 1 is the only live camera image. Any later images are manual "
            "reference drawings for component identity only; never measure or "
            "report a box from a reference drawing. "
            "Evaluate ONLY the requested step against its explicit preconditions, "
            "postconditions, and wrong states. matched_step_id must exactly equal "
            "the requested state_id. Determine whether that requested step is not "
            "started, in progress, completed, wrong, or uncertain. Never infer a hidden "
            "success from hand motion. Use uncertain when evidence is occluded, "
            "blurred, outside frame, or unsupported. safe_to_advance is advisory; "
            "the server applies the final safety gate. Describe concrete visible "
            "evidence in evidence; do not output enum names or schema field names "
            "as evidence or next_action. State reasoning and coarse 2D grounding "
            "must be returned together in this single response. Write evidence, "
            f"manual_section, and next_action in {output_language}.\n\n"
            "For every clearly visible requested target_component, also return "
            "one tight top-left-origin bbox_0_1000 and preserve its component_id "
            "exactly. Omit boxes for occluded or uncertain objects.\n\n"
            "Return only one JSON object that exactly matches the supplied JSON "
            "schema. Do not use Markdown fences or explanatory prose.\n\n"
            f"REQUESTED STEP: {request.current_step_id}\n"
            f"HISTORY: {json.dumps(request.history)}\n"
            f"DEVICE REFERENCE: {device_context}\n"
            f"FOCUSED CONTEXT: {json.dumps(context, ensure_ascii=False)}"
        )
        raw = self.ollama.chat_structured(
            prompt=prompt,
            schema=VerificationResult.model_json_schema(),
            images_base64=[normalized_image, *reference_images],
            max_tokens=768,
        )
        return VerificationResult.model_validate(raw)

    @staticmethod
    def _guidance_language_for_procedure(
        procedure: ProcedureDocument,
    ) -> str:
        sample = " ".join(
            state.instruction for state in procedure.states[:3]
        )
        non_ascii_letters = sum(
            1 for character in sample if ord(character) > 127
        )
        return "Simplified Chinese (zh-CN)" if non_ascii_letters > 2 else "English"

    @staticmethod
    def _verification_from_a1_mini_localization(
        state: Any,
        procedure: ProcedureDocument,
        localized: StateLocalizationResult,
    ) -> VerificationResult:
        facts = localized.observed_summary.lower()
        uncertain_for_step = {
            "S0": "device=uncertain",
            "S1": "base=uncertain",
            "S2": "holder=uncertain",
            "S3": "ptfe=uncertain",
            "S4": "spool=uncertain",
            "S5": "filament=uncertain",
            "S6": "route=uncertain",
        }.get(state.state_id, "uncertain") in facts
        wrong_for_step = {
            "S0": "device=not_a1_mini" in facts,
            "S1": False,
            "S2": False,
            "S3": "ptfe=wrong_location" in facts,
            "S4": (
                "spool=wrong_location" in facts
                or "spool=unstable" in facts
            ),
            "S5": "filament=wrong_opening" in facts,
            "S6": (
                "route=bent_or_tangled" in facts
                or "route=incomplete" in facts
            ),
        }.get(state.state_id, False)

        if uncertain_for_step or localized.confidence < 0.5:
            status = "uncertain"
            confidence = min(localized.confidence, 0.45)
        elif wrong_for_step:
            status = "wrong_operation"
            confidence = max(0.72, localized.confidence)
        elif state.state_id in localized.completed_step_ids:
            status = "completed"
            confidence = localized.confidence
        elif state.state_id == "S6" and "route=clear" in facts:
            status = "completed"
            confidence = localized.confidence
        elif state.state_id == localized.recommended_step_id:
            status = "not_started"
            confidence = localized.confidence
        else:
            status = "wrong_operation"
            confidence = max(0.60, localized.confidence)

        return VerificationResult(
            status=status,
            matched_step_id=state.state_id,
            evidence=localized.evidence,
            component_boxes_0_1000=[],
            manual_page=state.manual_provenance.page,
            manual_section=state.manual_provenance.section,
            confidence=confidence,
            safe_to_advance=False,
            next_action=state.instruction,
        )

    @staticmethod
    def _verification_from_book_pen_localization(
        state: Any,
        procedure: ProcedureDocument,
        localized: StateLocalizationResult,
    ) -> VerificationResult:
        """Map observable book/pen facts to the requested manual state."""

        facts = localized.observed_summary.lower()
        is_uncertain = "uncertain" in facts or localized.confidence < 0.5
        terminal_visible = (
            "on_book_right_half" in facts and "笔方向=vertical" in facts
        )

        if is_uncertain:
            status = "uncertain"
            confidence = min(localized.confidence, 0.45)
        elif state.state_id in localized.completed_step_ids:
            status = "completed"
            confidence = localized.confidence
        elif (
            state.state_id == procedure.states[-1].state_id
            and terminal_visible
        ):
            status = "completed"
            confidence = localized.confidence
        elif state.state_id == localized.recommended_step_id:
            # A closed book with the pen already in an off-script location is a
            # recoverable placement error, not a return to the initial state.
            off_script_pen = (
                state.step_index == 2
                and "书=closed" in facts
                and "笔相对位置=left_of_book" not in facts
            )
            status = "wrong_operation" if off_script_pen else "in_progress"
            confidence = localized.confidence
        else:
            status = "wrong_operation"
            confidence = max(0.55, localized.confidence)

        return VerificationResult(
            status=status,
            matched_step_id=state.state_id,
            evidence=localized.evidence,
            component_boxes_0_1000=list(localized.component_boxes_0_1000),
            manual_page=state.manual_provenance.page,
            manual_section=state.manual_provenance.section,
            confidence=confidence,
            safe_to_advance=False,
            next_action=state.instruction,
        )

    def _ground_components(
        self,
        image_base64: str,
        target_components: list[str],
        rotation_degrees: int,
        allow_vlm_fallback: bool = True,
        procedure: ProcedureDocument | None = None,
        state_id: str | None = None,
    ) -> list[ComponentBox]:
        try:
            image_bytes = base64.b64decode(image_base64, validate=True)
        except ValueError:
            return []
        grounded = self.grounder.ground(
            image_bytes,
            target_components,
            rotation_degrees,
        )
        grounded_ids = {item.component_id for item in grounded}
        missing = [
            component
            for component in target_components
            if component not in grounded_ids
        ]
        if missing and allow_vlm_fallback:
            grounded.extend(
                self._focused_vlm_grounding(
                    image_bytes,
                    missing,
                    rotation_degrees,
                    procedure=procedure,
                    state_id=state_id,
                )
            )
        return grounded

    def _focused_vlm_grounding(
        self,
        image_bytes: bytes,
        components: list[str],
        rotation_degrees: int,
        procedure: ProcedureDocument | None = None,
        state_id: str | None = None,
    ) -> list[ComponentBox]:
        requested = list(
            dict.fromkeys(str(value).strip() for value in components)
        )
        requested = [value for value in requested if value]
        if not requested:
            return []

        schema = {
            "type": "object",
            "properties": {
                "objects": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "component_id": {
                                "type": "string",
                                "enum": requested,
                            },
                            "bbox_0_1000": {
                                "type": "array",
                                "items": {"type": "integer"},
                                "minItems": 4,
                                "maxItems": 4,
                            },
                            "evidence": {"type": "string"},
                        },
                        "required": [
                            "component_id",
                            "bbox_0_1000",
                            "evidence",
                        ],
                    },
                }
            },
            "required": ["objects"],
        }
        normalized_image = self._normalize_image(
            rotate_jpeg_for_vlm(image_bytes, rotation_degrees),
            MAX_LIVE_IMAGE_SIDE,
        )
        device_profile = (
            profile_for_procedure(procedure)
            if procedure is not None
            else None
        )
        reference_images = self._reference_images_for_profile(
            device_profile,
            [state_id] if state_id else None,
        )
        grounding_context = (
            device_profile.grounding_context(requested)
            if device_profile is not None
            else ""
        )
        try:
            raw = self.ollama.chat_structured(
                prompt=(
                    "This is a focused 2D grounding request, not task-state "
                    "reasoning. IMAGE 1 is the only live camera image. Any "
                    "later images are manual reference drawings for identity "
                    "only. Locate only these requested components in IMAGE 1: "
                    + ", ".join(requested)
                    + ". Preserve each component_id exactly. Return one tight "
                    "top-left-origin box per clearly visible component, normalized "
                    "to integers 0-1000. Do not return other objects, do not copy "
                    "coordinates from a reference image, and do not guess an "
                    "occluded component.\n\n"
                    + grounding_context
                ),
                schema=schema,
                images_base64=[normalized_image, *reference_images],
                max_tokens=1024,
            )
        except (OllamaError, ValueError):
            return []

        requested_lookup = {value.lower(): value for value in requested}
        results: list[ComponentBox] = []
        rotation = DemoGrounder._normalize_rotation(rotation_degrees)
        for item in raw.get("objects", []):
            if not isinstance(item, dict):
                continue
            raw_id = str(item.get("component_id", "")).strip()
            component_id = requested_lookup.get(raw_id.lower())
            if component_id is None:
                base = raw_id.split(":", 1)[-1].strip().lower()
                component_id = next(
                    (
                        value
                        for value in requested
                        if value.split(":", 1)[-1].strip().lower() == base
                    ),
                    None,
                )
            if component_id is None:
                continue
            values = item.get("bbox_0_1000")
            if not isinstance(values, list) or len(values) != 4:
                continue
            box = [max(0, min(1000, int(value))) for value in values]
            if box[0] >= box[2] or box[1] >= box[3]:
                continue
            upright_box = PixelBox(*box)
            raw_box = DemoGrounder._upright_box_to_raw_normalized(
                upright_box,
                1000,
                1000,
                rotation,
            )
            results.append(
                ComponentBox(
                    component_id=component_id,
                    bbox_0_1000=raw_box,
                    observation=(
                        str(item.get("evidence", "")).strip()
                        or "聚焦 VLM 粗定位；作为后续 SAM 提示框"
                    ),
                )
            )
        return self._merge_component_boxes(results, [])

    def _reference_images_for_profile(
        self,
        profile: DeviceProfile | None,
        state_ids: list[str] | None,
    ) -> list[str]:
        if profile is None:
            return []
        images: list[str] = []
        for path in profile.reference_paths(state_ids):
            cache_key = str(path.resolve())
            encoded = self._reference_image_cache.get(cache_key)
            if encoded is None:
                try:
                    encoded = self._normalize_image(path.read_bytes(), 1200)
                except OSError:
                    continue
                self._reference_image_cache[cache_key] = encoded
            images.append(encoded)
        return images[:3]

    @staticmethod
    def _merge_component_boxes(
        preferred: list[ComponentBox],
        fallback: list[ComponentBox],
    ) -> list[ComponentBox]:
        merged: list[ComponentBox] = []
        seen: set[str] = set()
        for item in [*preferred, *fallback]:
            if item.component_id in seen:
                continue
            seen.add(item.component_id)
            merged.append(item)
        return merged

    @staticmethod
    def _boxes_to_raw_coordinates(
        boxes: list[ComponentBox],
        rotation_degrees: int,
    ) -> list[ComponentBox]:
        rotation = DemoGrounder._normalize_rotation(rotation_degrees)
        if rotation == 0:
            return list(boxes)
        converted: list[ComponentBox] = []
        for item in boxes:
            x1, y1, x2, y2 = item.bbox_0_1000
            raw_box = DemoGrounder._upright_box_to_raw_normalized(
                PixelBox(x1, y1, x2, y2),
                1000,
                1000,
                rotation,
            )
            converted.append(
                ComponentBox(
                    component_id=item.component_id,
                    bbox_0_1000=raw_box,
                    observation=(
                        item.observation + "；" if item.observation else ""
                    )
                    + "已映射回相机原始坐标",
                )
            )
        return converted

    @staticmethod
    def _deterministic_next_action(
        status: str,
        state: Any,
        procedure: ProcedureDocument,
    ) -> str:
        if status == "completed" and state.next_on_success:
            next_state = next(
                (
                    item
                    for item in procedure.states
                    if item.state_id == state.next_on_success
                ),
                None,
            )
            if next_state is not None:
                return next_state.instruction
        if status == "wrong_operation":
            return "恢复到本步前置状态后，重新执行：" + state.instruction
        if status == "uncertain":
            return "保持目标部件完整入镜、移开双手后重新识别。"
        if status == "completed":
            return "当前任务已完成。"
        return state.instruction

    def _save_debug_capture(
        self,
        kind: str,
        image_base64: str,
        procedure: ProcedureDocument,
        model_result: dict[str, Any],
        request_context: dict[str, Any],
    ) -> None:
        """Persist local-only evidence so a wrong model decision is auditable."""
        if not self.save_debug_captures:
            return
        try:
            image_bytes = base64.b64decode(image_base64, validate=True)
            DEBUG_CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
            capture_id = (
                datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
                + "_"
                + kind
                + "_"
                + uuid.uuid4().hex[:8]
            )
            image_path = DEBUG_CAPTURE_DIR / f"{capture_id}.jpg"
            record_path = DEBUG_CAPTURE_DIR / f"{capture_id}.json"
            image_path.write_bytes(image_bytes)
            payload = {
                "capture_id": capture_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "kind": kind,
                "vision_provider": self.ollama.provider,
                "model": self.ollama.model,
                "request_context": request_context,
                "procedure": procedure.model_dump(),
                "model_result": model_result,
                "image_path": image_path.name,
                "storage": "local_only",
            }
            record_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except (ValueError, OSError):
            # Debug persistence must never change the guidance decision.
            return

    def _save_training_sample(
        self,
        request: VerificationRequest,
        result: VerificationResult,
    ) -> None:
        TRAINING_DATA_DIR.mkdir(parents=True, exist_ok=True)
        sample_id = uuid.uuid4().hex
        image_path = TRAINING_DATA_DIR / f"{sample_id}_after.jpg"
        record_path = TRAINING_DATA_DIR / f"{sample_id}.json"
        image_path.write_bytes(base64.b64decode(request.image_base64))
        before_path = None
        if request.before_image_base64:
            before_path = TRAINING_DATA_DIR / f"{sample_id}_before.jpg"
            before_path.write_bytes(
                base64.b64decode(request.before_image_base64)
            )
        payload = {
            "sample_id": sample_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "vision_provider": self.ollama.provider,
            "model": self.ollama.model,
            "request": request.model_dump(
                exclude={"image_base64", "before_image_base64"}
            ),
            "model_result": result.model_dump(),
            "after_image_path": image_path.name,
            "before_image_path": before_path.name if before_path else None,
            "human_label": None,
        }
        record_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
