from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.entities import User
from ..security import tokens
from ..security.rbac import Perm, allowed
from ..settings import get_settings

DB = Depends(get_db)


def current_user(request: Request, db: Session = DB) -> User:
    token = request.cookies.get(tokens.COOKIE)
    uid = tokens.verify(token, get_settings().session_key) if token else None
    if uid is None:
        raise HTTPException(401, "请先登录")
    user = db.get(User, uid)
    if user is None or not user.is_active:
        raise HTTPException(401, "账号不存在或已停用")
    return user


def require(perm: Perm) -> Callable[..., User]:
    def dep(user: User = Depends(current_user)) -> User:
        if not allowed(user.role, perm):
            raise HTTPException(403, "没有权限")
        return user

    return dep
