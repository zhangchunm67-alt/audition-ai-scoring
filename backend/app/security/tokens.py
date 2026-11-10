"""登录会话：签名的 JWT 放在 httpOnly cookie 里。每次请求仍从数据库读取用户状态和角色。"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt

COOKIE = "session"
_ALG = "HS256"


def issue(user_id: uuid.UUID, key: bytes, hours: int, session_version: int = 0) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(user_id), "sv": session_version, "iat": now, "exp": now + timedelta(hours=hours), "jti": uuid.uuid4().hex},
                      key, algorithm=_ALG)


def verify(token: str, key: bytes) -> tuple[uuid.UUID, int] | None:
    """返回 (用户编号, 会话版本)。会话版本与数据库里的不一致（已退出、改过密码）时由调用方拒绝。"""
    try:
        data = jwt.decode(token, key, algorithms=[_ALG], options={"require": ["sub", "exp"]})
        return uuid.UUID(data["sub"]), int(data.get("sv", 0))
    except (jwt.PyJWTError, ValueError, TypeError):
        return None
