"""试镜题单（C29）：按抽题规则抽好异议、知识题和朗读稿，候选人按题单在系统外录制。"""
from __future__ import annotations

import base64
import os
import random
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from ..models.entities import AuditionSheet, DrawRule, Objection, Product, ProductCard, Question, ReadingScript, RedlineLexiconVersion, RubricVersion, User
from ..security.rbac import Perm
from ..services import audit
from ..services.rubrics import checklist_max, load, question_counts
from .deps import DB, require
from .products import check_card_total

router = APIRouter(prefix="/sheets", tags=["试镜题单"])
Read = Depends(require(Perm.sheet_read))
Write = Depends(require(Perm.sheet_write))
RECORDING_RULES_VERSION = "rules-v1"
_rng = random.SystemRandom()


class SheetIn(BaseModel):
    product_id: uuid.UUID
    rubric_version_id: uuid.UUID
    note: str | None = None


class SheetObjection(BaseModel):
    objection_id: uuid.UUID
    text: str
    at_ms: int


class SheetQuestion(BaseModel):
    question_id: uuid.UUID
    text: str


class SheetOut(BaseModel):
    id: uuid.UUID
    code: str
    status: str
    product_id: uuid.UUID
    product_name: str
    product_card_id: uuid.UUID
    product_card_version: int
    rubric_version_id: uuid.UUID
    rubric_version: str
    redline_lexicon_version_id: uuid.UUID | None
    redline_lexicon_version: str | None
    uses_draft_config: bool
    draw_rule: dict
    objections: list[SheetObjection]
    questions: list[SheetQuestion]
    reading_script_id: uuid.UUID
    reading_text: str
    recording_rules_version: str
    note: str | None
    created_at: datetime


def _out(db: Session, s: AuditionSheet) -> SheetOut:
    return SheetOut(
        id=s.id, code=s.code, status=s.status, product_id=s.product_id, product_name=db.get(Product, s.product_id).name,
        product_card_id=s.product_card_id, product_card_version=db.get(ProductCard, s.product_card_id).version,
        rubric_version_id=s.rubric_version_id, rubric_version=db.get(RubricVersion, s.rubric_version_id).version,
        redline_lexicon_version_id=s.redline_lexicon_version_id,
        redline_lexicon_version=db.get(RedlineLexiconVersion, s.redline_lexicon_version_id).version if s.redline_lexicon_version_id else None,
        uses_draft_config=s.uses_draft_config, draw_rule=s.draw_rule_snapshot, objections=s.objections, questions=s.questions,
        reading_script_id=s.reading_script_id, reading_text=s.reading_text, recording_rules_version=s.recording_rules_version,
        note=s.note, created_at=s.created_at,
    )


def _code() -> str:
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"TS{day}-{base64.b32encode(os.urandom(5)).decode()[:6]}"


@router.get("", response_model=list[SheetOut])
def list_sheets(status: str | None = None, db: Session = DB, _: User = Read) -> list[SheetOut]:
    q = select(AuditionSheet).order_by(AuditionSheet.created_at.desc())
    if status:
        q = q.where(AuditionSheet.status == status)
    return [_out(db, s) for s in db.scalars(q.limit(500))]


