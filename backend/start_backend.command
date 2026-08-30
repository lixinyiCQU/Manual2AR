#!/bin/zsh
set -e

SCRIPT_DIR="${0:A:h}"
cd "$SCRIPT_DIR"

# Load the user's private cloud-model credentials when available. This file is
# deliberately outside the repository so the API key cannot be committed with
# the project. Run setup_qwen_key.command once to create it with mode 600.
MANUAL2AR_QWEN_CONFIG="$HOME/.config/manual2ar/qwen.env"
if [[ -r "$MANUAL2AR_QWEN_CONFIG" ]]; then
  source "$MANUAL2AR_QWEN_CONFIG"
fi

if [[ ! -x ".venv/bin/python" ]]; then
  echo "Backend environment is missing. Create it with Python 3.11-3.13 first."
  exit 1
fi

# Prefer the local official SAM 2.1 service when it is healthy. In `auto` mode
# the provider is still allowed to fall back honestly to OpenCV when port 8020
# is unavailable.
export MANUAL2AR_TRACKING_PROVIDER="${MANUAL2AR_TRACKING_PROVIDER:-auto}"
export MANUAL2AR_SAM2_URL="${MANUAL2AR_SAM2_URL:-http://127.0.0.1:8020}"
# Qwen is the current cloud baseline. Keep secrets outside the repository and
# export DASHSCOPE_API_KEY plus the workspace-specific DASHSCOPE_BASE_URL before
# launching. Set the provider to `ollama` only for the frozen local ablation.
export MANUAL2AR_VISION_PROVIDER="${MANUAL2AR_VISION_PROVIDER:-qwen}"
export DASHSCOPE_MODEL="${DASHSCOPE_MODEL:-qwen3-vl-flash}"
# Visual endpoints require a short, schema-conformant final JSON object.
# Thinking mode can consume the completion budget and leave message.content
# empty, so keep it off unless an explicit ablation enables it.
export MANUAL2AR_QWEN_ENABLE_THINKING="${MANUAL2AR_QWEN_ENABLE_THINKING:-false}"

exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8010
