#!/usr/bin/env bash
# 同机服务器部署：拉取最新代码 → 确保独立库与账号 → 重建并重启 web/fetch
#
# 依赖服务器上已有的 ledger-db（PostgreSQL 容器）与 ledger-shared-net（共享网络）。
# 只创建/更新本应用自己的库与账号，不启动、重建或改动其他项目的服务。
#
# 用法（服务器 /opt/seafood-price-monitor）：
#   bash scripts/deploy.sh
set -euo pipefail

cd "$(dirname "$0")/.."

BRANCH="${DEPLOY_BRANCH:-main}"
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.server.yml)

# 脚本自身会被 git pull 更新；bash 仍按旧内容执行，检测到变化时重新执行一次
SELF_BEFORE=$(sha256sum "$0" | cut -d' ' -f1)

echo "==> 拉取 origin/$BRANCH"
git fetch --prune origin
git checkout "$BRANCH"
# 用 merge --ff-only 而不是 pull：避免重复 fetch 后 FETCH_HEAD 多分支导致无法快进
git merge --ff-only "origin/$BRANCH"

SELF_AFTER=$(sha256sum "$0" | cut -d' ' -f1)
if [ "${DEPLOY_REEXEC:-0}" != "1" ] && [ "$SELF_BEFORE" != "$SELF_AFTER" ]; then
  echo "==> 部署脚本已更新，重新执行"
  export DEPLOY_REEXEC=1
  exec bash "$0" "$@"
fi

if [ ! -f .env ]; then
  echo "缺少 .env，请先执行 cp deploy/server.env.example .env 并填写配置" >&2
  exit 1
fi

# 只读取需要的键，不 source .env，避免密码中的 $ ! 等字符被 shell 展开
read_env() {
  local key="$1" value
  value=$(grep -E "^${key}=" .env | tail -n1 | cut -d= -f2- || true)
  value="${value#\'}" ; value="${value%\'}"
  value="${value#\"}" ; value="${value%\"}"
  printf '%s' "$value"
}

WEB_PORT="${WEB_PORT:-$(read_env WEB_PORT)}"; WEB_PORT="${WEB_PORT:-38083}"
DB_NAME="${DB_NAME:-$(read_env DB_NAME)}"; DB_NAME="${DB_NAME:-seafood_price}"
DB_USER="${DB_USER:-$(read_env DB_USER)}"; DB_USER="${DB_USER:-seafood}"
DB_PASSWORD="${DB_PASSWORD:-$(read_env DB_PASSWORD)}"
PG_ADMIN_PASSWORD="${PG_ADMIN_PASSWORD:-$(read_env PG_ADMIN_PASSWORD)}"

: "${DB_PASSWORD:?请在 .env 配置 DB_PASSWORD（本应用专用账号密码）}"

# ledger-db 容器内是 trust 认证时可不填 PG_ADMIN_PASSWORD；否则必须提供
if [ -z "$PG_ADMIN_PASSWORD" ]; then
  if ! docker exec ledger-db psql -U postgres -d postgres -tAc 'select 1' >/dev/null 2>&1; then
    echo "PG_ADMIN_PASSWORD 未配置，且 ledger-db 不允许免密登录；请在 .env 填写 postgres 密码" >&2
    exit 1
  fi
fi

if ! [[ "$DB_NAME" =~ ^[a-z_][a-z0-9_]*$ && "$DB_USER" =~ ^[a-z_][a-z0-9_]*$ ]]; then
  echo "库名/账号只能包含小写字母、数字、下划线" >&2
  exit 1
fi

# 只读检查共享网络与数据库容器，绝不创建、启动或重建它们
if ! docker network inspect ledger-shared-net >/dev/null 2>&1; then
  echo "未找到 ledger-shared-net，请确认共享 PostgreSQL 已部署" >&2
  exit 1
fi
if [ "$(docker inspect -f '{{.State.Running}}' ledger-db 2>/dev/null || echo false)" != "true" ]; then
  echo "ledger-db 未运行，本次部署终止（不自动启动其他项目的数据库）" >&2
  exit 1
fi

echo "==> 确保专用库与账号存在"
PSQL=(docker exec -i -e PGPASSWORD="$PG_ADMIN_PASSWORD" ledger-db psql -U postgres -d postgres -v ON_ERROR_STOP=1 -v usr="$DB_USER" -v pwd="$DB_PASSWORD" -v dbname="$DB_NAME")

if [ -z "$("${PSQL[@]}" -tA <<< "SELECT 1 FROM pg_roles WHERE rolname = :'usr'")" ]; then
  echo "    创建角色 $DB_USER"
  "${PSQL[@]}" >/dev/null <<'EOSQL'
CREATE ROLE :"usr" LOGIN PASSWORD :'pwd';
EOSQL
else
  "${PSQL[@]}" >/dev/null <<'EOSQL'
ALTER ROLE :"usr" LOGIN PASSWORD :'pwd';
EOSQL
fi

if [ -z "$("${PSQL[@]}" -tA <<< "SELECT 1 FROM pg_database WHERE datname = :'dbname'")" ]; then
  echo "    创建数据库 $DB_NAME"
  "${PSQL[@]}" -tA <<< 'CREATE DATABASE :"dbname" OWNER :"usr"' >/dev/null
fi

echo "==> 构建并重启容器"
"${COMPOSE[@]}" up -d --build --wait --wait-timeout 600

echo "==> 清理悬空镜像（不影响运行中的容器）"
docker image prune -f >/dev/null

echo "==> 部署完成：http://<服务器IP>:${WEB_PORT}"
"${COMPOSE[@]}" ps
