# 单镜像：后端接口、处理 worker、管理后台前端都在里面（docker-compose.yml 用不同命令启动）
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# ffmpeg：检查视频、抽音频和抽帧；chromium + 中文字体：导出 PDF 报告
# 构建环境需经 HTTPS 代理（自签 CA）时，用 --secret id=build_ca,src=<CA 文件> 传入，CA 不会留在镜像里
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -f /run/secrets/build_ca ]; then \
      sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources; \
      echo 'Acquire::https::CAInfo "/run/secrets/build_ca";' > /etc/apt/apt.conf.d/99build-ca; \
    fi \
 && apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg chromium fonts-wqy-zenhei \
 && rm -rf /var/lib/apt/lists/* /etc/apt/apt.conf.d/99build-ca
WORKDIR /app
COPY pyproject.toml ./
COPY scoring ./scoring
RUN pip install --no-cache-dir ".[local]"
COPY backend ./backend
COPY config ./config
COPY docs/rubric.md docs/prd.md ./docs/
COPY --from=web /web/dist ./frontend/dist
ENV APP_FRONTEND_DIST=/app/frontend/dist APP_CHROMIUM=/usr/bin/chromium
RUN useradd --create-home --uid 10001 app
USER app
WORKDIR /app/backend
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
