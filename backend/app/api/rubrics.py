from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from scoring import config_hash, publish_blockers as _content_blockers, structure_problems


def publish_blockers(cfg) -> list[str]:
    """发布阻碍：待确认标记 + 结构检查（维度满分 100、达标线范围）。"""
    return _content_blockers(cfg) + structure_problems(cfg)

from ..models.entities import RubricVersion, User
from ..pipeline.detectors import unsupported_items
from ..security.rbac import Perm
from ..services import audit
from ..services.rubrics import checklist_max, load, parse_yaml, reference
from .deps import DB, require

router = APIRouter(prefix="/rubrics", tags=["评分标准"])
Read = Depends(require(Perm.config_read))
Write = Depends(require(Perm.config_write))


class RubricIn(BaseModel):
    yaml_text: str


class RubricSummary(BaseModel):
    id: uuid.UUID
    version: str
    status: str
    config_hash: str
    created_at: datetime
    published_at: datetime | None
    blocker_count: int
    processing_supported: bool
    processing_blockers: list[str]


class ItemRow(BaseModel):
    dimension: str
    id: str
    name: str
    type: str
    max: int


class RubricDetail(RubricSummary):
    yaml_text: str
    blockers: list[str]
    items: list[ItemRow]
    checklist_max: int | None  # 旧版 S2 的要点满分（C25）；新版按固定话术打分，为空
    thresholds: dict[str, int]


def _summary(rv: RubricVersion) -> RubricSummary:
    cfg = load(rv)
    bad = unsupported_items(cfg)
    return RubricSummary(id=rv.id, version=rv.version, status=rv.status, config_hash=rv.config_hash, created_at=rv.created_at,
                         published_at=rv.published_at, blocker_count=len(publish_blockers(cfg)),
                         processing_supported=not bad, processing_blockers=bad)


def _detail(rv: RubricVersion) -> RubricDetail:
    cfg = load(rv)
    return RubricDetail(
        **_summary(rv).model_dump(), yaml_text=rv.yaml_text, blockers=publish_blockers(cfg),
        items=[ItemRow(dimension=d.name, id=it.id, name=it.name, type=it.type, max=it.max) for d, it in cfg.items()],
        checklist_max=checklist_max(cfg), thresholds=cfg.thresholds,
    )


@router.get("", response_model=list[RubricSummary])
def list_rubrics(for_processing: bool = False, db: Session = DB, _: User = Read) -> list[RubricSummary]:
    rows = [_summary(rv) for rv in db.scalars(select(RubricVersion).order_by(RubricVersion.created_at.desc()))]
    return [r for r in rows if r.status != "retired" and r.processing_supported] if for_processing else rows


@router.post("", response_model=RubricDetail, status_code=201)
def import_rubric(body: RubricIn, request: Request, db: Session = DB, actor: User = Write) -> RubricDetail:
    cfg = parse_yaml(body.yaml_text)
    if db.scalar(select(RubricVersion).where(RubricVersion.version == cfg.version)):
        raise HTTPException(409, f"版本 {cfg.version} 已存在；修改规则请在 YAML 中换一个新的 version")
    rv = RubricVersion(version=cfg.version, status="draft", yaml_text=body.yaml_text, config_hash=config_hash(cfg), created_by=actor.id)
    db.add(rv)
    db.flush()
    audit.record(db, request, actor_type="user", actor_id=str(actor.id), action="rubric_import", target_type="rubric_version",
                 target_id=str(rv.id), version=rv.version, config_hash=rv.config_hash)
    db.commit()
    return _detail(rv)


@router.get("/reference", response_model=RubricDetail)
def get_reference(for_processing: bool = False, db: Session = DB, _: User = Read) -> RubricDetail:
    """默认供历史内容校验；新评分须指定 for_processing，排除旧证据协议。"""
    return _detail(reference(db, for_processing=for_processing))


def _get(db: Session, rid: uuid.UUID) -> RubricVersion:
    rv = db.get(RubricVersion, rid)
    if rv is None:
        raise HTTPException(404, "评分标准版本不存在")
    return rv


@router.get("/{rid}", response_model=RubricDetail)
def get_rubric(rid: uuid.UUID, db: Session = DB, _: User = Read) -> RubricDetail:
    return _detail(_get(db, rid))


@router.post("/{rid}/publish", response_model=RubricDetail)
def publish(rid: uuid.UUID, request: Request, db: Session = DB, actor: User = Write) -> RubricDetail:
    rv = _get(db, rid)
    if rv.status != "draft":
        raise HTTPException(409, f"只有草稿可以发布，当前状态为 {rv.status}")
    blockers = publish_blockers(load(rv))
    if blockers:
        raise HTTPException(409, {"message": "有待确认规则或测试占位值，不能发布", "blockers": blockers})
    rv.status, rv.published_at = "published", datetime.now(timezone.utc)
    audit.record(db, request, actor_type="user", actor_id=str(actor.id), action="rubric_publish", target_type="rubric_version",
                 target_id=str(rv.id), version=rv.version)
    db.commit()
    return _detail(rv)


@router.post("/{rid}/retire", response_model=RubricDetail)
def retire(rid: uuid.UUID, request: Request, db: Session = DB, actor: User = Write) -> RubricDetail:
    rv = _get(db, rid)
    if rv.status == "retired":
        raise HTTPException(409, "已经停用")
    rv.status = "retired"
    audit.record(db, request, actor_type="user", actor_id=str(actor.id), action="rubric_retire", target_type="rubric_version", target_id=str(rv.id))
    db.commit()
    return _detail(rv)
