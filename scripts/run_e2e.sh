#!/usr/bin/env bash
# 管理后台端到端测试：建一个临时库，迁移、导入演示数据、建账号，启动后端（托管前端构建产物），跑 Playwright。
# 需要：本机 PostgreSQL（E2E_ADMIN_URL 指向可建库的账号）、已执行 npm install。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
DB_ADMIN_URL="${E2E_ADMIN_URL:-postgresql://audition:audition@localhost/postgres}"
DB_NAME="audition_e2e"
PORT="${E2E_PORT:-8765}"
export E2E_PASSWORD="e2e-password-123"
export DATABASE_URL="postgresql+psycopg://audition:audition@localhost/${DB_NAME}"
for k in APP_SESSION_KEY APP_DATA_KEY APP_HASH_KEY; do export "$k=$("$PY" -c 'import base64,os;print(base64.b64encode(os.urandom(32)).decode())')"; done
export APP_COOKIE_SECURE=false APP_FRONTEND_DIST="$ROOT/frontend/dist"
TMP="$(mktemp -d)"
export APP_STORAGE=local APP_STORAGE_DIR="$TMP/storage" APP_UPLOAD_PART_BYTES=65536
export E2E_VIDEO="$TMP/audition.mp4"
ffmpeg -v error -y -f lavfi -i testsrc=size=320x240:rate=15:duration=20 -f lavfi -i sine=frequency=440:duration=20 \
  -c:v libx264 -preset ultrafast -pix_fmt yuv420p -c:a aac -shortest -movflags +faststart "$E2E_VIDEO"

psql "$DB_ADMIN_URL" -qc "DROP DATABASE IF EXISTS ${DB_NAME}" -c "CREATE DATABASE ${DB_NAME}"
(cd "$ROOT/frontend" && npm run build --silent)
(cd "$ROOT/backend" && "$PY" -m alembic upgrade head)
cd "$ROOT/backend"
"$PY" -m app.cli seed-demo
for r in admin compliance hr; do NEW_USER_PASSWORD="$E2E_PASSWORD" "$PY" -m app.cli create-user --username "e2e-$r" --role "$r" --display-name "E2E $r"; done
"$PY" -m uvicorn app.main:app --port "$PORT" --log-level warning &
PID=$!
trap 'kill $PID 2>/dev/null; rm -rf "$TMP"; psql "$DB_ADMIN_URL" -qc "DROP DATABASE IF EXISTS ${DB_NAME}" >/dev/null 2>&1 || true' EXIT
for _ in $(seq 50); do curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null && break; sleep 0.2; done
E2E_BASE_URL="http://127.0.0.1:$PORT" node "$ROOT/frontend/e2e/admin.e2e.mjs"
