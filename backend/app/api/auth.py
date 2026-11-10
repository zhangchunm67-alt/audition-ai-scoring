from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models.entities import AuditLog, User
from ..security import tokens
from ..security.crypto import lookup_hash
from ..security.passwords import DUMMY_HASH, MIN_LENGTH, hash_password, verify_password
from ..security.rbac import perms_of
from ..services import audit
from ..settings import get_settings
from .deps import DB, current_user

router = APIRouter(prefix="/auth", tags=["登录"])
MAX_FAILURES = 10  # 同一账号 15 分钟内失败次数上限
MAX_FAILURES_PER_IP = 30  # 同一来源地址 15 分钟内失败次数上限（防止换着用户名猜）
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
    must_change_password: bool = False


def me_of(u: User) -> MeOut:
    return MeOut(id=str(u.id), username=u.username, display_name=u.display_name, role=u.role, permissions=perms_of(u.role),
                 must_change_password=u.must_change_password)


def _set_cookie(response: Response, user: User) -> None:
    s = get_settings()
    response.set_cookie(
        tokens.COOKIE, tokens.issue(user.id, s.session_key, s.session_hours, user.session_version), max_age=s.session_hours * 3600,
        httponly=True, secure=s.cookie_secure, samesite="strict", path="/",
    )


@router.post("/login", response_model=MeOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = DB) -> MeOut:
    since = datetime.now(timezone.utc) - WINDOW
    failures = db.scalar(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.action == "login_failed", AuditLog.target_id == body.username, AuditLog.at >= since
        )
    )
    ip = request.client.host if request.client else None
    by_ip = db.scalar(select(func.count()).select_from(AuditLog).where(
        AuditLog.action == "login_failed", AuditLog.ip == ip, AuditLog.at >= since)) if ip else 0
    if failures >= MAX_FAILURES or by_ip >= MAX_FAILURES_PER_IP:
        raise HTTPException(429, "登录失败次数过多，请 15 分钟后再试")
    user = db.scalar(select(User).where(User.username == body.username))
    ok = verify_password(user.password_hash if user else DUMMY_HASH, body.password)
    if not (user and ok and user.is_active):
        # 不存在的用户名只记哈希：有人把密码误输进用户名框时，审计里不留明文
        target = body.username if user else "unknown:" + lookup_hash(body.username, get_settings().hash_key)[:16]
        audit.record(db, request, actor_type="user", actor_id=None, action="login_failed", target_type="user", target_id=target)
        db.commit()
        raise HTTPException(401, "用户名或密码错误")
    _set_cookie(response, user)
    audit.record(db, request, actor_type="user", actor_id=str(user.id), action="login", target_type="user", target_id=str(user.id))
    db.commit()
    return me_of(user)


@router.post("/logout", status_code=204)
def logout(response: Response, request: Request, user: User = Depends(current_user), db: Session = DB) -> None:
    """退出：本账号之前签发的登录状态全部失效（包括别处登录、被截获的）。"""
    user.session_version += 1
    response.delete_cookie(tokens.COOKIE, path="/")
    audit.record(db, request, actor_type="user", actor_id=str(user.id), action="logout", target_type="user", target_id=str(user.id))
    db.commit()


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(current_user)) -> MeOut:
    return me_of(user)


class PasswordIn(BaseModel):
    old_password: str
    new_password: str = Field(min_length=MIN_LENGTH)


@router.post("/password", response_model=MeOut)
def change_password(body: PasswordIn, request: Request, response: Response, user: User = Depends(current_user), db: Session = DB) -> MeOut:
    """本人改密码。管理员设的初始密码或重置的密码，须本人先改才能使用系统。改完其他地方的登录全部失效。"""
    if not verify_password(user.password_hash, body.old_password):
        raise HTTPException(422, "原密码不对")
    if body.new_password == body.old_password:
        raise HTTPException(422, "新密码不能与原密码相同")
    user.password_hash, user.must_change_password = hash_password(body.new_password), False
    user.session_version += 1
    _set_cookie(response, user)
    audit.record(db, request, actor_type="user", actor_id=str(user.id), action="password_change", target_type="user", target_id=str(user.id))
    db.commit()
    return me_of(user)
