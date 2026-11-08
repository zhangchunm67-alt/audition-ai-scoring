#!/usr/bin/env bash
# 每日备份（在宿主机上运行，例如 Mac Studio）：
#   1. 数据库：pg_dump 导出到 $BACKUP_DIR/db/，校验可读，保留 BACKUP_KEEP_DAYS 天；
#   2. 媒体：把 $MEDIA_DIR（MinIO 数据，服务端加密后的密文）同步到 $BACKUP_DIR/media/。
#      用 --delete 同步：到期删除的视频，备份里也随之删除，不在备份中超期保留候选人资料。
# 不备份 .env：里面的密钥须另外保存在密码管理器等与 NAS 分开的地方（与数据放在一起，NAS 失窃即可解密）。
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "缺少 .env" >&2; exit 2; }
env_get() { sed -n "s/^$1=//p" .env | tail -n 1; }
BACKUP_DIR=${BACKUP_DIR:-$(env_get BACKUP_DIR)}
MEDIA_DIR=${MEDIA_DIR:-$(env_get MEDIA_DIR)}
MEDIA_DIR=${MEDIA_DIR:-./data/minio}
KEEP_DAYS=${BACKUP_KEEP_DAYS:-$(env_get BACKUP_KEEP_DAYS)}
KEEP_DAYS=${KEEP_DAYS:-14}

log() { echo "$(date '+%F %T') $*"; }
[ -n "$BACKUP_DIR" ] || { log "未设置 BACKUP_DIR（.env）"; exit 2; }
# 标记文件确认目标确实是 NAS：NAS 没挂载时 /Volumes/xxx 不存在或是空目录，直接失败，不往本机磁盘写
[ -f "$BACKUP_DIR/.audition-backup" ] || { log "备份目录 $BACKUP_DIR 下没有标记文件 .audition-backup（NAS 没挂载？），本次不备份"; exit 3; }
[ -d "$MEDIA_DIR" ] || { log "媒体目录 $MEDIA_DIR 不存在"; exit 2; }

ts=$(date +%Y%m%d-%H%M%S)
mkdir -p "$BACKUP_DIR/db" "$BACKUP_DIR/media"
dump="$BACKUP_DIR/db/audition-$ts.dump"
docker compose exec -T postgres pg_dump -U audition -Fc audition > "$dump.part"
docker compose exec -T postgres pg_restore --list < "$dump.part" > /dev/null  # 校验导出文件完整可读
mv "$dump.part" "$dump"
log "数据库已备份：$dump（$(du -h "$dump" | cut -f1)）"
find "$BACKUP_DIR/db" -name 'audition-*.dump' -mtime +"$KEEP_DAYS" -print -delete | sed 's/^/删除过期备份 /'
find "$BACKUP_DIR/db" -name 'audition-*.dump.part' -mtime +1 -delete

# Bitnami MinIO 在数据目录里明文存了管理员账号密码（.root_user、.root_password），不带进备份
rsync -a --delete --exclude=/.root_user --exclude=/.root_password "$MEDIA_DIR/" "$BACKUP_DIR/media/"
log "媒体已同步：$(du -sh "$BACKUP_DIR/media" | cut -f1)"

# 本机磁盘超过 80% 时提醒（视频主要占用这里）
used=$(df -P "$MEDIA_DIR" | awk 'NR==2 {gsub("%", "", $5); print $5}')
if [ "${used:-0}" -ge 80 ]; then log "警告：媒体所在磁盘已用 ${used}%，请清理或扩容"; fi
