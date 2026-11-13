#!/usr/bin/env bash
# 本地一键启动：PostgreSQL（.local/pgdata @ 55432）→ 数据库迁移 → 后端（托管 frontend/dist）。
# 用法：./scripts/start_local.sh     停止：Ctrl+C
# 可选：NO_OPEN=1 ./scripts/start_local.sh  不自动打开浏览器
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PORT="${APP_PORT:-8000}"
PGPORT="${LOCAL_PGPORT:-55432}"
PGDATA="$ROOT/.local/pgdata"
LOGDIR="$ROOT/.local"
mkdir -p "$LOGDIR"

# 读取本地环境变量（DATABASE_URL、三把密钥、本地存储路径等）
set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

# 找到 pg_ctl（优先使用创建 .local/pgdata 时用的 PostgreSQL 18）
PGBIN=""
for d in "$HOME"/.pg0/installation/*/bin /opt/homebrew/opt/postgresql@*/bin; do
  [ -x "$d/pg_ctl" ] && PGBIN="$d"
done
if [ -z "$PGBIN" ] && command -v pg_ctl >/dev/null 2>&1; then
  PGBIN="$(dirname "$(command -v pg_ctl)")"
fi

# 1) 数据库
if "$PGBIN/pg_isready" -h 127.0.0.1 -p "$PGPORT" >/dev/null 2>&1; then
  echo "✓ PostgreSQL 已在 127.0.0.1:$PGPORT 运行"
else
  if [ -z "$PGBIN" ] || [ ! -d "$PGDATA" ]; then
    echo "✗ 找不到 PostgreSQL 或数据目录 $PGDATA" >&2
    exit 1
  fi
  echo "→ 启动 PostgreSQL ($PGPORT)..."
  "$PGBIN/pg_ctl" -D "$PGDATA" -l "$LOGDIR/postgres.log" -o "-p $PGPORT" start >/dev/null
  for _ in $(seq 50); do
    "$PGBIN/pg_isready" -h 127.0.0.1 -p "$PGPORT" >/dev/null 2>&1 && break
    sleep 0.2
  done
  "$PGBIN/pg_isready" -h 127.0.0.1 -p "$PGPORT" >/dev/null
  echo "✓ PostgreSQL 已启动"
fi

# 2) 迁移
echo "→ 应用数据库迁移..."
(cd "$ROOT/backend" && "$ROOT/.venv/bin/python" -m alembic upgrade head)
(cd "$ROOT/backend" && "$ROOT/.venv/bin/python" -m app.cli sync-rubric)

# 3) 前端构建产物（缺失才构建）
if [ ! -f "$ROOT/frontend/dist/index.html" ]; then
  echo "→ 构建前端..."
  (cd "$ROOT/frontend" && npm install && npm run build)
fi

# 4) 已在运行就直接打开
if curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
  echo "✓ 后端已在运行：http://127.0.0.1:$PORT"
  [ "${NO_OPEN:-0}" = "1" ] || open "http://127.0.0.1:$PORT"
  exit 0
fi

# 5) 启动后端
echo "→ 启动后端 http://127.0.0.1:$PORT ..."
cd "$ROOT/backend"
"$ROOT/.venv/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" \
  >>"$LOGDIR/api.log" 2>&1 &
API_PID=$!
trap 'kill "$API_PID" 2>/dev/null || true' EXIT INT TERM

for _ in $(seq 100); do
  if curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$API_PID" 2>/dev/null; then
    echo "✗ 后端启动失败，最后日志：" >&2
    tail -20 "$LOGDIR/api.log" >&2
    exit 1
  fi
  sleep 0.2
done

if ! curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
  echo "✗ 后端健康检查超时，见 $LOGDIR/api.log" >&2
  exit 1
fi

echo "✓ 启动完成：http://127.0.0.1:$PORT  （接口文档 /api/docs）"
echo "  日志：$LOGDIR/api.log  （Ctrl+C 停止后端）"
[ "${NO_OPEN:-0}" = "1" ] || open "http://127.0.0.1:$PORT"
wait "$API_PID"
