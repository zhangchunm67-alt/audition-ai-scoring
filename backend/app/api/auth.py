from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models.entities import AuditLog, User
from ..security import tokens
from ..security.passwords import DUMMY_HASH, verify_password
from ..security.rbac import perms_of
from ..services import audit
from ..settings import get_settings
from .deps import DB, current_user

router = APIRouter(prefix="/auth", tags=["登录"])
MAX_FAILURES = 10
WINDOW = timedelta(minutes=15)


class LoginIn(BaseModel):
    username: str
    password: str


class MeOut(BaseModel):
    id: str
    username: str
    display_name: str
    role: str
    permissions: list[str]


def me_of(u: User) -> MeOut:
    return MeOut(id=str(u.id), username=u.username, display_name=u.display_name, role=u.role, permissions=perms_of(u.role))


@router.post("/login", response_model=MeOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = DB) -> MeOut:
    since = datetime.now(timezone.utc) - WINDOW
    failures = db.scalar(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.action == "login_failed", AuditLog.target_id == body.username, AuditLog.at >= since
        )
    )
    if failures >= MAX_FAILURES:
        raise HTTPException(429, "登录失败次数过多，请 15 分钟后再试")
    user = db.scalar(select(User).where(User.username == body.username))
    ok = verify_password(user.password_hash if user else DUMMY_HASH, body.password)
    if not (user and ok and user.is_active):
        audit.record(db, request, actor_type="user", actor_id=None, action="login_failed", target_type="user", target_id=body.username)
        db.commit()
        raise HTTPException(401, "用户名或密码错误")
    s = get_settings()
    response.set_cookie(
        tokens.COOKIE, tokens.issue(user.id, s.session_key, s.session_hours), max_age=s.session_hours * 3600,
        httponly=True, secure=s.cookie_secure, samesite="strict", path="/",
    )
    audit.record(db, request, actor_type="user", actor_id=str(user.id), action="login", target_type="user", target_id=str(user.id))
    db.commit()
    return me_of(user)


@router.post("/logout", status_code=204)
def logout(response: Response, request: Request, user: User = Depends(current_user), db: Session = DB) -> None:
    response.delete_cookie(tokens.COOKIE, path="/")
    audit.record(db, request, actor_type="user", actor_id=str(user.id), action="logout", target_type="user", target_id=str(user.id))
    db.commit()


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(current_user)) -> MeOut:
    return me_of(user)
