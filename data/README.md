# Manual2AR data rules

## Directory intent

- `raw/`: original videos, images, manuals, and device exports. Never edit the
  originals in place.
- `annotations/`: labels and derived masks/boxes.
- `splits/`: train, validation, test, and held-out-device manifests.

## Leakage rules

- Split by recording session and operator, not by individual video frame.
- Near-duplicate frames from one action sequence must remain in one split.
- A held-out-device result requires the whole device, its sessions, and its
  manually captured reference images to be absent from training.
- Record prompt templates, model version, adapter checkpoint, and manual version
  for every experiment.

## First collection table

For every state, collect:

- clear before and after views;
- at least one side or oblique view;
- an incomplete transition;
- a wrong-direction or wrong-component example;
- an occluded or ambiguous view that should produce `uncertain`.

Do not record safety-critical real-machine mistakes merely to balance a
dataset. Use the printed rig or controlled simulation for negative examples.

## Runtime capture boundary

- Camera images are opt-in. The phone UI must visibly show `数据：开启` before
  `backend/data/training_samples/` receives verification frames.
- A saved model prediction is not a ground-truth label. Every record starts
  with `human_label: null` and must be reviewed before entering a split.
- `backend/data/tracking_events/` is image-free telemetry and may be used to
  measure lost rate, re-detection count, provider changes, mask-box drift, and
  latency by session/step.
- Never mix `debug_captures`, unreviewed samples, or frames from the same action
  sequence across train/validation/test.
