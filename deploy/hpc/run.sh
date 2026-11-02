#!/usr/bin/env bash
# Run from the extracted inference bundle on an already allocated GPU node.
set -euo pipefail
bundle_dir="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$bundle_dir"
gpu_python="${MANUAL2AR_GPU_PYTHON:-$bundle_dir/.gpu-venv/bin/python}"
if [[ ! -x "$gpu_python" ]]; then
  printf '%s\n' 'Set MANUAL2AR_GPU_PYTHON to a prepared Python 3.12 interpreter, or prepare .gpu-venv.' >&2
  exit 1
fi
case "${1:-serve}" in
  prepare) exec "$gpu_python" -B -m deploy.common.bootstrap ;;
  serve) exec "$gpu_python" -B -m deploy.common.launch serve --config configs/inference.local.json --work-dir "$bundle_dir" ;;
  *) printf '%s\n' 'Usage: bash deploy/hpc/run.sh prepare|serve' >&2; exit 2 ;;
esac
