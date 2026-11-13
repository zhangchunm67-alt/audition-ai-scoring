#!/usr/bin/env bash
# 每日备份（在宿主机上运行，例如 Mac Studio）：
#   1. 数据库：pg_dump 导出到本机临时目录，校验可读后用 BACKUP_KEY 加密（openssl AES-256）再写到 $BACKUP_DIR/db/，
#      NAS 上只有密文；保留 BACKUP_KEEP_DAYS 天；
#   2. 媒体：把 $MEDIA_DIR（MinIO 数据，服务端加密后的密文）按天做快照到 $BACKUP_DIR/media/<日期>/，
#      没变的文件用硬链接，不重复占空间；保留 BACKUP_MEDIA_KEEP 代。到期删除的视频最多在备份里多留这么多天。
#   3. 保护：媒体目录为空、或文件数比上次少一半以上时拒绝备份（本机数据可能已损坏，不能拿它覆盖备份）。
#   4. 结果写进管理后台（审计记录，看板显示“上次成功备份”）；失败时推送到 BACKUP_ALERT_WEBHOOK（群机器人）。
# 不备份 .env：里面的密钥须另外保存在密码管理器等与 NAS 分开的地方（与数据放在一起，NAS 失窃即可解密）。
# 恢复：scripts/restore_db.sh <备份文件>（见 README“备份与恢复”）。
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "缺少 .env" >&2; exit 2; }
env_get() { sed -n "s/^$1=//p" .env | tail -n 1; }
BACKUP_DIR=${BACKUP_DIR:-$(env_get BACKUP_DIR)}
MEDIA_DIR=${MEDIA_DIR:-$(env_get MEDIA_DIR)}
MEDIA_DIR=${MEDIA_DIR:-./data/minio}
KEEP_DAYS=${BACKUP_KEEP_DAYS:-$(env_get BACKUP_KEEP_DAYS)}
KEEP_DAYS=${KEEP_DAYS:-14}
MEDIA_KEEP=${BACKUP_MEDIA_KEEP:-$(env_get BACKUP_MEDIA_KEEP)}
MEDIA_KEEP=${MEDIA_KEEP:-7}
BACKUP_KEY=${BACKUP_KEY:-$(env_get BACKUP_KEY)}
WEBHOOK=${BACKUP_ALERT_WEBHOOK:-$(env_get BACKUP_ALERT_WEBHOOK)}

log() { echo "$(date '+%F %T') $*"; }
report() {  # report ok|failed 说明：写进管理后台；失败时推送群机器人
  docker compose exec -T api python -m app.cli backup-status "$1" "$2" >/dev/null 2>&1 || log "（写入管理后台失败）"
  if [ "$1" = failed ] && [ -n "$WEBHOOK" ]; then
    msg=$(printf '主播试镜评分系统备份失败（%s）：%s' "$(hostname)" "$2" | python3 -c 'import json,sys;print(json.dumps({"msgtype":"text","text":{"content":sys.stdin.read()}}))')
    curl -fsS -m 10 -H 'Content-Type: application/json' -d "$msg" "$WEBHOOK" >/dev/null || log "（告警推送失败）"
  fi
  if [ "$1" = failed ] && command -v osascript >/dev/null; then
    osascript -e "display notification \"$2\" with title \"试镜评分系统备份失败\"" 2>/dev/null || true
  fi
}
fail() { log "$1"; report failed "$1"; exit "${2:-1}"; }
trap 'fail "备份脚本异常退出（第 $LINENO 行）"' ERR

[ -n "$BACKUP_DIR" ] || fail "未设置 BACKUP_DIR（.env）" 2
[ -n "$BACKUP_KEY" ] || fail "未设置 BACKUP_KEY（.env），数据库备份不能明文写到 NAS" 2
# 标记文件确认目标确实是 NAS：NAS 没挂载时 /Volumes/xxx 不存在或是空目录，直接失败，不往本机磁盘写
[ -f "$BACKUP_DIR/.audition-backup" ] || fail "备份目录 $BACKUP_DIR 下没有标记文件 .audition-backup（NAS 没挂载？），本次不备份" 3
[ -d "$MEDIA_DIR" ] || fail "媒体目录 $MEDIA_DIR 不存在" 2

