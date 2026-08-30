# Manual2AR

Manual2AR converts equipment manuals into executable task graphs and uses live
camera observations to provide closed-loop visual guidance. The current
prototype targets the Bambu Lab A1 mini and AMS Lite.

## Components

- `backend/`: FastAPI service for manual parsing, task selection, visual
  grounding, state verification, safety gates, and tracking sessions.
- `unity/Manual2AR/`: Unity 2022.3.34f1 client with the workflow, component
  overview, Slot 4 guidance, filament loading, and build-plate inspection
  scenes.
- `sam2_mps_service/`: SAM 2.1 image segmentation service for Apple Silicon.
- `gpu_tracking_service/`: GroundingDINO and SAM 2.1 service for Linux/NVIDIA.
- `examples/`: audited task profiles, procedures, prompts, and capture
  protocols.
- `backend/tests/`: API, safety, tracking, evidence, and evaluation tests.

## Scope

Implemented:

- deterministic manual-to-task workflow for the reviewed A1 mini/AMS Lite
  profiles;
- Qwen visual grounding and state verification;
- SAM2/OpenCV mask initialization with LK/RANSAC propagation;
- image-space masks, arrows, labels, loss detection, and re-grounding;
- explicit safety gates and independent human-label support;
- English 16:9 Unity recording workflow.

Not validated:

- reliable parsing of arbitrary manuals;
- ARKit world anchoring on a physical iPhone;
- generalization beyond the reviewed devices and camera conditions;
- trained-model performance claims.

## Requirements

- macOS with Apple Silicon for the local SAM2 service, or Linux/NVIDIA for the
  GPU service;
- Python 3.11-3.13;
- Unity 2022.3.34f1;
- a Qwen-compatible API key and endpoint for live model inference.

## Setup

Clone the repository and its pinned model dependencies:

```bash
git clone --recurse-submodules https://github.com/NibiruCommander/Manual2AR.git
cd Manual2AR
```

Create the backend environment:

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
```

For the Apple-Silicon SAM2 service:

```bash
python3.12 -m venv sam2_mps_service/.venv
sam2_mps_service/.venv/bin/python -m pip install \
  -r sam2_mps_service/requirements.txt
mkdir -p third_party/sam2/checkpoints
curl -L \
  -o third_party/sam2/checkpoints/sam2.1_hiera_tiny.pt \
  https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_tiny.pt
```

Set the cloud-model configuration without writing credentials into the
repository:

```bash
export DASHSCOPE_API_KEY='<key>'
export DASHSCOPE_BASE_URL='<OpenAI-compatible-endpoint>'
export DASHSCOPE_MODEL='qwen3-vl-flash'
```

Start both local services:

```bash
./start_manual2ar_full.command
```

The backend listens on `http://127.0.0.1:8010`. The internal SAM2 service uses
`http://127.0.0.1:8020`; Unity connects only to port 8010.

Open `unity/Manual2AR` in Unity and load:

```text
Assets/Manual2AR/Scenes/Manual2ARWorkflow.unity
```

The official manuals are not redistributed in this repository. Follow the
source links and checksums in the corresponding `examples/*/manual/README.md`
files, then place local copies under
`unity/Manual2AR/Assets/StreamingAssets/Manual2AR/devices/bambu/` when needed.

## Tests

```bash
cd backend
.venv/bin/python -m pytest -q
```

Automated tests cover software behavior only. Camera, printer, and iPhone
validation must be recorded separately.

## Data and credentials

API keys, virtual environments, model checkpoints, Unity caches, raw runtime
captures, and generated outputs are excluded from Git. Reviewed task-profile
reference images required at runtime remain under `examples/`. Data collection
and evaluation-split rules are documented in `data/README.md`.

## Third-party software

Pinned upstream repositories and their roles are listed in
`third_party/README.md`. Each dependency retains its own license. No rights to
manufacturer manuals, trademarks, or device imagery are granted by this
repository.
