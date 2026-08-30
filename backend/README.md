# Manual2AR backend

FastAPI service for manual ingestion, reviewed task selection, visual
grounding, state verification, safety gating, and mask-tracking sessions.

## Setup

Use Python 3.11-3.13:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Configure the live visual provider through environment variables:

```bash
export MANUAL2AR_VISION_PROVIDER='qwen'
export DASHSCOPE_API_KEY='<key>'
export DASHSCOPE_BASE_URL='<OpenAI-compatible-endpoint>'
export DASHSCOPE_MODEL='qwen3-vl-flash'
./start_backend.command
```

Credentials must remain outside the repository. The retained local comparison
provider uses Ollama:

```bash
MANUAL2AR_VISION_PROVIDER=ollama \
MANUAL2AR_OLLAMA_URL=http://127.0.0.1:11434 \
MANUAL2AR_OLLAMA_MODEL=minicpm-v4.6:q4_0 \
./start_backend.command
```

## API

- `POST /api/manuals`: ingest a PDF or ordered page images.
- `GET /api/manuals/{job_id}`: read parsing status and the procedure graph.
- `POST /api/manuals/{job_id}/tasks/select`: instantiate a reviewed task.
- `POST /api/ams-lite/scan`: inspect the four-slot AMS Lite topology.
- `POST /api/guidance/locate`: suggest a start state for human confirmation.
- `POST /api/guidance/verify`: verify the requested state and safety gate.
- `POST /api/tracking/sessions`: initialize a tracking session.
- `POST /api/tracking/sessions/{id}/frames`: update a mask and loss state.
- `DELETE /api/tracking/sessions/{id}`: close a tracking session.
- `GET /health`: report providers, model identity, and availability.

The backend listens on port 8010. Unity must not connect directly to the SAM2
service on port 8020.

## Data policy

Camera images are not saved by default. `save_for_training=true` applies only
to requests made after explicit local consent. Model output is not a human
label. Image-free guidance and tracking events use a shared `run_id` and can be
joined with independent labels under `data/ground_truth/`.

## Tests

```bash
.venv/bin/python -m pytest -q
```

Automated tests establish software behavior. They do not establish physical
camera, printer, iPhone, or generalization performance.
