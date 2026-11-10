#!/usr/bin/env bash
# publish.sh — build aesvibe + OSS-friendly postbuild + 上传到香港 OSS。
# 目标: https://www.aesvibe.fun/  (bucket: aesvibe-fun, oss-cn-hongkong)
#
# 图片策略: 生产设 FLATTEN_ASSETS=1、ASSET_BASE_URL 留空 →
#   FlattenLocalAssets 写 public/assets/<hash>，HTML 引用 /assets/<hash>；
#   图片和 HTML 同桶，一次 sync-site 全上去。
set -euo pipefail

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENGINE="${PROSOPON_ENGINE:-$(cd "$SELF/../../prosopon-engine" && pwd)}"
AOPS="${ALIYUN_OPS:-$(cd "$SELF/../../oikos/prosopon/skills/aliyun-ops" && pwd)}"
BUCKET="${AESVIBE_BUCKET:-aesvibe-fun}"
REGION="${AESVIBE_REGION:-cn-hongkong}"
DOMAIN="${AESVIBE_DOMAIN:-www.aesvibe.fun}"
PUBLIC="$SELF/public"

if [ -d "$HOME/.nvm/versions/node" ]; then
  LATEST="$(ls -d "$HOME"/.nvm/versions/node/v* 2>/dev/null | sort -V | tail -1)"
  [ -n "$LATEST" ] && export PATH="$LATEST/bin:$PATH"
fi

[ -d "$ENGINE/quartz" ] || { echo "✗ 找不到 engine: $ENGINE/quartz（设 PROSOPON_ENGINE）"; exit 1; }
[ -x "$AOPS/bin/oss" ] || { echo "✗ 找不到 aliyun-ops: $AOPS（设 ALIYUN_OPS）"; exit 1; }
[ -f "$SELF/content/index.md" ] || { echo "✗ 缺 content/index.md"; exit 1; }

# 生产：扁平化 + 根相对 /assets；不要继承主站的 ASSET_BASE_URL。
unset ASSET_BASE_URL
export FLATTEN_ASSETS=1
export QUARTZ_SITE=aesvibe
export QUARTZ_CONFIG="$SELF/quartz.config.yaml"
export QUARTZ_CACHE_DIR="$SELF/.quartz-cache"

echo "▶ [1/3] build"
rm -rf "$PUBLIC"
cd "$ENGINE/quartz"
npx quartz build -d "$SELF/content" -o "$PUBLIC"

echo "▶ [2/3] postbuild（.html 链接 / noindex / robots）"
python3 "$SELF/scripts/postbuild.py" "$PUBLIC"

echo "▶ [3/3] OSS sync-site → oss://$BUCKET ($REGION)"
"$AOPS/bin/oss" sync-site "$PUBLIC" --bucket "$BUCKET" --region "$REGION"

echo "▶ verify"
curl -fsS -o /dev/null -w "  ✓ https://$DOMAIN/ (HTTP %{http_code})\n" "https://$DOMAIN/"
