# Manual2AR untrained baseline architecture v1

Date: 2026-08-03

## Goal

Before training a project-specific model, the system must already execute the
same closed loop and data contracts expected after training:

`manual state -> next target -> ground -> segment -> track -> verify -> advance/correct/abstain`

The trained model will replace state reasoning and improve grounding. It must
not require a new Unity page flow or a new tracking protocol.

## Runtime pipeline

1. **Manual parser and state compiler**
   - Input: PDF/pages plus user task.
   - Output: audited state graph, pre/postconditions, wrong states, target
     component queries, provenance, and transition rules.
   - Current baseline: local MLLM with schema validation and human review.

2. **Current-state localization**
   - Input: live image/short temporal window plus candidate state graph.
   - Output: visible scene facts, current state, uncertainty, and next state.
   - Baseline rule: read observable facts first; never ask the VLM to invent a
     step number from the whole manual.

3. **Open-vocabulary grounding**
   - Input: the next step's component query, such as `blue pen` or `printer
     access cover`.
   - Target provider: GroundingDINO through Grounded-SAM-2.
   - Development fallback: focused VLM box plus controlled color/contour cues.

4. **Pixel segmentation and temporal tracking**
   - Target provider: SAM 2 image predictor initialized by the grounding box,
     then SAM 2 video predictor propagates the mask across frames.
   - Development fallback: the new `/api/tracking` service returns a pixel
     overlay, contour polygon, centroid, box, quality, and lost/re-detect flag
     using OpenCV color/GrabCut pixel segmentation plus Lucas-Kanade mask
     propagation. The provider is explicitly reported as
     `opencv-grabcut-lk-baseline`; it is not labelled SAM.

5. **Spatial registration**
   - ARKit/AR Foundation provides camera intrinsics, device pose, raycasts, and
     depth when supported.
   - The mask centroid plus depth is back-projected into camera coordinates and
     transformed into Unity world coordinates.
   - Static equipment parts can use a world anchor. Moving parts must update
     their world pose from each tracked mask/depth observation; a fixed anchor
     would remain on the table after the pen moves.
   - Without valid depth, render a tracked 2D overlay and explicitly label it as
     screen-space guidance rather than pretending it is a 3D anchor.

6. **State verifier and safety gate**
   - The verifier evaluates only the current state's preconditions,
     postconditions, and wrong states.
   - Use multiple observations: accumulate consistent evidence and decay stale
     evidence, following the useful IndustReal baseline idea.
   - Advance only when the state is `completed`, confidence is calibrated, the
     required visual predicates are available, and `safe_to_advance=true`.
   - `wrong_operation` and `uncertain` never advance.

7. **Persistent multi-view observation nodes for large equipment (baseline 0.9)**
   - Manual parsing compiles each atomic action into persisted observation
     nodes such as `S3-V1` (toolhead top) and `S3-V2` (PTFE route). Unity
     consumes these nodes; it does not silently invent extra completion
     conditions at runtime.
   - Each node tells the user which component to frame and whether to move
     above, below, behind, or beside the equipment. The user then draws a
     manual ROI and requests exactly one VLM decision.
   - Passed nodes are retained in the current step context. Moving the phone,
     hand shake, temporary occlusion, or mask loss cannot erase them and cannot
     advance the procedure.
   - The final node carries the retained node ids; the server returns
     `safe_to_advance=true` only when every expected node has passed.
   - Live camera preview and SAM2 mask propagation may run continuously. The
     state VLM is deliberately single-shot in this baseline and is never called
     automatically after tracking loss.
   - Every node carries viewpoint, capture instruction, evidence type,
     visualization type, verification channel, same-frame constraint, and
     manual provenance. Invisible conditions are routed to a sensor or explicit
     human check instead of being guessed from an image.

## Service boundaries

### Existing

- `POST /api/manuals`
- `GET /api/manuals/{job_id}`
- `POST /api/guidance/locate`
- `POST /api/guidance/verify`
- `POST /api/guidance/start-confirmations`
  - records ordinary confirmations or audited human overrides;
  - an override is allowed only for 50--74% identity results after all required
    boundary observation nodes pass;
  - overrides are logged with `count_as_model_success=false`.

### Added temporal mask contract

- `POST /api/tracking/sessions`
  - first image, component id, detector box;
  - returns tracking id, exact overlay PNG, polygon, centroid, box, quality.
- `POST /api/tracking/sessions/{id}/frames`
  - subsequent image;
  - returns the propagated mask and `tracking|lost` state.
- `DELETE /api/tracking/sessions/{id}`

SAM 2 must implement this contract rather than leaking PyTorch objects into the
Unity client.

This is now implemented as a provider boundary:

- `MANUAL2AR_TRACKING_PROVIDER=opencv`: deterministic Mac baseline;
- `MANUAL2AR_TRACKING_PROVIDER=auto`: use the configured GPU service when
  healthy, otherwise expose the OpenCV provider in every result;
- `MANUAL2AR_TRACKING_PROVIDER=sam2`: strict experiment mode that fails with
  HTTP 503 instead of silently changing algorithms;
- `gpu_tracking_service/`: GroundingDINO text-to-box, SAM2.1 box-to-mask, then
  LK/RANSAC streaming propagation using the existing Unity contract.
- `sam2_mps_service/`: the same official SAM2.1 Tiny box-to-mask initialization
  runs locally on Apple MPS; this is now the preferred home-device provider,
  while the CUDA service remains the final faster experimental deployment.

## Model training decision

Use one trainable MLLM as the manual-scene-state aligner, not as the mask
tracker. The current candidate is Qwen3-VL 4B Instruct for a first GPU run,
subject to a frozen hardware budget and zero-shot evaluation. Its official
training framework supports images, videos, grounding-format boxes, and LoRA.

Train four output tasks from the same samples:

1. step retrieval/current-state localization;
2. state status and wrong-operation classification;
3. evidence grounding box/query;
4. forward manual step structuring with provenance.

SAM 2 fine-tuning is a separate optional experiment only if the untrained SAM 2
mask IoU fails on printer parts. Do not jointly train SAM 2 and the MLLM first.

## Evidence required before calling the baseline complete

- A recorded phone sequence for every correct state and every planned error.
- The next manipulated object is highlighted before each action.
- A source-to-target arrow appears for relocation actions.
- The same mask remains attached while the phone moves.
- Moving the object updates the mask/3D point rather than leaving it behind.
- Correct completion advances only after every required viewpoint is retained
  and the final node returns `safe_to_advance=true`.
- Wrong, skipped, occluded, and out-of-frame cases block advancement.
- Logs preserve frame/session ids, model/provider versions, state decisions,
  boxes/masks, confidence, and human correction.
- Offline metrics cover step Recall@1, state macro-F1, wrong-operation recall,
  mask IoU, tracking J&F or equivalent, unsafe advance rate, and risk coverage.

## Hardware reality

Grounded-SAM-2's official local path strongly prefers CUDA, and SAM 2 training
examples assume large NVIDIA GPUs. The M2 Mac remains suitable for Unity,
schema/state-machine work, data capture, CPU fallback tracking, and API tests.
The full untrained visual baseline should run as a separate Linux GPU service;
later LoRA training should use a dedicated GPU environment.

## Repeatable public-API acceptance

Run from `backend/` while the combined service is open:

```bash
.venv/bin/python scripts/run_pretraining_acceptance.py
```

The command uploads the real three-page proxy PDF through `/api/manuals`,
validates the compiled state graph, verifies a correct S1 and wrong S2 from
saved physical frames, checks both arrow endpoints, starts a public SAM2
session, performs a stable update, then sends a fully occluded frame and
requires `lost`, quality zero, and re-detection. The 2026-08-04 run passed; its
machine-readable result is stored at
`backend/output/acceptance/20260804_pretraining_acceptance.json`.

## Implemented verification snapshot (2026-08-03)

- The local API test suite passes 35 checks, including a generic foreground
  mask tighter than its prompt box and temporal pen tracking.
- Provider tests prove automatic CPU fallback is labelled honestly, strict
  SAM2 never falls back silently, and a remote session keeps one provider and
  its temporal state until close.
- The controlled book/pen adapter now asks MiniCPM only for observable facts,
  then maps those facts through the manual state graph instead of accepting a
  free-form step guess. On a real saved iPhone frame it correctly verified S1
  complete and safe to advance in 1.63 seconds; the former generic prompt had
  incorrectly called the same closed-book frame `in_progress`.
- On the same frame, S2 was correctly blocked as `wrong_operation` in 1.45
  seconds and returned both a source pen box and destination book-region box,
  enabling the pixel highlight and movement arrow.
- Unity now performs change-triggered automatic verification, has a hard
  stability watchdog, starts an independent mask-tracking session, and shows
  the actual provider in the guidance UI.
- A lost mask now triggers a non-advancing re-localization request, then starts
  a new segmentation/tracking session. Retries are rate-limited to three per
  step; failure preserves the current step and asks for manual reframing.
- Blue-pen grounding now joins separated collinear color regions before SAM2,
  so the prompt covers the whole pen rather than only its cap. A per-session
  color-consistency gate rejects small same-color distractors: full occlusion
  and out-of-frame real-image tests return `lost`, quality `0`, and
  `requires_redetection=true` instead of moving the overlay to a false target.
- Training images are explicit opt-in in the phone UI. Image-free JSONL
  telemetry records provider, step, quality, box, centroid, and re-detection
  flags for tracking evaluation.
- One per-launch `run_id` now joins state localization, step verification, and
  mask tracking without saving images or scene text. Every guidance decision
  has a `decision_id`; independent JSONL labels drive step Recall@1, state
  macro-F1, wrong-operation recall, unsafe-advance rate, and coverage.
- Manual compilation now rejects identical within-step state semantics,
  normalizes every manipulated component to `source:*`, and aligns adjacent
  postcondition/precondition boundaries using the richer observable predicate
  set. If an initial state contains only component nouns or lacks a supporting
  excerpt, a locked repair call may change constraints and provenance only;
  it cannot change state ids, instructions, or step order.
- VLM boxes are converted from the upright inference image back into the raw
  camera coordinate system before Unity rendering and SAM2 initialization.
  Deterministic local boxes override model boxes for supported demo objects,
  preventing portrait-camera rotation from separating the mask from its object.
- AR Foundation/ARKit 5.1.6 is configured for Unity 2022.3. The generated
  signed arm64 iPhone Xcode project builds successfully. Camera orientation,
  depth availability, and world-anchor persistence still require one physical
  iPhone run before being claimed as verified.

## Baseline 0.8 interaction update (2026-08-11)

- Manual ROI separates global localization failure from close-up state
  recognition failure and remains a recovery fallback for future automatic
  grounding.
- Large-step postconditions are checked as retained observation nodes; Unity
  reports node progress and a viewpoint-specific camera instruction.
- MiniCPM runs once per explicit check. SAM2 tracking remains continuous only
  after a trustworthy small-component box exists.
- Tracking loss clears the current mask and asks for a new ROI. It never calls
  MiniCPM automatically, rewinds retained nodes, or changes the manual state.
- Full-machine and complete-path boxes are not sent to SAM2; absence of a valid
  local box is reported explicitly rather than rendered as a large orange mask.

## Baseline 0.9 audit update (2026-08-11)

- Generic manual parsing now has three explicit stages: manual evidence
  extraction, atomic state compilation, and observation-node compilation.
- A validator rejects compound actions, repeated pre/post/error conditions,
  missing provenance, and visible checks without a corresponding observation
  node. Repair is limited to invalid fields and cannot silently reorder steps.
- Start localization confirms identity and configuration only. A suggested
  start boundary is audited one viewpoint at a time before guidance begins.
- Results at or above 75% may be confirmed normally. Results from 50--74%
  require a second explicit human override and an audit reason. Wrong-device,
  below-50%, or procedure-incompatible results remain blocked.
- The manual ROI is a transparent cyan outline with corner handles. It is never
  rendered as a filled mask. Model boxes and SAM2 masks use separate visual
  styles and only appear when their own confidence gates pass.
- AMS Lite may currently be identified as a configuration and localized for
  diagnostic tests, but the external-spool procedure cannot drive AMS Lite
  actions until a sourced and human-audited AMS procedure is added.
