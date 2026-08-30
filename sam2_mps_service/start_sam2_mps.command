#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
VENV_PYTHON="${SCRIPT_DIR}/.venv/bin/python"
CHECKPOINT="${PROJECT_DIR}/third_party/sam2/checkpoints/sam2.1_hiera_tiny.pt"

if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "SAM 2.1 环境尚未安装。"
  exit 2
fi

if [[ ! -f "${CHECKPOINT}" ]]; then
  echo "缺少 SAM 2.1 Tiny checkpoint：${CHECKPOINT}"
  exit 3
fi

export PYTHONPATH="${PROJECT_DIR}/backend:${PROJECT_DIR}/third_party/sam2:${SCRIPT_DIR}"
export PYTORCH_ENABLE_MPS_FALLBACK=1
export MANUAL2AR_SAM2_DEVICE="${MANUAL2AR_SAM2_DEVICE:-auto}"

cd "${SCRIPT_DIR}"
exec "${VENV_PYTHON}" -m uvicorn sam2_mps_service.main:app \
  --host 127.0.0.1 \
  --port 8020

