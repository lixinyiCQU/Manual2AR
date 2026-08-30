#!/bin/zsh

set -euo pipefail

PROJECT_DIR="${0:A:h}"
SUPERVISOR_COMMAND="${PROJECT_DIR}/scripts/manual2ar_supervisor.command"
SUPERVISOR_PID_FILE="/tmp/manual2ar-supervisor.pid"
SUPERVISOR_LOG="/tmp/manual2ar-supervisor.log"
QWEN_KEYCHAIN_SERVICE="Manual2AR-DashScope"
QWEN_KEYCHAIN_ACCOUNT="${USER:-manual2ar-user}"

# Qwen is the live VLM baseline.  Defaults are safe to set before service
# checks; the credential itself is requested only when a fresh backend will
# actually be launched.
export MANUAL2AR_VISION_PROVIDER="${MANUAL2AR_VISION_PROVIDER:-qwen}"
export DASHSCOPE_MODEL="${DASHSCOPE_MODEL:-qwen3-vl-flash}"
export MANUAL2AR_QWEN_ENABLE_THINKING="${MANUAL2AR_QWEN_ENABLE_THINKING:-false}"

if [[ "${MANUAL2AR_VISION_PROVIDER}" == "qwen" ]]; then
  if [[ -z "${DASHSCOPE_BASE_URL:-}" ]]; then
    echo "DASHSCOPE_BASE_URL is required for the Qwen provider."
    exit 2
  fi
  if [[ -z "${DASHSCOPE_API_KEY:-}" ]]; then
    DASHSCOPE_API_KEY="$(
      security find-generic-password \
        -a "${QWEN_KEYCHAIN_ACCOUNT}" \
        -s "${QWEN_KEYCHAIN_SERVICE}" \
        -w 2>/dev/null || true
    )"
    if [[ -n "${DASHSCOPE_API_KEY}" ]]; then
      echo "已从 macOS 钥匙串读取千问凭据。"
    fi
  fi
  while [[ -z "${DASHSCOPE_API_KEY:-}" ]]; do
    printf "请粘贴百炼 API Key（输入不会显示，将安全保存到 macOS 钥匙串）："
    IFS= read -r -s DASHSCOPE_API_KEY
    echo
    if [[ -z "${DASHSCOPE_API_KEY}" ]]; then
      echo "没有读取到 API Key。请按 Command+V 粘贴后再按回车。"
    fi
  done
  export DASHSCOPE_API_KEY
  security add-generic-password \
    -U \
    -a "${QWEN_KEYCHAIN_ACCOUNT}" \
    -s "${QWEN_KEYCHAIN_SERVICE}" \
    -w "${DASHSCOPE_API_KEY}" >/dev/null
  echo "千问凭据已载入；密钥不会写入项目文件。"
fi

existing_pid=""
if [[ -r "${SUPERVISOR_PID_FILE}" ]]; then
  existing_pid="$(<"${SUPERVISOR_PID_FILE}")"
fi
if [[ "${existing_pid}" != <-> ]] || ! kill -0 "${existing_pid}" 2>/dev/null; then
  rm -f "${SUPERVISOR_PID_FILE}"
  nohup "${SUPERVISOR_COMMAND}" </dev/null >>"${SUPERVISOR_LOG}" 2>&1 &
  disown
  echo "已启动后台守护程序；现在可以关闭终端窗口。"
else
  echo "后台守护程序已经运行（PID ${existing_pid}）。"
fi

backend_ready=0
sam_ready=0
for attempt in {1..150}; do
  if curl --fail --silent --max-time 2 http://127.0.0.1:8020/health >/dev/null; then
    sam_ready=1
  fi
  if curl --fail --silent --max-time 2 http://127.0.0.1:8010/health >/dev/null; then
    backend_ready=1
  fi
  if [[ "${sam_ready}" == "1" && "${backend_ready}" == "1" ]]; then
    break
  fi
  sleep 1
done

if [[ "${sam_ready}" != "1" || "${backend_ready}" != "1" ]]; then
  echo "服务未能在 150 秒内全部就绪。诊断日志："
  tail -40 "${SUPERVISOR_LOG}" 2>/dev/null || true
  tail -25 /tmp/manual2ar-backend.log 2>/dev/null || true
  tail -25 /tmp/manual2ar-sam2-mps.log 2>/dev/null || true
  exit 2
fi

health="$(curl --fail --silent http://127.0.0.1:8010/health)"
echo "Manual2AR 已稳定运行："
echo "- 视觉模型：$(print -r -- "${health}" | jq -r '.model')"
echo "- 千问连接：$(print -r -- "${health}" | jq -r '.vision_ready')"
echo "- 分割服务：$(print -r -- "${health}" | jq -r '.tracking_provider')"
echo "- SAM 可用：$(print -r -- "${health}" | jq -r '.tracking_remote_available')"
echo "终端可以关闭；守护程序会在进程意外退出时自动恢复。"
