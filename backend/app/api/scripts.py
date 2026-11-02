"""朗读稿（M1-3）。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.entities import ReadingScript, User
from ..security.rbac import Perm
from ..services import audit
from .deps import DB, require

router = APIRouter(prefix="/reading-scripts", tags=["朗读稿"])
Read = Depends(require(Perm.config_read))
Write = Depends(require(Perm.config_write))


class ScriptIn(BaseModel):
    title: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1)
    active: bool = True


class ScriptOut(ScriptIn):
    id: uuid.UUID
    char_count: int


def _out(s: ReadingScript) -> ScriptOut:
    return ScriptOut(id=s.id, title=s.title, text=s.text, active=s.active, char_count=len("".join(s.text.split())))


@router.get("", response_model=list[ScriptOut])
def list_scripts(db: Session = DB, _: User = Read) -> list[ScriptOut]:
    return [_out(s) for s in db.scalars(select(ReadingScript).order_by(ReadingScript.created_at))]


@router.post("", response_model=ScriptOut, status_code=201)
def create_script(body: ScriptIn, request: Request, db: Session = DB, actor: User = Write) -> ScriptOut:
    s = ReadingScript(**body.model_dump())
    db.add(s)
    db.flush()
    audit.record(db, request, actor_type="user", actor_id=str(actor.id), action="script_create", target_type="reading_script", target_id=str(s.id))
    db.commit()
    return _out(s)


@router.put("/{sid}", response_model=ScriptOut)
def update_script(sid: uuid.UUID, body: ScriptIn, request: Request, db: Session = DB, actor: User = Write) -> ScriptOut:
    s = db.get(ReadingScript, sid)
    if s is None:
        raise HTTPException(404, "朗读稿不存在")
    for k, v in body.model_dump().items():
        setattr(s, k, v)
    audit.record(db, request, actor_type="user", actor_id=str(actor.id), action="script_update", target_type="reading_script", target_id=str(s.id))
    db.commit()
    return _out(s)
