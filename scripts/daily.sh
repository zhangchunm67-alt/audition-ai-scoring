#!/usr/bin/env bash
# 每天一次（由 launchd 或 cron 调用）：先删除到期媒体，再备份。到期删除先做，备份里就不会留下已到期的视频。
set -euo pipefail
cd "$(dirname "$0")/.."
echo "$(date '+%F %T') 中断检查：$(docker compose exec -T api python -m app.cli sweep-stuck)"
echo "$(date '+%F %T') 到期删除：$(docker compose exec -T api python -m app.cli purge-expired)"
./scripts/backup.sh
