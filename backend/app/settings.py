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
    )
