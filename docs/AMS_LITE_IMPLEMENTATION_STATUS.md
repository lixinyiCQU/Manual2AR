# AMS Lite closed-loop implementation status

## Implemented now

- `ManualTaskBundle 1.0` with fixed slot topology 1 left-upper, 2
  left-lower, 3 right-lower, and 4 right-upper.
- Parameterized `load_spool(slot_id)` and guarded
  `recover_visible_jam(slot_id)` task instances.
- Color-neutral structural predicates. Material becomes a hard constraint only
  when the user explicitly selects one.
- Phone task/slot selection, Qwen overview suggestion, and mandatory human
  confirmation.
- Per-predicate evidence plus a server-owned deterministic advance gate.
- Small-component mask quality checks and no broad rectangle fallback for
  feeder inlets, spool axes, or release buttons.
- UI overlay semantics: cyan next target, green verified, yellow insufficient,
  red error/forbidden.
- ARKit world target marker and reviewed PNG billboard interface. Runtime image
  generation is disabled.
- A future logistic-regression fusion trainer that refuses fewer than 100 real
  labelled transitions and never overrides hard safety gates.

## Deliberately gated

- `unload_spool` and `swap_spool` remain disabled until their official
  maintenance provenance is reviewed.
- Any jam that requires PTFE, hub, extruder, or hotend disassembly stops this
  task and requires a separate maintenance procedure.
- A missing-object spool billboard is not displayed until a transparent PNG is
  generated, reviewed, marked `approved`, and assigned a real `local_path` in
  the task bundle.
- SAM2.1 is selected only when a configured MPS/GPU provider is available;
  otherwise health and telemetry explicitly report the OpenCV baseline.
- Logistic regression is not trained until 100 real human-labelled transitions
  exist.

## Phone demonstration path

1. Start the Mac backend and confirm `/health` reports Qwen.
2. Rebuild the Unity iOS app after these script changes.
3. Choose the AMS Lite quick guide.
4. Choose **Load spool**, scan the four-slot overview, and manually confirm the
   slot suggested by the system.
5. Review the parameterized task, locate current progress, and record the
   before image.
6. Perform the action with both hands, then return the phone to the requested
   viewpoint and capture the after image.
7. Demonstrate one successful predicate and one deliberately incomplete view.
   The incomplete view must stay on the same step and ask for a closer/new
   angle.
8. On the final step, show the completion page containing the real device,
   task, slot, and passed predicate count.

## Physical acceptance still required

- Confirm slot suggestions for all four physical positions.
- Confirm the feeder-inlet mask quality gate rejects a large feeder-shell mask.
- Confirm the normal loading task never targets the yellow release button.
- Measure 10-second handheld drift on iPhone 15 Pro Max. The target is at most
  5% of the screen diagonal; otherwise tracking must pause and re-localize.
- Collect equal gray/orange structural cases and verify they receive the same
  pass/fail decision when material was not selected as a constraint.

