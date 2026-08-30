# Manual2AR SAM 2.1 MPS provider

This local microservice runs the official untrained SAM 2.1 Hiera Tiny image
predictor on Apple Silicon MPS (or CPU fallback). A detector/VLM box initializes
the exact first-frame mask; the existing LK/RANSAC path propagates it between
expensive model calls. It implements the same tracking-session API as the Linux
CUDA service and does not change Unity.

Start it first:

```bash
./start_sam2_mps.command
```

Then start the main backend with:

```bash
MANUAL2AR_TRACKING_PROVIDER=auto \
MANUAL2AR_SAM2_URL=http://127.0.0.1:8020 \
../backend/start_backend.command
```

`GET /health` on port 8010 must report a provider containing
`sam2.1_hiera_tiny-mps+box-mask+lk`. If the MPS service is offline, `auto`
honestly reports and uses the OpenCV fallback. Use `sam2` instead of `auto` for
strict experiments where fallback must fail.

