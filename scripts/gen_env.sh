#!/usr/bin/env bash
# 生成 docker-compose 用的 .env（随机密钥）。已存在则不覆盖。
set -euo pipefail
cd "$(dirname "$0")/.."
[ -e .env ] && { echo ".env 已存在，未覆盖"; exit 0; }
k() { python3 -c 'import base64,os;print(base64.b64encode(os.urandom(32)).decode())'; }
p() { python3 -c 'import secrets;print(secrets.token_urlsafe(24))'; }
cat > .env <<EOT
# —— 密钥（务必备份 APP_DATA_KEY：丢失后已加密的个人信息无法解密）——
APP_SESSION_KEY=$(k)
APP_DATA_KEY=$(k)
APP_HASH_KEY=$(k)
POSTGRES_PASSWORD=$(p)
S3_ACCESS_KEY=audition$(p | tr -dc 'a-z0-9' | head -c 8)
S3_SECRET_KEY=$(p)
MINIO_KMS_SECRET_KEY=audition-kms:$(k)
# —— 运行配置 ——
# 员工访问用的地址（内网域名或 Mac Studio 的固定内网 IP），Caddy 按它签发 HTTPS 证书
APP_HOST=
# 登录 cookie 只经 HTTPS 发送。只在本机 http://127.0.0.1:8000 临时调试时才改成 false
APP_COOKIE_SECURE=true
# 未录用候选人媒体保存天数：30 仅为占位，正式值待法务确认
APP_RETENTION_DAYS=30
APP_PORT=8000
APP_PROVIDERS=mock
# —— 存储与备份 ——
# 媒体（MinIO 加密后的文件）在宿主机上的目录，放本机 SSD
MEDIA_DIR=./data/minio
# 备份目标：NAS 挂载目录，例如 /Volumes/audition-backup。目录里须有标记文件 .audition-backup（防止 NAS 没挂载时写到本机）
BACKUP_DIR=
# 数据库备份保留天数
BACKUP_KEEP_DAYS=14
# 媒体备份保留几代（每天一代，没变的文件用硬链接，不重复占空间）
BACKUP_MEDIA_KEEP=7
# 数据库备份加密口令（openssl AES-256）。务必另存到密码管理器：丢了就解不开备份；不要和备份放在同一个 NAS
BACKUP_KEY=$(p)$(p)
# 备份失败时推送告警的群机器人地址（企业微信 / 钉钉 / 飞书的 webhook），留空则只写日志和管理后台
BACKUP_ALERT_WEBHOOK=
EOT
chmod 600 .env
echo "已生成 .env"
