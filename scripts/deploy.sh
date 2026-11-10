#!/usr/bin/env bash
# deploy.sh — 构建数字花园并上线。图片走 OSS(assets.junhangc.cn),HTML 走 ECS(nginx)。
# 用法: scripts/deploy.sh [子域名]
#   默认子域名 prosopon.junhangc.cn;可传参或设 PROSOPON_DOMAIN。
# 流程:
#   1. ASSET_BASE_URL=OSS 域名 → Quartz 构建 + mouseion.json feed
#   2. .quartz-cache/assets/ → OSS 桶(内容 hash 增量)
#   3. mouseion-site/build.py 生成独立全屏站 → vps deploy-dir mouseion.junhangc.cn
#   4. 删 public/assets/ → vps deploy-dir HTML 到主站
set -euo pipefail

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"              # prosopon-source
ENGINE="${PROSOPON_ENGINE:-$(cd "$SELF/../prosopon-engine" && pwd)}"
ALIYUN_OPS="${ALIYUN_OPS:-$(cd "$SELF/../oikos/prosopon/skills/aliyun-ops" && pwd 2>/dev/null || echo "")}"
CONTENT="$SELF/content"
PUBLIC="$ENGINE/quartz/public"
DOMAIN="${1:-${PROSOPON_DOMAIN:-prosopon.junhangc.cn}}"   # 正式站(试运行曾用 quartz.junhangc.cn)
ASSET_BASE="${ASSET_BASE_URL:-https://assets.junhangc.cn}"   # 图床域名(OSS 自定义域名)
MOUSEION_DOMAIN="${MOUSEION_DOMAIN:-mouseion.junhangc.cn}"
MOUSEION_SITE="$ENGINE/mouseion-site"
MOUSEION_DIST="$ENGINE/.quartz-cache/mouseion-dist"

if [ -d "$HOME/.nvm/versions/node" ]; then
  LATEST="$(ls -d "$HOME"/.nvm/versions/node/v* 2>/dev/null | sort -V | tail -1)"
  [ -n "$LATEST" ] && export PATH="$LATEST/bin:$PATH"
fi

[ -d "$ENGINE/quartz" ] || { echo "✗ 找不到 engine: $ENGINE/quartz"; exit 1; }
[ -n "$ALIYUN_OPS" ] && [ -x "$ALIYUN_OPS/bin/vps" ] || { echo "✗ 找不到 aliyun-ops(设 ALIYUN_OPS)"; exit 1; }

echo "▶ [1/4] 构建(图 URL → $ASSET_BASE)"
cd "$ENGINE/quartz"
# 保留 .quartz-cache:OG/字体/已扁平图资产缓存,避免每次全量重生成。
rm -rf public
ASSET_CACHE="$ENGINE/quartz/.quartz-cache/assets"
QUARTZ_PROD=1 ASSET_BASE_URL="$ASSET_BASE" npx quartz build -d "$CONTENT"
NIMG=$(find "$ASSET_CACHE" -type f 2>/dev/null | wc -l | tr -d ' ')
echo "  ✓ 构建完成(缓存 assets: ${NIMG}; OSS 增量同步)"

# /aestic/：所有被引用配图的洗牌墙（派生自 build 产出的 manifest + contentIndex）
AESTIC_SITE="$ENGINE/aestic-site"
if [ -f "$PUBLIC/static/assets-manifest.json" ] && [ -f "$AESTIC_SITE/build.py" ]; then
  ASSET_BASE_URL="$ASSET_BASE" python3 "$AESTIC_SITE/build.py" \
    "$PUBLIC/static/assets-manifest.json" "$PUBLIC/static/contentIndex.json" "$PUBLIC/aestic"
fi

echo "▶ [2/4] 图片 → OSS($ASSET_BASE)"
if [ -d "$ASSET_CACHE" ] && [ "$NIMG" -gt 0 ]; then
  "$ALIYUN_OPS/bin/oss" sync "$ASSET_CACHE" assets/
else
  echo "  (无图,跳过)"
fi

echo "▶ [3/4] MOUSEION → ECS(https://$MOUSEION_DOMAIN)"
if [ -f "$PUBLIC/static/mouseion.json" ] && [ -f "$MOUSEION_SITE/build.py" ]; then
  python3 "$MOUSEION_SITE/build.py" "$PUBLIC/static/mouseion.json" "$MOUSEION_DIST"
  "$ALIYUN_OPS/bin/vps" deploy-dir "$MOUSEION_DIST" --domain "$MOUSEION_DOMAIN"
  "$ALIYUN_OPS/bin/vps" use-cert --domain "$MOUSEION_DOMAIN" || echo "  (MOUSEION HTTPS 未切;检查泛域名证书)"
else
  echo "  (缺 mouseion feed/site,跳过)"
fi

echo "▶ [4/4] HTML → ECS(https://$DOMAIN)"
rm -rf "$PUBLIC/assets"   # 图已在 OSS,不进 ECS 包(包只剩 HTML,小)
cd "$ALIYUN_OPS"
bin/vps deploy-dir "$PUBLIC" --domain "$DOMAIN"
echo "  ✓ 上线: https://$DOMAIN/  (图走 $ASSET_BASE;公网自验 curl -I https://$DOMAIN/)"
