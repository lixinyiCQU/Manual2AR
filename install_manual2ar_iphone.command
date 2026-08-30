#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="${0:A:h}"
DEVICE_ID="${1:-${MANUAL2AR_DEVICE_ID:-}}"
EXPECTED_LOCAL_HOSTNAME="${MANUAL2AR_LOCAL_HOSTNAME:-$(scutil --get LocalHostName 2>/dev/null || true)}"
PROJECT_DIR="${MANUAL2AR_IOS_PROJECT_DIR:-${SCRIPT_DIR}/build/ios}"
DERIVED_DIR="/tmp/manual2ar-signed-derived"
APP_PATH="${DERIVED_DIR}/Build/Products/Debug-iphoneos/Manual2AR.app"
BUNDLE_ID="${MANUAL2AR_IOS_BUNDLE_ID:-}"
TEAM_ID="${MANUAL2AR_IOS_TEAM_ID:-}"

if [[ -z "${DEVICE_ID}" || -z "${BUNDLE_ID}" || -z "${TEAM_ID}" ]]; then
  echo "Set MANUAL2AR_DEVICE_ID, MANUAL2AR_IOS_BUNDLE_ID, and MANUAL2AR_IOS_TEAM_ID."
  exit 2
fi

echo "Manual2AR 真机安装检查"

CURRENT_MAC_IP="$(ipconfig getifaddr en0 2>/dev/null || true)"
if [[ -z "${CURRENT_MAC_IP}" ]]; then
  echo "失败：没有找到 Mac 的 Wi-Fi 地址。请先让 Mac 和 iPhone 连接同一 Wi-Fi。"
  exit 2
fi

CURRENT_LOCAL_HOSTNAME="$(scutil --get LocalHostName 2>/dev/null || true)"
if [[ "${CURRENT_LOCAL_HOSTNAME}" != "${EXPECTED_LOCAL_HOSTNAME}" ]]; then
  echo "停止：当前 Mac 本地主机名是 ${CURRENT_LOCAL_HOSTNAME:-未知}，但 App 配置的是 ${EXPECTED_LOCAL_HOSTNAME}.local。"
  echo "请先更新 Unity 的 iPhoneBaseUrl 并重新导出。"
  exit 3
fi

echo "Mac 局域网服务：http://${EXPECTED_LOCAL_HOSTNAME}.local:8010（当前 IP ${CURRENT_MAC_IP}）"

if ! curl --fail --silent --max-time 3 "http://${EXPECTED_LOCAL_HOSTNAME}.local:8010/health" >/dev/null; then
  echo "失败：Mac 上的 Manual2AR 后端没有运行。"
  echo "请先运行 ${SCRIPT_DIR}/start_manual2ar_full.command。"
  exit 4
fi

DEVICE_JSON="$(mktemp -t manual2ar-device).json"
trap 'rm -f "${DEVICE_JSON}"' EXIT

if ! xcrun devicectl list devices \
  --filter "hardwareProperties.udid == '${DEVICE_ID}'" \
  --json-output "${DEVICE_JSON}" >/dev/null 2>&1; then
  echo "失败：无法读取 Mac 的设备列表。"
  exit 5
fi

DEVICE_COUNT="$(plutil -extract result.devices raw "${DEVICE_JSON}" 2>/dev/null || echo 0)"
if [[ "${DEVICE_COUNT}" == "0" ]]; then
  echo "失败：这台 Mac 没有保存目标 iPhone。请先用数据线配对并信任。"
  exit 5
fi

TUNNEL_STATE="$(plutil -extract result.devices.0.connectionProperties.tunnelState raw "${DEVICE_JSON}" 2>/dev/null || echo unavailable)"
if [[ "${TUNNEL_STATE}" != "connected" ]]; then
  echo "失败：iPhone 仍然离线或未信任这台 Mac。"
  echo "请解锁 iPhone、用数据线连接、在手机上点‘信任’，并保持屏幕亮着后重试。"
  exit 5
fi

echo "1/3 构建并签名 iPhone App…"
xcodebuild \
  -project "${PROJECT_DIR}/Unity-iPhone.xcodeproj" \
  -scheme Unity-iPhone \
  -configuration Debug \
  -sdk iphoneos \
  -destination 'generic/platform=iOS' \
  -derivedDataPath "${DERIVED_DIR}" \
  DEVELOPMENT_TEAM="${TEAM_ID}" \
  CODE_SIGN_STYLE=Automatic \
  -allowProvisioningUpdates \
  build

if [[ ! -d "${APP_PATH}" ]]; then
  echo "失败：构建结束但没有找到 ${APP_PATH}。"
  exit 6
fi

echo "2/3 安装到 iPhone…"
xcrun devicectl device install app --device "${DEVICE_ID}" "${APP_PATH}" --timeout 60

echo "3/3 启动 Manual2AR…"
xcrun devicectl device process launch --device "${DEVICE_ID}" "${BUNDLE_ID}" --timeout 30

echo "完成：Manual2AR 已安装并启动。首次运行请允许相机和本地网络权限。"
