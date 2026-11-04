#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ "${1:-}" == setup ]]; then
  python3.12 -m venv .venv
  .venv/bin/python -m pip install -r apps/backend/requirements.lock
  .venv/bin/python -m pip install --no-deps -e packages/contracts -e packages/perception -e apps/backend -e apps/inference
  .venv/bin/python -m playwright install chromium
  if [[ ! -f configs/app.local.json ]]; then
    cp configs/app.example.json configs/app.local.json
    chmod 600 configs/app.local.json
  fi
  exit 0
fi
if [[ ! -x .venv/bin/python ]]; then
  printf '%s\n' '先运行 bash run.sh setup；只在 configs/app.local.json 中编辑参数。'
  exit 1
fi
case "${1:-}" in
  start|sync|package) exec .venv/bin/python -B -m manual2ar.application.manage "$1" ;;
  resources) exec .venv/bin/python -B -m tools.resources.validate ;;
  inference-bundle) exec .venv/bin/python -B -m tools.build.inference_bundle ;;
  colab-*) exec .venv/bin/python -B -m tools.deployment.colab "${1#colab-}" ;;
  test) exec .venv/bin/python -B -m manual2ar.application.testing ;;
  gpu-notebook) exec .venv/bin/python -B -m tools.build.gpu_notebook ;;
  diagnostics-notebook) exec .venv/bin/python -B -m tools.build.colab_diagnostics ;;
  *) printf '%s\n' '命令：setup / start / sync / package / test / resources / gpu-notebook / diagnostics-notebook / inference-bundle / colab-{setup,login,start,start-watch,watch,diagnose,test-runtime,release-diagnostic,status,logs,stop-service,release}。配置请编辑 configs/app.local.json。' ;;
esac
