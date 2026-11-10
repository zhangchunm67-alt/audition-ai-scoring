from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.entities import User
from ..security.passwords import MIN_LENGTH, hash_password
from ..security.rbac import Perm, Role
from ..services import audit
from .deps import DB, require

router = APIRouter(prefix="/users", tags=["账号"])
Admin = Depends(require(Perm.users_manage))


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    role: Role
    is_active: bool


class UserIn(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z0-9_.-]{3,64}$")
    display_name: str = Field(min_length=1, max_length=64)
    role: Role
    password: str = Field(min_length=MIN_LENGTH)


class UserPatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=64)
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=MIN_LENGTH)


def _out(u: User) -> UserOut:
    return UserOut(id=u.id, username=u.username, display_name=u.display_name, role=Role(u.role), is_active=u.is_active)


@router.get("", response_model=list[UserOut])
def list_users(db: Session = DB, _: User = Admin) -> list[UserOut]:
    return [_out(u) for u in db.scalars(select(User).order_by(User.created_at))]


@router.get("/anchors", response_model=list[UserOut])
def list_anchors(db: Session = DB, _: User = Depends(require(Perm.hiring_update))) -> list[UserOut]:
    """供 HR 关联新主播账号时选择。"""
    return [_out(u) for u in db.scalars(select(User).where(User.role == "anchor", User.is_active).order_by(User.display_name))]


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserIn, request: Request, db: Session = DB, actor: User = Admin) -> UserOut:
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(409, "用户名已存在")
    u = User(username=body.username, display_name=body.display_name, role=body.role.value, password_hash=hash_password(body.password),
             must_change_password=True)  # 管理员设的初始密码，本人首次登录须修改
    db.add(u)
    db.flush()
    audit.record(db, request, actor_type="user", actor_id=str(actor.id), action="user_create", target_type="user", target_id=str(u.id), role=u.role)
    db.commit()
    return _out(u)


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: uuid.UUID, body: UserPatch, request: Request, db: Session = DB, actor: User = Admin) -> UserOut:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "账号不存在")
    if u.id == actor.id and ((body.role and body.role != Role.admin) or body.is_active is False):
        raise HTTPException(409, "不能停用自己或取消自己的管理员角色")
    changed = body.model_dump(exclude_none=True, exclude={"password"})
    for k, v in changed.items():
        setattr(u, k, v.value if isinstance(v, Role) else v)
    if body.password:
        u.password_hash, u.must_change_password = hash_password(body.password), True
        changed["password"] = "已重置"
    if body.password or body.role or body.is_active is False:
        u.session_version += 1  # 重置密码、改角色、停用：之前的登录全部失效
    audit.record(db, request, actor_type="user", actor_id=str(actor.id), action="user_update", target_type="user", target_id=str(u.id),
                 changes={k: (v.value if isinstance(v, Role) else v) for k, v in changed.items()})
    db.commit()
    return _out(u)
