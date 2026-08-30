from __future__ import annotations

from pathlib import Path
from time import perf_counter

from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from .field_capture import save_field_capture
from .manual_service import ManualService
from .guidance_events import GuidanceEventLogger
from .models import (
    AmsOverviewScanRequest,
    AmsOverviewScanResult,
    BuildPlateInspectionRequest,
    BuildPlateInspectionResponse,
    BuildPlateObservation,
    EmptySpoolAxleCandidate,
    EmptySpoolAxleLocateRequest,
    EmptySpoolAxleLocateResponse,
    FilamentLoadingInspectionRequest,
    FilamentLoadingInspectionResponse,
    FilamentLoadingPredicateResult,
    FilamentRegionObservation,
    GuidanceTarget,
    HealthResponse,
    FieldCaptureResponse,
    InspectionPredicateResult,
    LocatedComponentResult,
    ManualJob,
    ManualJobAccepted,
    ManualTaskSelectionRequest,
    ManualTaskSelectionResult,
    MultiComponentId,
    MultiComponentLocateRequest,
    MultiComponentLocateResponse,
    SemanticComponentCandidate,
    StateLocalizationRequest,
    StateLocalizationResult,
    StateStartConfirmationRequest,
    StateStartConfirmationResponse,
    TrackedComponent,
    TrackingFrameRequest,
    TrackingSessionRequest,
    TrackingSessionResponse,
    VerificationRequest,
    VerificationResult,
)
from .ollama_client import OllamaError
from .plate_inspection import PlateInspectionEngine
from .filament_loading import FilamentLoadingEngine
from .tracking import decode_base64_image
from .tracking_provider import HybridMaskTracker, TrackingProviderError
from .tracking_events import TrackingEventLogger


