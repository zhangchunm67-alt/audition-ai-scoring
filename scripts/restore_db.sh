#!/usr/bin/env bash
# 从加密备份恢复数据库：scripts/restore_db.sh /Volumes/audition-backup/db/audition-20261110-030000.dump.enc
# 需要 .env 里的 BACKUP_KEY（与备份时相同）。会覆盖当前数据库，先停掉 api 和 worker：docker compose stop api worker
set -euo pipefail
cd "$(dirname "$0")/.."
[ $# -eq 1 ] && [ -f "$1" ] || { echo "用法：$0 <备份文件.dump.enc>" >&2; exit 2; }
BACKUP_KEY=${BACKUP_KEY:-$(sed -n 's/^BACKUP_KEY=//p' .env | tail -n 1)}
[ -n "$BACKUP_KEY" ] || { echo "缺少 BACKUP_KEY" >&2; exit 2; }
BACKUP_KEY="$BACKUP_KEY" openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:BACKUP_KEY -in "$1" \
  | docker compose exec -T postgres pg_restore -U audition -d audition --clean --if-exists --no-owner
echo "已恢复：$1"
