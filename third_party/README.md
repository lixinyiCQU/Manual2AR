# Manual2AR external baselines

These repositories are shallow, sparse reference checkouts. Datasets, demo
videos, and generated outputs are intentionally not vendored. The one explicit
exception is the official SAM 2.1 Hiera Tiny checkpoint used by the executable
Apple-MPS baseline; it remains ignored by the upstream Git configuration.
Manual2AR code should call them through an adapter or service boundary instead
of copying their internals into the Unity app.

| Local path | Upstream revision | License | Manual2AR use |
| --- | --- | --- | --- |
| `grounded-sam-2` | `b7a9c29f196e` | Apache-2.0 plus bundled notices | Primary untrained visual baseline: text prompt -> box -> mask -> video mask propagation |
| `sam2` | `2b90b9f5ceec` | Apache-2.0/BSD notices | Official image/video predictor and segmentation fine-tuning reference |
| `arfoundation-samples` | `6ad7b8765de2`, upstream branch `5.1` | Unity Companion License | Unity 2022.3-compatible camera pose, raycast, anchor, CPU image, and depth examples |
| `checkmanual` | `50946f15daa5` | No license file in the checkout | Read-only research reference for manual resolution, part alignment, GroundingDINO/SAM service boundaries, and appliance planning; do not copy code without permission |
| `industreal` | `ad86a35d4b51` | Apache-2.0 | Procedure-step/error baseline; especially accumulated confidence and temporal decay |
| `qwen3-vl` | `96588727e44c` | Apache-2.0 | Candidate MLLM training framework for image/video state classification, structured output, and grounding LoRA |
| `cutie` | `ec5cdd4cf16f` | MIT | Lower-complexity video object segmentation/tracking alternative to SAM 2 |

The selected SAM2 code is consumed through
`sam2_mps_service/` and `gpu_tracking_service/gpu_service/main.py`, not copied
into Unity. Both services
uses the official `SAM2ImagePredictor` box-prompt entry point; the pinned
Grounded-SAM-2 repository also supplies the verified GroundingDINO processing
pattern used by the optional text-to-box endpoint.

## Deliberately not integrated

- `facebookresearch/co-tracker`: useful point tracking reference, but most of
  the repository is CC-BY-NC. It is not selected as the product baseline.
- `NVlabs/FoundationPose`: strong 6-DoF pose estimation/tracking when a CAD
  model or reference views are available, but the official implementation is
  CUDA/NVIDIA-oriented and its repository license needs separate review.
- Guided Reality, JARVIS, and Chain-of-Procedure: close research references,
  but no verified reusable implementation was found during this pass.

## Updating a reference

Record the new full commit hash, upstream branch, license change, and the exact
Manual2AR experiment that needs it before updating. Do not download additional
checkpoints without recording the model, hash, hardware purpose, and storage
impact.