app = FastAPI(
    title="Manual2AR Inference API",
    version="0.1.0",
    description="Manual ingestion and closed-loop visual state verification.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

service = ManualService()
tracker = HybridMaskTracker()
plate_inspection = PlateInspectionEngine(service.ollama, tracker)
filament_loading = FilamentLoadingEngine(service.ollama, tracker)
tracking_events = TrackingEventLogger(
    Path(__file__).resolve().parents[1] / "data" / "tracking_events"
)
guidance_events = GuidanceEventLogger(
    Path(__file__).resolve().parents[1] / "data" / "guidance_events",
    service.ollama.model,
    service.ollama.provider,
)

_COMPONENT_LABELS: dict[MultiComponentId, str] = {
    "filament_spool": "Filament Spool",
    "empty_spool_holder": "Empty Spool Holder",
    "build_plate": "Build Plate",
}
_COMPONENT_TRACKER_IDS: dict[MultiComponentId, str] = {
    "filament_spool": "paper_figure_filament_spool",
    "empty_spool_holder": "paper_figure_empty_spool_holder",
    "build_plate": "paper_figure_build_plate",
}
_COMPONENT_AREA_LIMITS: dict[MultiComponentId, tuple[float, float]] = {
    "filament_spool": (0.006, 0.20),
    "empty_spool_holder": (0.001, 0.075),
    "build_plate": (0.008, 0.30),
}
_COMPONENT_FORBIDDEN: dict[MultiComponentId, list[str]] = {
    "filament_spool": [
        "build_plate",
        "empty_spool_holder",
        "table",
        "ams_lite_feeder_module",
        "ptfe_tube",
    ],
    "empty_spool_holder": [
        "filament_spool",
        "build_plate",
        "ams_lite_feeder_module",
        "ams_lite_release_button",
        "ptfe_tube",
        "central_support_column",
    ],
    "build_plate": [
        "filament_spool",
        "empty_spool_holder",
        "table",
        "printer_base",
        "ptfe_tube",
    ],
}


def _component_guidance_target(candidate: SemanticComponentCandidate) -> GuidanceTarget:
    min_area, max_area = _COMPONENT_AREA_LIMITS[candidate.component_id]
    return GuidanceTarget(
        expected_component_id=_COMPONENT_TRACKER_IDS[candidate.component_id],
        semantic_role="target",
        # The overview figure labels one clearly visible empty holder; unlike
        # the dedicated Slot 4 operation scene, it must not silently attach a
        # slot identity that Qwen was not asked to establish.
        target_slot_id=None,
        render_mode="mask",
        forbidden_component_ids=_COMPONENT_FORBIDDEN[candidate.component_id],
        target_point_0_1000=candidate.target_point_0_1000,
        expected_area_ratio_min=min_area,
        expected_area_ratio_max=max_area,
    )


def _component_failure_result(
    component_id: MultiComponentId,
    error: str,
    candidate: SemanticComponentCandidate | None = None,
) -> LocatedComponentResult:
    return LocatedComponentResult(
        component_id=component_id,
        english_label=_COMPONENT_LABELS[component_id],
        found=False,
        candidate=candidate
        or SemanticComponentCandidate(
            component_id=component_id,
            found=False,
            confidence=0.0,
            visible_evidence="",
            failure_reason=error,
        ),
        session_id=None,
        tracked=None,
        tracking_ready=False,
        error=error,
    )


@app.get("/collector", response_class=HTMLResponse, include_in_schema=False)
def field_collector() -> HTMLResponse:
    page = Path(__file__).resolve().parent / "static" / "collector.html"
    return HTMLResponse(page.read_text(encoding="utf-8"))


@app.get("/live-empty-spindle", response_class=HTMLResponse, include_in_schema=False)
def live_empty_spindle() -> HTMLResponse:
    """Desktop webcam entry point for the narrow empty-spool-holder demo.

    This deliberately stays outside task recommendation and state verification.
    Each sampled webcam frame is automatically grounded with Qwen and segmented
    with SAM2.  Invalid current-frame masks are cleared instead of holding an
    old overlay, so a screenshot cannot confuse stale evidence with live
    grounding.
    """
    page = Path(__file__).resolve().parent / "static" / "live_empty_spindle.html"
    return HTMLResponse(page.read_text(encoding="utf-8"))


@app.get("/live-component-grounding", response_class=HTMLResponse, include_in_schema=False)
def live_component_grounding() -> HTMLResponse:
    """Desktop webcam page for figure-quality component masks and labels."""
    page = Path(__file__).resolve().parent / "static" / "live_component_grounding.html"
    return HTMLResponse(page.read_text(encoding="utf-8"))


@app.post(
    "/api/components/locate",
    response_model=MultiComponentLocateResponse,
)
def locate_figure_components(
    request: MultiComponentLocateRequest,
) -> MultiComponentLocateResponse:
    """Qwen grounds three overview components; SAM2 tracks each separately.

    A partial result is intentional: one weak object must not erase two valid
    masks.  Every successful object receives its own immutable semantic box and
    tracking session so later frames cannot merge the three identities.
    """
    try:
        batch = service.locate_components(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OllamaError as exc:
        return MultiComponentLocateResponse(
            results=[
                _component_failure_result(component_id, str(exc))
                for component_id in request.component_ids
            ],
            provider=service.ollama.provider,
            model=service.ollama.model,
        )

    image_bytes = decode_base64_image(request.image_base64)
    results: list[LocatedComponentResult] = []
    by_id = {candidate.component_id: candidate for candidate in batch.components}
    for component_id in request.component_ids:
        candidate = by_id.get(component_id)
        if candidate is None or not candidate.found:
            results.append(
                _component_failure_result(
                    component_id,
                    (candidate.failure_reason or "Component is not clearly visible")
                    if candidate is not None
                    else "Qwen omitted the component",
                    candidate,
                )
            )
            continue
        if candidate.confidence < 0.60:
            results.append(
                _component_failure_result(
                    component_id,
                    "Qwen confidence is below the overview-overlay threshold",
                    candidate,
                )
            )
            continue

        try:
            session_id, tracked = tracker.start(
                image_bytes,
                _COMPONENT_TRACKER_IDS[component_id],
                candidate.bbox_0_1000 or [1, 1, 2, 2],
                _component_guidance_target(candidate),
            )
        except (ValueError, TrackingProviderError) as exc:
            results.append(_component_failure_result(component_id, str(exc), candidate))
            continue

        ready = (
            tracked.status == "tracking"
            and tracked.mask_quality_passed
            and not tracked.requires_redetection
            and tracked.quality >= 0.50
        )
        if not ready:
            tracker.close(session_id)
        results.append(
            LocatedComponentResult(
                component_id=component_id,
                english_label=_COMPONENT_LABELS[component_id],
                found=True,
                candidate=candidate,
                session_id=session_id if ready else None,
                tracked=tracked,
                tracking_ready=ready,
                error=None if ready else "; ".join(tracked.mask_quality_reasons)
                or "SAM2 mask did not pass the quality gate",
            )
        )

    return MultiComponentLocateResponse(
        results=results,
        provider=service.ollama.provider,
        model=service.ollama.model,
    )


@app.post(
    "/api/a1-mini/build-plate/inspect",
    response_model=BuildPlateInspectionResponse,
)
def inspect_a1_mini_build_plate(
    request: BuildPlateInspectionRequest,
) -> BuildPlateInspectionResponse:
    """Run the exemplar-guided Qwen -> compiled SAM2 pre-print check.

    The task profile fixes the image order, visual definitions, exclusions,
    coordinate contract, and deterministic safety predicates. Every visible
    anomaly receives its own SAM2/LK session. A transient model failure returns
    an explicit uncertain state so clients clear overlays instead of holding
    stale evidence.
    """
    try:
        return plate_inspection.inspect(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (OllamaError, TrackingProviderError) as exc:
        return BuildPlateInspectionResponse(
            profile_id=request.profile_id,
            profile_version="1.0.0",
            prompt_version="preprint-plate-qwen-v1.0.0",
            method_label=(
                "manual-compiled task-conditioned vision profile + "
                "constraint-guided segmentation prompt compilation"
            ),
            exemplar_guided=True,
            provider=service.ollama.provider,
            model=service.ollama.model,
            status="uncertain",
            safe_to_print=False,
            headline="INSPECTION UNCERTAIN · REFRAME BUILD PLATE",
            correction_instructions=[],
            predicates=[
                InspectionPredicateResult(
                    predicate_id=predicate_id,
                    passed=False,
                    confidence=0.0,
                    evidence=str(exc),
                )
                for predicate_id in (
                    "plate_present",
                    "plate_aligned",
                    "surface_clear",
                    "no_residue",
                )
            ],
            plate=BuildPlateObservation(
                present="uncertain",
                aligned="uncertain",
                fully_visible="uncertain",
                confidence=0.0,
                visible_evidence=str(exc),
            ),
            rejected_candidates=[],
            qwen_raw={"error": str(exc)},
            reference_hashes={},
        )


@app.post(
    "/api/ams-lite/filament-loading/inspect",
    response_model=FilamentLoadingInspectionResponse,
)
def inspect_ams_lite_filament_loading(
    request: FilamentLoadingInspectionRequest,
) -> FilamentLoadingInspectionResponse:
    """Classify and ground the guidance/verification states for Figures 3–4."""
    try:
        return filament_loading.inspect(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (OllamaError, TrackingProviderError) as exc:
        unknown = FilamentRegionObservation(
            visible="uncertain",
            confidence=0.0,
            visible_evidence=str(exc),
        )
        return FilamentLoadingInspectionResponse(
            profile_id=request.profile_id,
            profile_version="1.0.0",
            prompt_version="ams-lite-filament-loading-qwen-v1.0.0",
            method_label=(
                "manual-compiled task-conditioned vision profile + "
                "constraint-guided segmentation prompt compilation"
            ),
            exemplar_guided=True,
            provider=service.ollama.provider,
            model=service.ollama.model,
            status="uncertain",
            headline="LOADING STATE UNCERTAIN",
            primary_instruction="REFRAME FEEDER + FILAMENT PATH",
            secondary_instruction="KEEP INLET, TIP AND PTFE TUBE VISIBLE",
            predicates=[
                FilamentLoadingPredicateResult(
                    predicate_id=predicate_id,
                    passed=False,
                    confidence=0.0,
                    evidence=str(exc),
                )
                for predicate_id in (
                    "feeder_visible",
                    "inlet_visible",
                    "filament_entered_feeder",
                    "filament_visible_in_ptfe",
                )
            ],
            feeder_module=unknown,
            filament_inlet=unknown,
            loose_filament_tip=unknown,
            inserted_filament_at_inlet=unknown,
            filament_visible_in_ptfe=unknown,
            qwen_raw={"error": str(exc)},
        )


@app.post(
    "/api/evaluation/captures",
    response_model=FieldCaptureResponse,
    status_code=201,
)
async def create_field_capture(
    image: UploadFile = File(...),
    case_id: str = Form(...),
    phase: str = Form(...),
    operation: str = Form(...),
    viewpoint: str = Form(...),
    slot: int = Form(..., ge=1, le=4),
    expected_color: str = Form(...),
    actual_color: str = Form(...),
    winding_direction: str = Form(...),
    filament_state: str = Form(...),
    expected_status: str = Form(...),
    notes: str = Form(default="", max_length=500),
    figure_id: str = Form(default=""),
    run_id: str = Form(default=""),
    device_id: str = Form(default="ams_lite"),
    task_id: str = Form(default=""),
    model_version: str = Form(default=""),
    prompt_version: str = Form(default=""),
    manual_version: str = Form(default=""),
    compile_version: str = Form(default=""),
    paper_claim: str = Form(default="", max_length=500),
    paper_use_allowed: bool = Form(default=False),
    consent: bool = Form(...),
) -> FieldCaptureResponse:
    if not consent:
        raise HTTPException(status_code=400, detail="必须确认本地研究采集同意")
    payload = await image.read()
    labels = {
        "operation": operation,
        "viewpoint": viewpoint,
        "slot": slot,
        "direction_group": "counterclockwise" if slot in {1, 3} else "clockwise",
        "expected_color": expected_color,
        "actual_color": actual_color,
        "winding_direction": winding_direction,
        "filament_state": filament_state,
        "expected_status": expected_status,
        "notes": notes,
        "paper_evidence": {
            "figure_id": figure_id,
            "run_id": run_id,
            "device_id": device_id,
            "task_id": task_id,
            "model_version": model_version,
            "prompt_version": prompt_version,
            "manual_version": manual_version,
            "compile_version": compile_version,
            "claim": paper_claim,
            "paper_use_allowed": paper_use_allowed,
        },
    }
    try:
        saved = save_field_capture(
            case_id=case_id,
            phase=phase,
            image_bytes=payload,
            content_type=image.content_type or "",
            labels=labels,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FieldCaptureResponse.model_validate(saved)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    tracking = tracker.health()
    vision_ready, vision_configuration_error = (
        service.ollama.configuration_status()
    )
    return HealthResponse(
        status="ok",
        ollama_url=service.ollama.base_url,
        model=service.ollama.model,
        vision_provider=service.ollama.provider,
        vision_ready=vision_ready,
        vision_configuration_error=vision_configuration_error,
        tracking_mode=str(tracking["mode"]),
        tracking_provider=str(tracking["active_default"]),
        tracking_remote_available=bool(tracking["remote_available"]),
        tracking_remote_url=tracking["remote_url"],
        tracking_last_error=tracking["last_remote_error"],
    )


@app.post("/api/manuals", response_model=ManualJobAccepted, status_code=202)
async def create_manual_job(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    mode: str = Query(default="ollama", pattern="^(mock|ollama)$"),
    device_profile: str | None = Query(
        default=None,
        pattern="^(bambu_a1_mini|bambu_a1_mini_ams_lite)$",
    ),
    guidance_language: str = Query(default="zh", pattern="^(zh|en)$"),
) -> ManualJobAccepted:
    uploads: list[tuple[str, str, bytes]] = []
    for upload in files:
        payload = await upload.read()
        uploads.append(
            (
                upload.filename or "manual",
                upload.content_type or "application/octet-stream",
                payload,
            )
        )
    if not uploads:
        raise HTTPException(status_code=400, detail="No manual pages were uploaded")

    job = service.create_job()
    background_tasks.add_task(
        service.process_job,
        job.job_id,
        uploads,
        mode,
        device_profile,
        guidance_language,
    )
    return ManualJobAccepted(job_id=job.job_id, status="queued")


@app.get("/api/manuals/{job_id}", response_model=ManualJob)
def get_manual_job(job_id: str) -> ManualJob:
    job = service.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Manual job not found")
    return job


@app.post(
    "/api/manuals/{job_id}/tasks/select",
    response_model=ManualTaskSelectionResult,
)
def select_manual_task(
    job_id: str,
    request: ManualTaskSelectionRequest,
) -> ManualTaskSelectionResult:
    try:
        return service.select_ams_task(job_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(
    "/api/ams-lite/scan",
    response_model=AmsOverviewScanResult,
)
def scan_ams_lite_overview(
    request: AmsOverviewScanRequest,
) -> AmsOverviewScanResult:
    try:
        return service.scan_ams_overview(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OllamaError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/guidance/verify", response_model=VerificationResult)
def verify_guidance(request: VerificationRequest) -> VerificationResult:
    started_at = perf_counter()
    try:
        result = service.verify(request)
        guidance_events.verified(
            request,
            result,
            (perf_counter() - started_at) * 1000.0,
        )
        return result
    except ValueError as exc:
        guidance_events.failed(
            "verify_failed",
            request.run_id,
            request.procedure_id,
            request.mode,
            (perf_counter() - started_at) * 1000.0,
            type(exc).__name__,
            str(exc),
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TrackingProviderError as exc:
        guidance_events.failed(
            "verify_failed",
            request.run_id,
            request.procedure_id,
            request.mode,
            (perf_counter() - started_at) * 1000.0,
            type(exc).__name__,
            str(exc),
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except OllamaError as exc:
        guidance_events.failed(
            "verify_failed",
            request.run_id,
            request.procedure_id,
            request.mode,
            (perf_counter() - started_at) * 1000.0,
            type(exc).__name__,
            str(exc),
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/guidance/locate", response_model=StateLocalizationResult)
def locate_guidance_state(
    request: StateLocalizationRequest,
) -> StateLocalizationResult:
    started_at = perf_counter()
    try:
        result = service.locate_state(request)
        guidance_events.located(
            request,
            result,
            (perf_counter() - started_at) * 1000.0,
        )
        return result
    except ValueError as exc:
        guidance_events.failed(
            "locate_failed",
            request.run_id,
            request.procedure_id,
            request.mode,
            (perf_counter() - started_at) * 1000.0,
            type(exc).__name__,
            str(exc),
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TrackingProviderError as exc:
        guidance_events.failed(
            "locate_failed",
            request.run_id,
            request.procedure_id,
            request.mode,
            (perf_counter() - started_at) * 1000.0,
            type(exc).__name__,
            str(exc),
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except OllamaError as exc:
        guidance_events.failed(
            "locate_failed",
            request.run_id,
            request.procedure_id,
            request.mode,
            (perf_counter() - started_at) * 1000.0,
            type(exc).__name__,
            str(exc),
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post(
    "/api/guidance/start-confirmations",
    response_model=StateStartConfirmationResponse,
)
def confirm_guidance_start(
    request: StateStartConfirmationRequest,
) -> StateStartConfirmationResponse:
    job = service.jobs.get(request.procedure_id)
    if job is None or job.status != "completed" or job.procedure is None:
        raise HTTPException(status_code=400, detail="Unknown or incomplete procedure_id")
    if request.recommended_step_id not in {
        state.state_id for state in job.procedure.states
    }:
        raise HTTPException(status_code=400, detail="Unknown recommended_step_id")
    if request.procedure_compatible == "false":
        raise HTTPException(
            status_code=409,
            detail="The selected procedure is incompatible with the visible configuration",
        )
    if request.device_identity in {"not_a1_mini", "not_ams_lite"}:
        raise HTTPException(status_code=409, detail="Visible device identity mismatch")
    if request.human_override:
        if request.confidence < 0.50 or request.confidence >= 0.75:
            raise HTTPException(
                status_code=400,
                detail="Human override is only valid for confidence in [0.50, 0.75)",
            )
    elif request.confidence < 0.75:
        raise HTTPException(
            status_code=409,
            detail="Automatic start confirmation requires at least 75% confidence",
        )
    audit_id = guidance_events.start_confirmed(request)
    return StateStartConfirmationResponse(accepted=True, audit_id=audit_id)


@app.post(
    "/api/tracking/sessions",
    response_model=TrackingSessionResponse,
    status_code=201,
)
def create_tracking_session(
    request: TrackingSessionRequest,
) -> TrackingSessionResponse:
    try:
        session_id, tracked = tracker.start(
            decode_base64_image(request.image_base64),
            request.component_id,
            request.bbox_0_1000,
            request.guidance_target,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TrackingProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    tracking_events.started(session_id, request, tracked)
    return TrackingSessionResponse(session_id=session_id, tracked=tracked)


@app.post(
    "/api/ams-lite/empty-spool-axle/locate",
    response_model=EmptySpoolAxleLocateResponse,
)
def locate_empty_spool_axle(
    request: EmptySpoolAxleLocateRequest,
) -> EmptySpoolAxleLocateResponse:
    """Narrow, reproducible Qwen Flash -> SAM2 spindle-grounding endpoint.

    It intentionally bypasses task recommendation, state localisation, and
    closed-loop verification.  This is the only endpoint needed to acquire a
    clean empty-spool-spindle highlight image or tracking video.
    """
    try:
        if request.verified_seed_bbox_0_1000 is not None:
            if request.preferred_slot_id is None:
                raise ValueError("A verified photo seed requires preferred_slot_id")
            x1, y1, x2, y2 = request.verified_seed_bbox_0_1000
            candidate = EmptySpoolAxleCandidate(
                found=True,
                slot_id=request.preferred_slot_id,
                bbox_0_1000=request.verified_seed_bbox_0_1000,
                # Use the upper-middle solid surface rather than the fork's
                # opening, so that the prompt point belongs to the holder.
                target_point_0_1000=[(x1 + x2) // 2, y1 + (y2 - y1) // 3],
                confidence=0.99,
                visible_evidence=(
                    "Human-verified photo seed for the visible empty AMS Lite "
                    "spool holder; SAM2 refines only its visible surface."
                ),
                proposal_source="verified_photo_seed",
            )
        else:
            candidate = service.locate_empty_spool_axle(request)
        if not candidate.found:
            return EmptySpoolAxleLocateResponse(
                found=False,
                candidate=candidate,
                provider=service.ollama.provider,
                model=service.ollama.model,
                tracking_ready=False,
                error=candidate.failure_reason or "No clearly visible empty spool spindle",
            )
        # The live evidence page is deliberately narrow: the selected slot is
        # part of the task contract.  A plausible spindle from any other slot
        # is not a usable result and must never be rendered as the selected
        # target.
        if (
            request.preferred_slot_id is not None
            and candidate.slot_id != request.preferred_slot_id
        ):
            return EmptySpoolAxleLocateResponse(
                found=False,
                candidate=candidate,
                provider=service.ollama.provider,
                model=service.ollama.model,
                tracking_ready=False,
                error=(
                    f"Qwen localized Slot {candidate.slot_id}, not selected "
                    f"Slot {request.preferred_slot_id}; no overlay rendered."
                ),
            )
        if candidate.confidence < 0.72:
            return EmptySpoolAxleLocateResponse(
                found=False,
                candidate=candidate,
                provider=service.ollama.provider,
                model=service.ollama.model,
                tracking_ready=False,
                error=(
                    "Qwen confidence is below the live-overlay threshold; "
                    "move closer to the selected empty white holder."
                ),
            )

        target = GuidanceTarget(
            expected_component_id="ams_lite_empty_spool_spindle",
            semantic_role="target",
            target_slot_id=candidate.slot_id,
            render_mode="mask",
            forbidden_component_ids=[
                "mounted_spool",
                "ams_lite_feeder_module",
                "ams_lite_release_button",
                "ptfe_tube",
                "central_support_column",
            ],
            target_point_0_1000=candidate.target_point_0_1000,
            expected_area_ratio_min=0.001,
            # The empty white Slot 4 arm is a compact visible surface. A mask
            # larger than eight percent of the frame has merged into the AMS
            # support, loose spool, or table and must never be shown.
            expected_area_ratio_max=0.08,
        )
        session_id, tracked = tracker.start(
            decode_base64_image(request.image_base64),
            "ams_lite_empty_spool_spindle",
            candidate.bbox_0_1000 or [1, 1, 2, 2],
            target,
        )
        ready = (
            tracked.status == "tracking"
            and tracked.mask_quality_passed
            and tracked.quality >= 0.58
        )
        return EmptySpoolAxleLocateResponse(
            found=True,
            candidate=candidate,
            session_id=session_id,
            tracked=tracked,
            provider=(
                "verified_photo_seed+sam2"
                if candidate.proposal_source == "verified_photo_seed"
                else service.ollama.provider
            ),
            model=service.ollama.model,
            tracking_ready=ready,
            error=None if ready else "; ".join(tracked.mask_quality_reasons)
            or "SAM2 mask did not pass the quality gate",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (OllamaError, TrackingProviderError) as exc:
        # This narrow demo page is used for live figure capture.  A transient
        # Qwen/SAM2 failure must clear the current overlay and ask for a new
        # frame; it should not turn the page into a "service unavailable"
        # dead-end.  Keep HTTP 200 here so the frontend can continue sampling.
        return EmptySpoolAxleLocateResponse(
            found=False,
            candidate=EmptySpoolAxleCandidate(
                found=False,
                confidence=0.0,
                visible_evidence="",
                failure_reason=str(exc),
            ),
            provider=service.ollama.provider,
            model=service.ollama.model,
            tracking_ready=False,
            error=str(exc),
        )


@app.post(
    "/api/tracking/sessions/{session_id}/frames",
    response_model=TrackedComponent,
)
def update_tracking_session(
    session_id: str,
    request: TrackingFrameRequest,
) -> TrackedComponent:
    try:
        tracked = tracker.update(
            session_id,
            decode_base64_image(request.image_base64),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Tracking session not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TrackingProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    # The segmentation tracker cannot know whether the iPhone has established
    # a stable ARKit world anchor.  Merge the client's spatial telemetry into
    # the same immutable response that is written to the paper-evidence log.
    if request.world_anchor_status is not None:
        tracked.world_anchor_status = request.world_anchor_status
    if request.client_drift_ratio is not None:
        tracked.drift_ratio = request.client_drift_ratio
    if request.client_relocalization_count is not None:
        tracked.relocalization_count = request.client_relocalization_count
    tracking_events.updated(session_id, tracked)
    return tracked


@app.delete(
    "/api/tracking/sessions/{session_id}",
    status_code=204,
    response_class=Response,
)
def delete_tracking_session(session_id: str) -> Response:
    try:
        if not tracker.close(session_id):
            raise HTTPException(status_code=404, detail="Tracking session not found")
    except TrackingProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    tracking_events.closed(session_id)
    return Response(status_code=204)
