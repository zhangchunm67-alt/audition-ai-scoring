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
# 本机用 http 试用时为 false；正式部署必须走 https 并改为 true
APP_COOKIE_SECURE=false
# 未录用候选人媒体保存天数：30 仅为占位，正式值待法务确认
APP_RETENTION_DAYS=30
APP_PORT=8000
APP_PROVIDERS=mock
EOT
chmod 600 .env
echo "已生成 .env"
