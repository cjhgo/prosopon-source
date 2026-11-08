#!/usr/bin/env bash
# deploy.sh — 构建数字花园并上线到 VPS(经 aliyun-ops 的 vps deploy-dir)。
# 用法: scripts/deploy.sh [子域名]
#   默认子域名见 DOMAIN;可传参覆盖,或设环境变量 PROSOPON_DOMAIN。
# 流程: Quartz 构建 content → public/ → aliyun-ops vps deploy-dir 整目录上传 + nginx vhost(cert-aware)。
set -euo pipefail

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"              # prosopon-source
ENGINE="${PROSOPON_ENGINE:-$(cd "$SELF/../prosopon-engine" && pwd)}"
ALIYUN_OPS="${ALIYUN_OPS:-$(cd "$SELF/../oikos/prosopon/skills/aliyun-ops" && pwd 2>/dev/null || echo "")}"
CONTENT="$SELF/content"
PUBLIC="$ENGINE/quartz/public"
DOMAIN="${1:-${PROSOPON_DOMAIN:-quartz.junhangc.cn}}"

if [ -d "$HOME/.nvm/versions/node" ]; then
  LATEST="$(ls -d "$HOME"/.nvm/versions/node/v* 2>/dev/null | sort -V | tail -1)"
  [ -n "$LATEST" ] && export PATH="$LATEST/bin:$PATH"
fi

[ -d "$ENGINE/quartz" ] || { echo "✗ 找不到 engine: $ENGINE/quartz"; exit 1; }
[ -n "$ALIYUN_OPS" ] && [ -x "$ALIYUN_OPS/bin/vps" ] || { echo "✗ 找不到 aliyun-ops(设 ALIYUN_OPS)"; exit 1; }

echo "▶ [1/2] 构建 $CONTENT → public/"
cd "$ENGINE/quartz"
rm -rf public .quartz-cache
npx quartz build -d "$CONTENT"
N=$(find "$PUBLIC" -type f | wc -l | tr -d ' ')
echo "  ✓ 构建完成,$N 个文件"

echo "▶ [2/2] 部署 → https://$DOMAIN"
cd "$ALIYUN_OPS"
bin/vps deploy-dir "$PUBLIC" --domain "$DOMAIN"
echo "  ✓ 已部署: https://$DOMAIN/  (公网自验: curl -I https://$DOMAIN/)"
