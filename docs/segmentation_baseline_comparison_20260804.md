# Segmentation baseline comparison — 2026-08-04

## Purpose

Verify that Manual2AR can replace a detector rectangle with an actual object
mask before any project-specific model training, without changing Unity's
tracking API.

## Providers

- Development fallback: `opencv-grabcut-lk-baseline`.
- Preferred Mac baseline: official `sam2.1_hiera_tiny-mps+box-mask+lk` at the
  pinned upstream SAM2 commit `2b90b9f5ceec907a1c18123530e92e794ad901a4`.
- Both receive the same detector/VLM box and return the same mask-session
  contract. Later frames use LK/RANSAC so SAM is not called on every camera
  frame.

## Real saved iPhone-frame evidence

| Case | Result |
|---|---|
| S1 book action | OpenCV/GrabCut fell back to a filled prompt rectangle. SAM2 followed the visible book boundary and excluded surrounding desk/laptop regions. |
| S2 pen relocation | SAM2 produced an orange pen mask, a green destination mask, and enabled the source-to-target arrow. |
| S2 wrong operation | The existing state adapter returned `wrong_operation`; rendering retained the current step and still showed the recovery target. |
| Main API routing | Port 8010 reported `tracking_remote_available=true` and returned provider `sam2.1_hiera_tiny-mps+box-mask+lk`. |
| Warm first-mask latency | 0.662 seconds for the saved book frame through the public port-8010 session API. |
| Known camera motion, book | Four cumulative affine frames: mean IoU 0.9992, minimum IoU 0.9987, no lost frame. |
| Known camera motion, pen | Four cumulative affine frames: mean IoU 0.9855, minimum IoU 0.9764, mean centroid error 0.084 px, no lost frame. |
| Full pen grounding | Collinear color-region joining expanded the prompt from the old pen-cap box to the complete pen; SAM2 mask pixel count increased from 2,113 to 4,530. |
| Full occlusion/out of frame | Both real-frame attacks return `lost`, quality `0`, and `requires_redetection=true`; a small cyan distractor is rejected. |

Artifacts:

- `backend/output/replays/20260803T155607_book_step_sam2.png`
- `backend/output/replays/20260803T155623_wrong_operation_sam2.png`
- `backend/output/replays/20260803T155623_wrong_operation_regrounded_sam2.png`
- `backend/output/tracking_eval/20260803T155607_book_sam2_motion.png`
- `backend/output/tracking_eval/20260803T155623_pen_sam2_motion.png`
- Adjacent JSON files contain prompt boxes, mask boxes, centroids, mask pixel
  counts, fill ratios, provider, status, and arrow availability.

## What this proves and does not prove

This proves the untrained provider boundary, real SAM2 inference on Apple MPS,
pixel-mask rendering, source/target arrow construction, public-API routing, and
controlled known-motion propagation on saved physical imagery. It does not
prove unconstrained temporal stability during handheld use, physical-scene
mask IoU, ARKit world anchoring, or arbitrary printer-part grounding. Those
still require a labeled physical-phone sequence.
