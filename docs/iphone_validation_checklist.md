# Manual2AR iPhone baseline validation

Date: 2026-08-04

This checklist separates a visually convincing demo from evidence that the
untrained closed-loop baseline actually works. Record one continuous screen
video and preserve the backend telemetry for each run.

## Before the run

- Mac and iPhone are on the same Wi-Fi.
- `http://127.0.0.1:8010/health` reports `status: ok` on the Mac.
- The iPhone grants camera and local-network permission.
- The guidance page shows the actual tracking provider, not `Mock`.
- Training-data capture remains **off** unless the scene contains no private
  information and the run is intentionally being saved.

## Minimal physical scene

Use one book and one blue pen. Keep the whole book and pen visible initially.

1. State A: book open, blue pen horizontal on the left.
2. Action 1: close the book.
3. Action 2: move the pen onto the book.
4. Error case: move the pen somewhere other than the book.
5. Recovery: return the pen, then perform the required action.

## Pass/fail evidence

| Test | Pass condition | Failure condition |
|---|---|---|
| Current-state localization | The suggested step matches visible book/pen facts, and the screen explains the next action in text. | A step number is guessed without matching visible facts. |
| Start confidence gate | `>=75%` allows ordinary confirmation; `50--74%` requires a second audited override; `<50%`, wrong device, or incompatible configuration remains blocked. | A green-looking disabled button gives no reason, or a low-confidence result enters guidance without an override record. |
| Multi-view start audit | The candidate boundary is confirmed one local observation at a time; every passed inspection remains listed while the phone moves. | One full-machine frame is treated as proof of hidden, rear, top, or close-up conditions. |
| Before-action guidance | The object to manipulate is highlighted before the user moves it. | The box/mask appears only after completion or points to the wrong object. |
| Segmentation | The visible mask follows the pen/book silhouette more closely than a coarse detector box. | Only a full rectangular area is tinted, or no overlay is shown. |
| Direction guidance | A move action shows source highlight, destination highlight, and an arrow from source to target. | The arrow is decorative, reversed, or detached from the objects. |
| Observation-node verification | One tap sends one close-up ROI; a passed node remains retained while the user moves to the next viewpoint. | The app repeatedly calls the VLM, loses a passed node after camera motion, or treats a full-machine view as proof of every condition. |
| ROI rendering | The manual ROI is a thin cyan outline with four corner handles and the camera remains visible inside it. | The ROI becomes an opaque cyan rectangle or is mistaken for a model/SAM mask. |
| Correct transition | Completion advances only after consistent evidence and `safe_to_advance=true`. | A transient frame or uncertain result advances the procedure. |
| Wrong operation | The current step is retained and a recovery instruction is shown. | The system advances or silently resets. |
| Occlusion/out of frame | Tracking reports lost, clears the stale mask, retains completed nodes, and asks for a new ROI without calling the VLM. | The old mask remains frozen, automatic re-recognition starts, a retained node disappears, or the step advances. |
| Camera motion | Slow phone motion keeps the mask attached; quality/provider diagnostics remain visible. | The mask drifts while still being reported as reliable. |
| Spatial mode | The diagnostic explicitly says ARKit/world anchor when depth/raycast succeeds, otherwise screen-space. | A 2D overlay is presented as verified 3D registration. |

## Evidence to retain

- One screen recording covering setup, correct actions, one wrong action,
  occlusion, and recovery.
- Screenshot of the state text, provider, tracking quality, and spatial mode.
- Corresponding image-free JSONL tracking events from
  `backend/data/tracking_events/`.
- Corresponding image-free localization and verification decisions from
  `backend/data/guidance_events/`; all events from one recording must share one
  `run_id` with its tracking sessions.
- For every manual override, retain the `start_confirmed` event, reason,
  confidence, passed inspection ids, and `count_as_model_success=false`.
- Model name, prompt/procedure version, iPhone model, iOS version, lighting,
  and approximate camera distance.

Do not call the baseline complete merely because the App launches. The baseline
is complete only when every row above has physical-device evidence.
