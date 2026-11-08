#!/usr/bin/env bash
# deploy.sh — 构建数字花园并上线。图片走 OSS(assets.junhangc.cn),HTML 走 ECS(nginx)。
# 用法: scripts/deploy.sh [子域名]
#   默认子域名 quartz.junhangc.cn;可传参或设 PROSOPON_DOMAIN。
# 流程:
#   1. ASSET_BASE_URL=OSS 域名 → Quartz 构建(HTML 里图 URL 指向 OSS)
#   2. ossutil sync public/assets/ → OSS 桶(增量,大文件走这)
#   3. 删 public/assets/(不进 ECS 包)→ vps deploy-dir 传 HTML(小、快)
set -euo pipefail

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"              # prosopon-source
ENGINE="${PROSOPON_ENGINE:-$(cd "$SELF/../prosopon-engine" && pwd)}"
ALIYUN_OPS="${ALIYUN_OPS:-$(cd "$SELF/../oikos/prosopon/skills/aliyun-ops" && pwd 2>/dev/null || echo "")}"
CONTENT="$SELF/content"
PUBLIC="$ENGINE/quartz/public"
DOMAIN="${1:-${PROSOPON_DOMAIN:-quartz.junhangc.cn}}"
ASSET_BASE="${ASSET_BASE_URL:-https://assets.junhangc.cn}"   # 图床域名(OSS 自定义域名)

if [ -d "$HOME/.nvm/versions/node" ]; then
  LATEST="$(ls -d "$HOME"/.nvm/versions/node/v* 2>/dev/null | sort -V | tail -1)"
  [ -n "$LATEST" ] && export PATH="$LATEST/bin:$PATH"
fi

[ -d "$ENGINE/quartz" ] || { echo "✗ 找不到 engine: $ENGINE/quartz"; exit 1; }
[ -n "$ALIYUN_OPS" ] && [ -x "$ALIYUN_OPS/bin/vps" ] || { echo "✗ 找不到 aliyun-ops(设 ALIYUN_OPS)"; exit 1; }

echo "▶ [1/3] 构建(图 URL → $ASSET_BASE)"
cd "$ENGINE/quartz"
rm -rf public .quartz-cache
ASSET_BASE_URL="$ASSET_BASE" npx quartz build -d "$CONTENT"
NIMG=$(find "$PUBLIC/assets" -type f 2>/dev/null | wc -l | tr -d ' ')
echo "  ✓ 构建完成($NIMG 张图待传 OSS)"

echo "▶ [2/3] 图片 → OSS($ASSET_BASE)"
if [ -d "$PUBLIC/assets" ] && [ "$NIMG" -gt 0 ]; then
  "$ALIYUN_OPS/bin/oss" sync "$PUBLIC/assets" assets/
else
  echo "  (无图,跳过)"
fi

echo "▶ [3/3] HTML → ECS(https://$DOMAIN)"
rm -rf "$PUBLIC/assets"   # 图已在 OSS,不进 ECS 包(包只剩 HTML,小)
cd "$ALIYUN_OPS"
bin/vps deploy-dir "$PUBLIC" --domain "$DOMAIN"
echo "  ✓ 上线: https://$DOMAIN/  (图走 $ASSET_BASE;公网自验 curl -I https://$DOMAIN/)"
