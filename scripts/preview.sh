#!/usr/bin/env bash
# preview.sh — 本地预览数字花园(Quartz serve + 热重载)。
# 用法: scripts/preview.sh [端口]
#   在 prosopon-source 里写内容,本脚本起 engine 的 Quartz 构建本仓 content,localhost 预览。
set -euo pipefail

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # prosopon-source
ENGINE="${PROSOPON_ENGINE:-$(cd "$SELF/../prosopon-engine" && pwd)}"
CONTENT="$SELF/content"
PORT="${1:-8080}"
WSPORT=$((PORT + 20000)) # 热重载 WebSocket 端口:每实例独立(避开默认 3001 及 9090 代理等常用段)
[ "$WSPORT" -gt 60000 ] && WSPORT=$((PORT + 1))

# node 走 nvm(非 brew),让 npx/quartz 可用
if [ -d "$HOME/.nvm/versions/node" ]; then
  LATEST="$(ls -d "$HOME"/.nvm/versions/node/v* 2>/dev/null | sort -V | tail -1)"
  [ -n "$LATEST" ] && export PATH="$LATEST/bin:$PATH"
fi

[ -d "$ENGINE/quartz" ] || { echo "✗ 找不到 engine: $ENGINE/quartz(设 PROSOPON_ENGINE 或把两仓平级放)"; exit 1; }
[ -f "$CONTENT/index.md" ] || { echo "✗ 缺 content/index.md"; exit 1; }

# 端口被占:只 kill 占用的 quartz 预览进程(不误伤别的服务);非 quartz 则让用户换端口。
# 同时清 HTTP 端口(PORT)和热重载 WS 端口(WSPORT)——serve 会同时占两个。
BUSY="$( { lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null; lsof -tiTCP:"$WSPORT" -sTCP:LISTEN 2>/dev/null; } | sort -u || true)"
if [ -n "$BUSY" ]; then
  QPIDS=""; FOREIGN=""
  for pid in $BUSY; do
    cmd="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    case "$cmd" in
      *quartz*|*"npx "*) QPIDS="$QPIDS $pid" ;;
      "") ;; # 已退出
      *) FOREIGN="$FOREIGN $pid" ;;
    esac
  done
  if [ -n "$QPIDS" ]; then
    echo "▶ 端口 $PORT/$WSPORT 上已有 Quartz 预览,先停掉(pid:$QPIDS)"
    kill $QPIDS 2>/dev/null || true
    sleep 1
    for pid in $QPIDS; do kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true; done
  fi
  if [ -n "$FOREIGN" ]; then
    echo "✗ 端口被其它进程占用(非 Quartz):"
    lsof -nP -iTCP:"$PORT" -iTCP:"$WSPORT" -sTCP:LISTEN 2>/dev/null | sed 's/^/    /'
    echo "  → 换个端口: scripts/preview.sh $((PORT + 1))"
    exit 1
  fi
fi

echo "▶ 预览: $CONTENT → http://localhost:$PORT  (Ctrl-C 退出,改 md 自动重载)"
cd "$ENGINE/quartz"
exec npx quartz build -d "$CONTENT" --serve --port "$PORT" --wsPort "$WSPORT"