ts=$(date +%Y%m%d-%H%M%S)
mkdir -p "$BACKUP_DIR/db" "$BACKUP_DIR/media"

# —— 数据库：本机导出、校验、加密后再写 NAS ——
tmp=$(mktemp -d "${TMPDIR:-/tmp}/audition-backup.XXXXXX")
chmod 700 "$tmp"
trap 'rm -rf "$tmp"' EXIT
docker compose exec -T postgres pg_dump -U audition -Fc audition > "$tmp/db.dump"
docker compose exec -T postgres pg_restore --list < "$tmp/db.dump" > /dev/null  # 校验导出文件完整可读
dump="$BACKUP_DIR/db/audition-$ts.dump.enc"
BACKUP_KEY="$BACKUP_KEY" openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass env:BACKUP_KEY -in "$tmp/db.dump" -out "$dump.part"
mv "$dump.part" "$dump"
rm -f "$tmp/db.dump"
log "数据库已加密备份：${dump}（$(du -h "$dump" | cut -f1)）"
find "$BACKUP_DIR/db" -name 'audition-*.dump*' -mtime +"$KEEP_DAYS" -print -delete | sed 's/^/删除过期备份 /'
find "$BACKUP_DIR/db" -name '*.part' -mtime +1 -delete

# —— 媒体：先查本机数据是否正常，再做快照 ——
count=$(find "$MEDIA_DIR" -type f ! -name '.root_user' ! -name '.root_password' | wc -l | tr -d ' ')
last=$(cat "$BACKUP_DIR/media/.file-count" 2>/dev/null || echo 0)
[ "$count" -gt 0 ] || [ "$last" -eq 0 ] || fail "媒体目录 $MEDIA_DIR 是空的（上次备份时有 $last 个文件），本机数据可能已损坏，拒绝备份；请先排查" 4
if [ "$last" -gt 20 ] && [ $((count * 2)) -lt "$last" ]; then
  fail "媒体文件数从 $last 骤降到 ${count}，拒绝备份（防止把本机损坏的数据同步到 NAS）；确认无误后删除 $BACKUP_DIR/media/.file-count 再运行" 4
fi
prev=$(ls -1d "$BACKUP_DIR"/media/20*/ 2>/dev/null | tail -n 1 || true)
snap="$BACKUP_DIR/media/$ts"
# Bitnami MinIO 在数据目录里明文存了管理员账号密码（.root_user、.root_password），不带进备份
rsync -a --exclude=/.root_user --exclude=/.root_password ${prev:+--link-dest="$prev"} "$MEDIA_DIR/" "$snap.part/"
mv "$snap.part" "$snap"
echo "$count" > "$BACKUP_DIR/media/.file-count"
log "媒体快照：${snap}（$count 个文件）"
ls -1d "$BACKUP_DIR"/media/20*/ 2>/dev/null | awk -v k="$MEDIA_KEEP" '{a[NR]=$0} END {for (i = 1; i <= NR - k; i++) print a[i]}' | while read -r old; do rm -rf "$old"; log "删除过期媒体快照 $old"; done
find "$BACKUP_DIR/media" -maxdepth 1 -name '*.part' -mtime +1 -exec rm -rf {} +

# 本机磁盘超过 80% 时提醒（视频主要占用这里）
used=$(df -P "$MEDIA_DIR" | awk 'NR==2 {gsub("%", "", $5); print $5}')
if [ "${used:-0}" -ge 80 ]; then log "警告：媒体所在磁盘已用 ${used}%，请清理或扩容"; fi
report ok "数据库 $(du -h "$dump" | cut -f1)，媒体 $count 个文件"
