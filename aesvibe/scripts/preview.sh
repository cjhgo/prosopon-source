#!/usr/bin/env bash
# preview.sh — 本地预览 aesvibe（per-md 相对图，不走 OSS 扁平化）。
# 用法: scripts/preview.sh [端口]   默认 8099
set -euo pipefail

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENGINE="${PROSOPON_ENGINE:-$(cd "$SELF/../../prosopon-engine" && pwd)}"
PORT="${1:-8099}"
WSPORT=$((PORT + 20000))
[ "$WSPORT" -gt 60000 ] && WSPORT=$((PORT + 1))

if [ -d "$HOME/.nvm/versions/node" ]; then
  LATEST="$(ls -d "$HOME"/.nvm/versions/node/v* 2>/dev/null | sort -V | tail -1)"
  [ -n "$LATEST" ] && export PATH="$LATEST/bin:$PATH"
fi

[ -d "$ENGINE/quartz" ] || { echo "✗ 找不到 engine: $ENGINE/quartz（设 PROSOPON_ENGINE）"; exit 1; }
[ -f "$SELF/content/index.md" ] || { echo "✗ 缺 content/index.md"; exit 1; }

# 预览：不扁平化、不走 OSS；Quartz 默认资产管线按 per-md 相对路径复制。
unset ASSET_BASE_URL FLATTEN_ASSETS
export QUARTZ_SITE=aesvibe
export QUARTZ_CONFIG="$SELF/quartz.config.yaml"
export QUARTZ_CACHE_DIR="$SELF/.quartz-cache"

echo "▶ 预览: $SELF/content → http://localhost:$PORT  (Ctrl-C 退出)"
cd "$ENGINE/quartz"
exec npx quartz build -d "$SELF/content" -o "$SELF/public" --serve --port "$PORT" --wsPort "$WSPORT"