@router.post("", response_model=SheetOut, status_code=201)
def create_sheet(body: SheetIn, request: Request, db: Session = DB, actor: User = Write) -> SheetOut:
    product = db.get(Product, body.product_id)
    if product is None:
        raise HTTPException(404, "产品不存在")
    rv = db.get(RubricVersion, body.rubric_version_id)
    if rv is None or rv.status == "retired":
        raise HTTPException(422, "评分标准版本不存在或已停用")
    card = db.scalar(select(ProductCard).where(ProductCard.product_id == product.id, ProductCard.status == "published"))
    if card is None:
        raise HTTPException(422, "该产品还没有已发布的卖点卡")
    cfg = load(rv)
    lex = None
    if cfg.redlines.enabled:  # 试镜关闭红线（C33）时不需要词表
        lex = db.scalar(
            select(RedlineLexiconVersion).where(RedlineLexiconVersion.status != "retired")
            .order_by(case((RedlineLexiconVersion.status == "published", 0), else_=1), RedlineLexiconVersion.created_at.desc()).limit(1)
        )
        if lex is None:
            raise HTTPException(422, "该评分标准启用了红线，但还没有红线词表")
    rule = db.scalar(select(DrawRule).where(DrawRule.product_id == product.id).order_by(DrawRule.created_at.desc()).limit(1))
    if rule is None:
        raise HTTPException(422, "该产品还没有抽题规则")

    check_card_total(card.content, checklist_max(cfg))  # C25：按所选评分标准再校验一次
    counts = question_counts(cfg)
    if counts.get("S3") != rule.objection_count or counts.get("O5") != rule.question_count:
        raise HTTPException(422, f"抽题规则（异议 {rule.objection_count} 条、知识题 {rule.question_count} 道）与评分标准（S3 {counts.get('S3')} 条、O5 {counts.get('O5')} 道）不一致")

    objs = list(db.scalars(select(Objection).where(Objection.product_id == product.id, Objection.active)))
    qs = list(db.scalars(select(Question).where(Question.product_id == product.id, Question.active)))
    scripts = list(db.scalars(select(ReadingScript).where(ReadingScript.active)))
    if len(objs) < rule.objection_count:
        raise HTTPException(422, f"可用异议只有 {len(objs)} 条，至少需要 {rule.objection_count} 条")
    if len(qs) < rule.question_count:
        raise HTTPException(422, f"可用知识题只有 {len(qs)} 道，至少需要 {rule.question_count} 道")
    if not scripts:
        raise HTTPException(422, "没有可用的朗读稿")
    drawn_o = _rng.sample(objs, rule.objection_count)
    drawn_q = _rng.sample(qs, rule.question_count)
    script = _rng.choice(scripts)

    s = AuditionSheet(
        code=_code(), product_id=product.id, product_card_id=card.id, rubric_version_id=rv.id, redline_lexicon_version_id=lex.id if lex else None,
        draw_rule_snapshot={k: getattr(rule, k) for k in ("objection_count", "question_count", "objection_times_ms", "prep_seconds", "question_seconds", "main_seconds")},
        objections=[{"objection_id": str(o.id), "text": o.text, "at_ms": t} for o, t in zip(drawn_o, rule.objection_times_ms)],
        questions=[{"question_id": str(q.id), "text": q.text} for q in drawn_q],
        reading_script_id=script.id, reading_text=script.text, recording_rules_version=RECORDING_RULES_VERSION,
        uses_draft_config=rv.status != "published" or (lex is not None and lex.status != "published"), note=body.note, created_by=actor.id,
    )
    db.add(s)
    db.flush()
    audit.record(db, request, actor_type="user", actor_id=str(actor.id), action="sheet_create", target_type="audition_sheet", target_id=str(s.id),
                 code=s.code, rubric_version=rv.version, uses_draft_config=s.uses_draft_config, redlines_enabled=cfg.redlines.enabled)
    db.commit()
    return _out(db, s)


@router.get("/{sid}", response_model=SheetOut)
def get_sheet(sid: uuid.UUID, db: Session = DB, _: User = Read) -> SheetOut:
    s = db.get(AuditionSheet, sid)
    if s is None:
        raise HTTPException(404, "题单不存在")
    return _out(db, s)


@router.post("/{sid}/void", response_model=SheetOut)
def void_sheet(sid: uuid.UUID, request: Request, db: Session = DB, actor: User = Write) -> SheetOut:
    s = db.get(AuditionSheet, sid)
    if s is None:
        raise HTTPException(404, "题单不存在")
    if s.status != "issued":
        raise HTTPException(409, "只有未使用的题单可以作废")
    s.status = "void"
    audit.record(db, request, actor_type="user", actor_id=str(actor.id), action="sheet_void", target_type="audition_sheet", target_id=str(s.id))
    db.commit()
    return _out(db, s)
