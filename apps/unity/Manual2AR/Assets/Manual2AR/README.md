# Manual2AR Unity client

Unity version: `2022.3.34f1`.

## Scenes

- `Manual2ARWorkflow.unity`: complete recording workflow.
- `Manual2ARDemoHub.unity`: launcher for the four live modules.
- `ComponentOverviewTracking.unity`: component grounding and labels.
- `EmptySpindleTracking.unity`: AMS Lite Slot 4 guidance.
- `FilamentLoadingGuidance.unity`: insertion guidance and verification.
- `PrePrintPlateInspection.unity`: build-plate inspection.

The Mac Editor uses `WebCamTexture` and image-space overlays. This is not ARKit
world anchoring. The selected camera source is retained across scene changes.

## Backend

Start the repository services before opening a live module:

```bash
./start_manual2ar_full.command
```

Unity connects to `http://127.0.0.1:8010`. Port 8020 is internal to the backend
and must not be configured in Unity.

Tracking loss clears masks, labels, and arrows before re-grounding. A stale
overlay must not be retained as a fallback.

## Scene regeneration

The `Manual2AR` Unity menu contains builders for the workflow, module hub, and
individual feature scenes. Regenerating a scene also updates Build Settings.

## Validation boundary

The prepared desktop workflow and scene navigation have been exercised in the
Unity Editor. Physical iPhone ARKit anchoring and generalization to arbitrary
equipment have not been validated.
