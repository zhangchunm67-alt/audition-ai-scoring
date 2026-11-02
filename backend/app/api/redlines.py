"""红线词表与正确说法（M1-5）：只有合规角色能写。"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, RootModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.entities import RedlineLexiconVersion, User
from ..security.rbac import Perm
from ..services import audit
from ..services.rubrics import load, reference
from .deps import DB, require

router = APIRouter(prefix="/redline-lexicons", tags=["红线词表"])
Read = Depends(require(Perm.redline_read))
Write = Depends(require(Perm.redline_write))


class RedlineEntry(BaseModel):
    name: str = Field(min_length=1)  # 如“承诺收益或保本”
    keywords: list[str] = Field(min_length=1)  # 召回候选句用的关键词
    examples: list[str] = Field(default_factory=list)  # 命中的典型说法
    not_redline: list[str] = Field(default_factory=list)  # 不算红线的说法
    correct: list[str] = Field(min_length=1)  # 正确说法，报告里附给候选人


class LexiconContent(RootModel[dict[str, RedlineEntry]]):
    pass


class LexiconIn(BaseModel):
    version: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    content: dict[str, RedlineEntry]


class LexiconOut(LexiconIn):
    id: uuid.UUID
    status: str
    created_at: datetime


def _out(x: RedlineLexiconVersion) -> LexiconOut:
    return LexiconOut(id=x.id, version=x.version, status=x.status, content=x.content, created_at=x.created_at)


@router.get("", response_model=list[LexiconOut])
def list_lexicons(db: Session = DB, _: User = Read) -> list[LexiconOut]:
    return [_out(x) for x in db.scalars(select(RedlineLexiconVersion).order_by(RedlineLexiconVersion.created_at.desc()))]


@router.post("", response_model=LexiconOut, status_code=201)
def create_lexicon(body: LexiconIn, request: Request, db: Session = DB, actor: User = Write) -> LexiconOut:
    ids = load(reference(db)).redlines.ids
    unknown = sorted(set(body.content) - set(ids))
    missing = sorted(set(ids) - set(body.content))
    if unknown or missing:
        raise HTTPException(422, f"红线编号须与评分标准一致（{', '.join(ids)}）；多出：{unknown or '无'}，缺少：{missing or '无'}")
    if db.scalar(select(RedlineLexiconVersion).where(RedlineLexiconVersion.version == body.version)):
        raise HTTPException(409, "版本已存在")
    x = RedlineLexiconVersion(version=body.version, status="draft", content={k: v.model_dump() for k, v in body.content.items()}, created_by=actor.id)
    db.add(x)
    db.flush()
    audit.record(db, request, actor_type="user", actor_id=str(actor.id), action="lexicon_create", target_type="redline_lexicon", target_id=str(x.id), version=x.version)
    db.commit()
    return _out(x)


@router.post("/{lid}/publish", response_model=LexiconOut)
def publish_lexicon(lid: uuid.UUID, request: Request, db: Session = DB, actor: User = Write) -> LexiconOut:
    x = db.get(RedlineLexiconVersion, lid)
    if x is None:
        raise HTTPException(404, "词表版本不存在")
    if x.status != "draft":
        raise HTTPException(409, "只有草稿可以发布")
    for old in db.scalars(select(RedlineLexiconVersion).where(RedlineLexiconVersion.status == "published")):
        old.status = "retired"
    x.status = "published"
    audit.record(db, request, actor_type="user", actor_id=str(actor.id), action="lexicon_publish", target_type="redline_lexicon", target_id=str(x.id), version=x.version)
    db.commit()
    return _out(x)
