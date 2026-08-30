#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
cd "$PROJECT_DIR"

export MANUAL2AR_VISION_PROVIDER="qwen"
export DASHSCOPE_MODEL="${DASHSCOPE_MODEL:-qwen3-vl-flash}"

if [[ -z "${DASHSCOPE_BASE_URL:-}" ]]; then
  echo "DASHSCOPE_BASE_URL is required."
  exit 2
fi

while [[ -z "${DASHSCOPE_API_KEY:-}" ]]; do
  printf "请粘贴百炼 API Key（输入不会显示），然后按回车："
  IFS= read -r -s DASHSCOPE_API_KEY
  echo
  if [[ -z "$DASHSCOPE_API_KEY" ]]; then
    echo "没有读取到 API Key。请按 Command+V 粘贴后再按回车。"
  fi
done
export DASHSCOPE_API_KEY
echo "已安全读取 API Key（长度 ${#DASHSCOPE_API_KEY}，不会显示或保存）。"

PYTHONPATH="$SCRIPT_DIR" \
  "$SCRIPT_DIR/.venv/bin/python" \
  "$SCRIPT_DIR/scripts/evaluate_qwen_pair.py" \
  "$PROJECT_DIR/data/evaluation/pairs/A1_SANITY_001"
