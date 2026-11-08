#!/usr/bin/env bash
# preview.sh — 本地预览数字花园(Quartz serve + 热重载)。
# 用法: scripts/preview.sh [端口]
#   在 prosopon-source 里写内容,本脚本起 engine 的 Quartz 构建本仓 content,localhost 预览。
set -euo pipefail

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # prosopon-source
ENGINE="${PROSOPON_ENGINE:-$(cd "$SELF/../prosopon-engine" && pwd)}"
CONTENT="$SELF/content"
PORT="${1:-8080}"

# node 走 nvm(非 brew),让 npx/quartz 可用
if [ -d "$HOME/.nvm/versions/node" ]; then
  LATEST="$(ls -d "$HOME"/.nvm/versions/node/v* 2>/dev/null | sort -V | tail -1)"
  [ -n "$LATEST" ] && export PATH="$LATEST/bin:$PATH"
fi

[ -d "$ENGINE/quartz" ] || { echo "✗ 找不到 engine: $ENGINE/quartz(设 PROSOPON_ENGINE 或把两仓平级放)"; exit 1; }
[ -f "$CONTENT/index.md" ] || { echo "✗ 缺 content/index.md"; exit 1; }

echo "▶ 预览: $CONTENT → http://localhost:$PORT  (Ctrl-C 退出,改 md 自动重载)"
cd "$ENGINE/quartz"
exec npx quartz build -d "$CONTENT" --serve --port "$PORT"
