#!/bin/zsh
set -e

SCRIPT_DIR="${0:A:h}"
CONFIG_DIR="$HOME/.config/manual2ar"
CONFIG_FILE="$CONFIG_DIR/qwen.env"
BASE_URL="${DASHSCOPE_BASE_URL:-}"

echo "Manual2AR 千问配置"
echo "密钥只会保存到本机用户配置目录，不会写入项目或 Git。"
if [[ -z "${BASE_URL}" ]]; then
  echo "请先设置 DASHSCOPE_BASE_URL。"
  exit 2
fi
echo -n "请输入百炼 API Key（输入时不会显示）："
read -rs API_KEY
echo

if [[ -z "$API_KEY" ]]; then
  echo "未输入密钥，未做任何修改。"
  exit 1
fi

mkdir -p "$CONFIG_DIR"
umask 077
{
  printf 'export DASHSCOPE_API_KEY=%q\n' "$API_KEY"
  printf 'export DASHSCOPE_BASE_URL=%q\n' "$BASE_URL"
} > "$CONFIG_FILE"
chmod 600 "$CONFIG_FILE"
unset API_KEY

echo "配置已安全保存：$CONFIG_FILE"
echo "正在启动 Manual2AR 后端……"
exec "$SCRIPT_DIR/start_backend.command"
