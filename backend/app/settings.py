"""运行配置，全部来自环境变量。密钥没有默认值，缺了直接报错。"""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from functools import lru_cache


class SettingsError(RuntimeError):
    pass


def _key(name: str) -> bytes:
    raw = os.environ.get(name)
    if not raw:
        raise SettingsError(f"缺少环境变量 {name}（32 字节密钥的 base64）")
    try:
        key = base64.b64decode(raw, validate=True)
    except ValueError as exc:
        raise SettingsError(f"{name} 不是合法的 base64") from exc
    if len(key) != 32:
        raise SettingsError(f"{name} 解码后须为 32 字节，实际 {len(key)}")
    return key


@dataclass(frozen=True)
class Settings:
    database_url: str
    session_key: bytes  # 登录会话签名
    data_key: bytes  # 个人信息字段加密（AES-256-GCM）
    hash_key: bytes  # 手机号等查找用哈希（HMAC-SHA256）
    session_hours: int = 8
    cookie_secure: bool = True
    retention_days: int = 30  # 未录用候选人媒体保存天数；30 仅为开发测试占位（C13、C24）
    frontend_dist: str | None = None
    env: str = "development"  # production 时禁止本地目录存储
    storage: str = "local"  # local / s3
    storage_dir: str | None = None
    s3_endpoint: str | None = None
    s3_region: str | None = None
    s3_bucket: str | None = None
    s3_sse: str = "AES256"
    max_upload_bytes: int = 8 * 1024**3
    upload_part_bytes: int = 8 * 1024**2  # S3 分片最小 5 MB
    queue: str = "inline"  # inline（同步执行，开发和测试）/ rq（Redis 队列，生产）
    redis_url: str = "redis://localhost:6379/0"
    retry_backoff_s: tuple[float, ...] = (5.0, 20.0)  # 失败自动重试 2 次（M4-4）及每次等待秒数
    call_retry_backoff_s: tuple[float, ...] = (1.0, 3.0)  # 单次供应商调用失败后再试 2 次
    limit_llm: int = 8  # 同时调用大模型的上限（所有 worker 合计）；压测表明 ≥ 8 才能在最坏情况下 30 分钟内出报告
    limit_asr: int = 3
    detector_workers: int = 6  # 一轮内并行跑检测器的线程数
    stuck_after_min: int = 180  # 已提交 / 处理中超过这么久没完成，视为中断（断电、重启）


@lru_cache
def get_settings() -> Settings:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SettingsError("缺少环境变量 DATABASE_URL")
    return Settings(
        database_url=url,
        session_key=_key("APP_SESSION_KEY"),
        data_key=_key("APP_DATA_KEY"),
        hash_key=_key("APP_HASH_KEY"),
        session_hours=int(os.environ.get("APP_SESSION_HOURS", "8")),
        cookie_secure=os.environ.get("APP_COOKIE_SECURE", "true").lower() != "false",
        retention_days=int(os.environ.get("APP_RETENTION_DAYS", "30")),
        frontend_dist=os.environ.get("APP_FRONTEND_DIST") or None,
        env=os.environ.get("APP_ENV", "development"),
        storage=os.environ.get("APP_STORAGE", "local"),
        storage_dir=os.environ.get("APP_STORAGE_DIR") or None,
        s3_endpoint=os.environ.get("APP_S3_ENDPOINT") or None,
        s3_region=os.environ.get("APP_S3_REGION") or None,
        s3_bucket=os.environ.get("APP_S3_BUCKET") or None,
        s3_sse=os.environ.get("APP_S3_SSE", "AES256"),
        max_upload_bytes=int(os.environ.get("APP_MAX_UPLOAD_BYTES", str(8 * 1024**3))),
        upload_part_bytes=int(os.environ.get("APP_UPLOAD_PART_BYTES", str(8 * 1024**2))),
        queue=os.environ.get("APP_QUEUE", "inline"),
        redis_url=os.environ.get("APP_REDIS_URL", "redis://localhost:6379/0"),
        retry_backoff_s=tuple(float(x) for x in os.environ.get("APP_RETRY_BACKOFF_S", "5,20").split(",") if x.strip()),
        call_retry_backoff_s=tuple(float(x) for x in os.environ.get("APP_CALL_RETRY_BACKOFF_S", "1,3").split(",") if x.strip()),
        limit_llm=int(os.environ.get("APP_LIMIT_LLM", "8")),
        limit_asr=int(os.environ.get("APP_LIMIT_ASR", "3")),
        detector_workers=int(os.environ.get("APP_DETECTOR_WORKERS", "6")),
        stuck_after_min=int(os.environ.get("APP_STUCK_AFTER_MIN", "180")),
    )
