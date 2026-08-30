# GroundingDINO + SAM 2 GPU service

This optional Linux/NVIDIA service implements the same tracking-session
contract already consumed by Unity. It uses:

- `IDEA-Research/grounding-dino-tiny` for open-vocabulary text-to-box grounding;
- `facebook/sam2.1-hiera-tiny` for the first-frame box-prompt pixel mask;
- the Manual2AR LK/RANSAC tracker for low-latency streaming propagation.

It does not contain the future trained Manual2AR state model. Both visual models
are untrained upstream checkpoints and can therefore be used as the frozen
pre-training baseline.

## Start on a Linux CUDA host

From the project root:

```bash
docker compose -f gpu_tracking_service/docker-compose.yml up --build
```

The first launch downloads model weights into the named Docker volume. Verify:

```bash
curl http://127.0.0.1:8020/health
```

Then start the normal Manual2AR backend with strict SAM2 routing:

```bash
MANUAL2AR_TRACKING_PROVIDER=sam2 \
MANUAL2AR_SAM2_URL=http://127.0.0.1:8020 \
./backend/start_backend.command
```

For automatic GPU-to-CPU fallback, use `MANUAL2AR_TRACKING_PROVIDER=auto`.
The `/health` response reports whether the remote service is actually active;
an existing session never silently changes provider.

## API

- `POST /api/ground`: image plus component strings to GroundingDINO boxes.
- `POST /api/tracking/sessions`: image, component id, and prompt box to a SAM2
  mask and temporal session.
- `POST /api/tracking/sessions/{id}/frames`: update the mask using LK/RANSAC.
- `DELETE /api/tracking/sessions/{id}`: release temporal state.

This service has not been executed on the M2 Mac because CUDA is an explicit
runtime requirement. Its container and contract can be built/tested only on a
Linux machine with a compatible NVIDIA driver.
