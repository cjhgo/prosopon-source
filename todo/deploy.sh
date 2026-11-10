#!/usr/bin/env bash
# deploy.sh — 部署 todo.junhangc.cn（常驻 node 服务 + nginx 反代 + 泛域名证书）。
#
# 与主站的区别：主站是静态产物 push 到 nginx root；这里是**有状态服务**——
# 代码/systemd 单元/环境变量一次性落地，状态数据放在 /var/lib/<service>，
# 重复部署只换代码，不碰数据。
#
# 用法:
#   todo/deploy.sh                 # 用已保存的密码
#   TODO_PASSWORD=xxx todo/deploy.sh
#   TODO_PORT=3021 todo/deploy.sh  # 换内部端口
set -euo pipefail

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ALIYUN_OPS="${ALIYUN_OPS:-$(cd "$SELF/../../oikos/prosopon/skills/aliyun-ops" && pwd)}"
DOMAIN="${TODO_DOMAIN:-todo.junhangc.cn}"
PORT="${TODO_PORT:-3020}"
NAME="${TODO_SERVICE:-todo-junhangc}"
DATA_DIR="${TODO_DATA_DIR:-/var/lib/$NAME}"
CONF_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/todo"
PASS_FILE="$CONF_DIR/password"

[ -x "$ALIYUN_OPS/bin/vps" ] || { echo "✗ 找不到 aliyun-ops: $ALIYUN_OPS"; exit 1; }

# ---------------------------------------------------------------- 密码
mkdir -p "$CONF_DIR" && chmod 700 "$CONF_DIR"
if [ -z "${TODO_PASSWORD:-}" ]; then
  if [ -f "$PASS_FILE" ]; then
    TODO_PASSWORD="$(cat "$PASS_FILE")"
  else
    # 先取固定字节再过滤，避免 tr 被 head 提前关闭触发 SIGPIPE（set -o pipefail 会因此中止）
    TODO_PASSWORD="$(head -c 64 /dev/urandom | LC_ALL=C tr -dc 'A-Za-z0-9' | cut -c1-18)"
    printf '%s' "$TODO_PASSWORD" > "$PASS_FILE"
    chmod 600 "$PASS_FILE"
    echo "▶ 已生成访问密码: $TODO_PASSWORD"
    echo "  （存在 ${PASS_FILE}，之后部署自动复用；换密码：TODO_PASSWORD=... $0）"
  fi
fi

RR="${DOMAIN%%.*}"

# ---------------------------------------------------------------- 1. DNS
echo "▶ [1/3] DNS"
if "$ALIYUN_OPS/bin/vps" preflight "$RR" 2>&1 | grep -q "缺 A 记录"; then
  "$ALIYUN_OPS/bin/acs" dns add-a "$RR" -y
else
  echo "  ✓ A 记录已存在"
fi

# ---------------------------------------------------------------- 2. 服务
echo "▶ [2/3] 部署服务（systemd: ${NAME}, 内部端口: ${PORT}）"
ENV_ARGS=(
  --env "PORT=$PORT"
  --env "DATA_DIR=$DATA_DIR"
  # 只影响「首次迁移出 owner 空间」；之后密码以空间内设置为准
  --env "TODO_PASSWORD=$TODO_PASSWORD"
)
if [ -n "${TODO_INVITE:-}" ]; then
  ENV_ARGS+=(--env "TODO_INVITE=$TODO_INVITE")
else
  echo "  (未设 TODO_INVITE：创建空间不要求邀请码，按 IP 限流 5 次/小时)"
fi

"$ALIYUN_OPS/bin/vps" serve "$SELF" \
  --domain "$DOMAIN" \
  --port "$PORT" \
  --name "$NAME" \
  --start "node server.js" \
  --data-dir "$DATA_DIR" \
  "${ENV_ARGS[@]}"

# ---------------------------------------------------------------- 3. 自检
echo "▶ [3/3] 公网自检"
curl -sS -o /dev/null -w "  https://$DOMAIN/ → %{http_code}\n" "https://$DOMAIN/" || true
curl -sS "https://$DOMAIN/api/health" || true
echo
echo "  ✓ 完成: https://$DOMAIN/"
