#!/usr/bin/env bash
# gencover.sh — 单篇书影音笔记：初始化专用 frontmatter → 选封面 → 补元数据 + 背景
#
# 用法：
#   bash scripts/gencover.sh content/mouseion/film/stand-by-me.md          # 可视化挑
#   bash scripts/gencover.sh content/mouseion/film/stand-by-me.md --auto   # 非交互，取排名第一
#
# 不依赖 genfront.sh；书影音有自己的 frontmatter 格式。
# 代理自动探测：FETCH_PROXY 优先；否则本机 127.0.0.1:7890 在听就走它；否则直连。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NOTE="${1:?用法: scripts/gencover.sh <note.md> [--auto] [--force]}"
shift || true

[ -f "$NOTE" ] || { echo "no such note: $NOTE" >&2; exit 1; }

AUTO=0
ARGS=()
for arg in "$@"; do
  case "$arg" in
    --auto) AUTO=1 ;;
    *) ARGS+=("$arg") ;;
  esac
done

if [ "$AUTO" -eq 1 ]; then
  if [ "${#ARGS[@]}" -gt 0 ]; then
    exec python3 "$SCRIPT_DIR/covers/note_cover.py" auto "$NOTE" "${ARGS[@]}"
  else
    exec python3 "$SCRIPT_DIR/covers/note_cover.py" auto "$NOTE"
  fi
else
  if [ "${#ARGS[@]}" -gt 0 ]; then
    exec python3 "$SCRIPT_DIR/covers/note_cover.py" serve "$NOTE" --enrich --exit-after-apply "${ARGS[@]}"
  else
    exec python3 "$SCRIPT_DIR/covers/note_cover.py" serve "$NOTE" --enrich --exit-after-apply
  fi
fi
