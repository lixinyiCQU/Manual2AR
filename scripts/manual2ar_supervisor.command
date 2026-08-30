#!/bin/zsh

set -u

PROJECT_DIR="${0:A:h:h}"
BACKEND_COMMAND="${PROJECT_DIR}/backend/start_backend.command"
SAM2_COMMAND="${PROJECT_DIR}/sam2_mps_service/start_sam2_mps.command"
SUPERVISOR_PID_FILE="/tmp/manual2ar-supervisor.pid"
BACKEND_PID_FILE="/tmp/manual2ar-backend.pid"
SAM2_PID_FILE="/tmp/manual2ar-sam2.pid"
SUPERVISOR_LOG="/tmp/manual2ar-supervisor.log"
BACKEND_LOG="/tmp/manual2ar-backend.log"
SAM2_LOG="/tmp/manual2ar-sam2-mps.log"

export MANUAL2AR_VISION_PROVIDER="${MANUAL2AR_VISION_PROVIDER:-qwen}"
export DASHSCOPE_MODEL="${DASHSCOPE_MODEL:-qwen3-vl-flash}"
export MANUAL2AR_QWEN_ENABLE_THINKING="${MANUAL2AR_QWEN_ENABLE_THINKING:-false}"
export MANUAL2AR_TRACKING_PROVIDER="${MANUAL2AR_TRACKING_PROVIDER:-auto}"
export MANUAL2AR_SAM2_URL="${MANUAL2AR_SAM2_URL:-http://127.0.0.1:8020}"
export MANUAL2AR_RECOVERY_DEVICE_PROFILE="${MANUAL2AR_RECOVERY_DEVICE_PROFILE:-bambu_a1_mini_ams_lite}"

is_healthy() {
  curl --fail --silent --max-time 3 "$1" >/dev/null 2>&1
}

owned_pid() {
  local pid_file="$1"
  local pid=""
  [[ -r "${pid_file}" ]] && pid="$(<"${pid_file}")"
  if [[ "${pid}" == <-> ]] && kill -0 "${pid}" 2>/dev/null; then
    print -r -- "${pid}"
    return 0
  fi
  return 1
}

stop_owned_process() {
  local pid_file="$1"
  local pid=""
  pid="$(owned_pid "${pid_file}" 2>/dev/null || true)"
  if [[ -n "${pid}" ]]; then
    kill "${pid}" 2>/dev/null || true
    for _ in {1..20}; do
      kill -0 "${pid}" 2>/dev/null || break
      sleep 0.25
    done
  fi
  rm -f "${pid_file}"
}

start_sam2() {
  if is_healthy "http://127.0.0.1:8020/health"; then
    return 0
  fi
  stop_owned_process "${SAM2_PID_FILE}"
  print -r -- "$(date '+%F %T') starting SAM 2.1" >>"${SUPERVISOR_LOG}"
  "${SAM2_COMMAND}" >>"${SAM2_LOG}" 2>&1 &
  print -r -- "$!" >"${SAM2_PID_FILE}"
}

start_backend() {
  if is_healthy "http://127.0.0.1:8010/health"; then
    return 0
  fi
  stop_owned_process "${BACKEND_PID_FILE}"
  print -r -- "$(date '+%F %T') starting backend" >>"${SUPERVISOR_LOG}"
  "${BACKEND_COMMAND}" >>"${BACKEND_LOG}" 2>&1 &
  print -r -- "$!" >"${BACKEND_PID_FILE}"
}

cleanup() {
  rm -f "${SUPERVISOR_PID_FILE}"
}
trap cleanup EXIT INT TERM

print -r -- "$$" >"${SUPERVISOR_PID_FILE}"
print -r -- "$(date '+%F %T') supervisor started pid=$$" >>"${SUPERVISOR_LOG}"

while true; do
  start_sam2
  # Let SAM begin loading before the backend checks its remote dependency.
  if ! is_healthy "http://127.0.0.1:8020/health"; then
    sleep 2
  fi
  start_backend
  sleep 5
done
