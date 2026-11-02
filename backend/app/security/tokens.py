"""登录会话：签名的 JWT 放在 httpOnly cookie 里。每次请求仍从数据库读取用户状态和角色。"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt

COOKIE = "session"
_ALG = "HS256"


def issue(user_id: uuid.UUID, key: bytes, hours: int) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(user_id), "iat": now, "exp": now + timedelta(hours=hours), "jti": uuid.uuid4().hex}, key, algorithm=_ALG)


def verify(token: str, key: bytes) -> uuid.UUID | None:
    try:
        data = jwt.decode(token, key, algorithms=[_ALG], options={"require": ["sub", "exp"]})
        return uuid.UUID(data["sub"])
    except (jwt.PyJWTError, ValueError):
        return None
