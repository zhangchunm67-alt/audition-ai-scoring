"""校准（M6-1）：金标准集、抽样、分配校准员、背对背打分、分歧裁决、与 AI 对比。
校准员只看分给自己的样本，提交前看不到 AI 结果和其他校准员的打分（PRD 第 5 节“权限”）。"""
from __future__ import annotations

import random
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from scoring import parse_config
from scoring.aggregate import calibration_config

from ..models.entities import (
    AuditionSheet, CalibrationAssignment, GoldSample, GoldSet, MediaAsset, ProductCard, Recording, RubricVersion, User,
)
from ..pipeline.runner import detector_config
from ..security.rbac import Perm
from ..services import audit
from ..services.calibration import ai_report_id, compare, consolidate, metrics, normalize_evidence, score_assignment
from .candidates import get_candidate, name_of
from .deps import DB, require

router = APIRouter(prefix="/calibration", tags=["校准"])
Manage = Depends(require(Perm.calibration_manage))
Score = Depends(require(Perm.calibration_score))
CN = timezone(timedelta(hours=8))
_rng = random.SystemRandom()


def _log(db, request, actor: User, action: str, ttype: str, tid, **kw) -> None:
    audit.record(db, request, actor_type="user", actor_id=str(actor.id), action=action, target_type=ttype, target_id=str(tid), **kw)


class SetIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    purpose: str = Field(pattern=r"^(prelaunch|monthly_sample)$")
    rubric_version_id: uuid.UUID
    note: str | None = None


class AddIn(BaseModel):
    recording_ids: list[uuid.UUID] = Field(min_length=1)


class SampleIn(BaseModel):
    month: str = Field(pattern=r"^\d{4}-\d{2}$")  # 按提交月份（北京时间）随机抽
    count: int = Field(ge=1, le=100)


class AssignIn(BaseModel):
    calibrator_ids: list[uuid.UUID] = Field(min_length=2, max_length=3)  # PRD：2–3 位校准员


class EvidenceIn(BaseModel):
    evidence: list[dict]
    note: str | None = None


class AdjudicateIn(BaseModel):
    item_id: str
    score: float = Field(ge=0)
    note: str = Field(min_length=1)


def _set(db: Session, sid: uuid.UUID) -> GoldSet:
    gs = db.get(GoldSet, sid)
    if gs is None:
        raise HTTPException(404, "金标准集不存在")
    return gs


def _samples(db: Session, gs: GoldSet) -> list[GoldSample]:
    return list(db.scalars(select(GoldSample).where(GoldSample.gold_set_id == gs.id)))


def _set_out(db: Session, gs: GoldSet, with_metrics: bool = False) -> dict:
    samples = _samples(db, gs)
    out = {"id": str(gs.id), "name": gs.name, "purpose": gs.purpose, "note": gs.note, "created_at": gs.created_at,
           "rubric_version": db.get(RubricVersion, gs.rubric_version_id).version, "samples": len(samples),
           "final": sum(1 for s in samples if s.status == "final"), "needs_adjudication": sum(1 for s in samples if s.status == "needs_adjudication")}
    if with_metrics:
        out["metrics"] = metrics(db, samples)
        out["sample_rows"] = [_sample_row(db, s) for s in samples]
    return out


def _sample_row(db: Session, s: GoldSample) -> dict:
    rec = db.get(Recording, s.recording_id)
    subs = db.scalars(select(CalibrationAssignment).where(CalibrationAssignment.sample_id == s.id)).all()
    return {"id": str(s.id), "recording_id": str(rec.id), "candidate_name": name_of(get_candidate(db, rec.candidate_id)),
            "submitted_at": rec.submitted_at, "status": s.status, "flagged_items": s.flagged_items,
            "assignments": [{"calibrator": db.get(User, a.calibrator_id).display_name, "status": a.status} for a in subs],
            "gold_total": s.gold["total_grade"] if s.gold else None}


# ───────────── 管理员 ─────────────


@router.get("/sets")
def list_sets(db: Session = DB, _: User = Manage) -> list[dict]:
    return [_set_out(db, gs) for gs in db.scalars(select(GoldSet).order_by(GoldSet.created_at.desc()))]


@router.post("/sets", status_code=201)
def create_set(body: SetIn, request: Request, db: Session = DB, actor: User = Manage) -> dict:
    if db.get(RubricVersion, body.rubric_version_id) is None:
        raise HTTPException(404, "评分标准版本不存在")
    gs = GoldSet(name=body.name, purpose=body.purpose, rubric_version_id=body.rubric_version_id, note=body.note, created_by=actor.id)
    db.add(gs)
    db.flush()
    _log(db, request, actor, "gold_set_create", "gold_set", gs.id, purpose=gs.purpose)
    db.commit()
    return _set_out(db, gs)


@router.get("/sets/{sid}")
def get_set(sid: uuid.UUID, db: Session = DB, _: User = Manage) -> dict:
    return _set_out(db, _set(db, sid), with_metrics=True)


def _has_video(db: Session, rid: uuid.UUID) -> bool:
    return db.scalar(select(MediaAsset.id).where(MediaAsset.recording_id == rid, MediaAsset.kind == "raw_video",
                                                 MediaAsset.deleted_at.is_(None)).limit(1)) is not None


def _add(db: Session, gs: GoldSet, rec_ids: list[uuid.UUID]) -> int:
    have = {s.recording_id for s in _samples(db, gs)}
    n = 0
    for rid in rec_ids:
        rec = db.get(Recording, rid)
        # 上线前校准时 AI 往往还出不了报告：标好分段、视频还在的录像就能加入，校准员照样背对背打分；
        # 对比时 AI 没有结果的记为“AI 不完整”
        if rec is None or rec.status in ("uploading", "cancelled") or not rec.segments:
            raise HTTPException(422, "只能加入已上传并标好分段的录像")
        if not _has_video(db, rid):
            raise HTTPException(422, "这条录像的视频已到期删除，校准员没法看，不能加入")
        if rid in have:
            continue
        db.add(GoldSample(gold_set_id=gs.id, recording_id=rid))
        n += 1
    return n


@router.post("/sets/{sid}/samples")
def add_samples(sid: uuid.UUID, body: AddIn, request: Request, db: Session = DB, actor: User = Manage) -> dict:
    gs = _set(db, sid)
    n = _add(db, gs, body.recording_ids)
    _log(db, request, actor, "gold_samples_add", "gold_set", gs.id, added=n)
    db.commit()
    return _set_out(db, gs, with_metrics=True)


@router.post("/sets/{sid}/sample-month")
def sample_month(sid: uuid.UUID, body: SampleIn, request: Request, db: Session = DB, actor: User = Manage) -> dict:
    """每月抽检（PRD：每月抽 10–20 条）：从该月提交且已出报告的录像里随机抽，已在本集里的不重复抽。"""
    gs = _set(db, sid)
    y, m = map(int, body.month.split("-"))
    start = datetime.combine(date(y, m, 1), time.min, CN)
    end = datetime.combine(date(y + (m == 12), m % 12 + 1, 1), time.min, CN)
    have = {s.recording_id for s in _samples(db, gs)}
    pool = [r.id for r in db.scalars(select(Recording).where(Recording.status == "done", Recording.submitted_at >= start, Recording.submitted_at < end))
            if r.id not in have and _has_video(db, r.id)]  # 视频已到期删除的不抽（校准员要看视频）
    picked = _rng.sample(pool, min(body.count, len(pool)))
    n = _add(db, gs, picked)
    _log(db, request, actor, "gold_samples_draw", "gold_set", gs.id, month=body.month, requested=body.count, added=n, pool=len(pool))
    db.commit()
    return {**_set_out(db, gs, with_metrics=True), "drawn": n, "pool": len(pool)}


@router.post("/sets/{sid}/assign")
def assign(sid: uuid.UUID, body: AssignIn, request: Request, db: Session = DB, actor: User = Manage) -> dict:
    gs = _set(db, sid)
    if len(set(body.calibrator_ids)) != len(body.calibrator_ids):
        raise HTTPException(422, "校准员重复")
    for uid in body.calibrator_ids:
        u = db.get(User, uid)
        if u is None or u.role != "calibrator" or not u.is_active:
            raise HTTPException(422, "只能分配启用中的“校准员”账号")
    n = 0
    for s in _samples(db, gs):
        have = {a.calibrator_id for a in db.scalars(select(CalibrationAssignment).where(CalibrationAssignment.sample_id == s.id))}
        for uid in body.calibrator_ids:
            if uid not in have:
                db.add(CalibrationAssignment(sample_id=s.id, calibrator_id=uid, evidence=[]))
                n += 1
        if s.status == "final" and n:
            s.status = "collecting"  # 新增校准员后需重新汇总
    _log(db, request, actor, "gold_assign", "gold_set", gs.id, calibrators=[str(x) for x in body.calibrator_ids], created=n)
    db.commit()
    return _set_out(db, gs, with_metrics=True)


@router.get("/samples/{sample_id}")
def sample_detail(sample_id: uuid.UUID, db: Session = DB, _: User = Manage) -> dict:
    s = db.get(GoldSample, sample_id)
    if s is None:
        raise HTTPException(404, "样本不存在")
    subs = db.scalars(select(CalibrationAssignment).where(CalibrationAssignment.sample_id == s.id)).all()
    return {**_sample_row(db, s), "adjudication": s.adjudication, "gold": s.gold, "ai_report_id": ai_report_id(db, s.recording_id),
            "calibrators": [{"name": db.get(User, a.calibrator_id).display_name, "status": a.status, "items": (a.result or {}).get("items"),
                             "total_grade": (a.result or {}).get("total_grade"), "note": a.note} for a in subs],
            "comparison": compare(db, s)}


@router.post("/samples/{sample_id}/adjudicate")
def adjudicate(sample_id: uuid.UUID, body: AdjudicateIn, request: Request, db: Session = DB, actor: User = Manage) -> dict:
    """分歧条目开会裁决后，录入裁决分数和理由；全部裁决后金标准自动定稿。"""
    s = db.get(GoldSample, sample_id)
    if s is None:
        raise HTTPException(404, "样本不存在")
    if body.item_id not in s.flagged_items:
        raise HTTPException(422, "该条目没有分歧，不需要裁决")
    rv = db.get(RubricVersion, db.get(GoldSet, s.gold_set_id).rubric_version_id)
    mx = next(it.max for _, it in parse_config(yaml.safe_load(rv.yaml_text)).items() if it.id == body.item_id)
    if body.score > mx:
        raise HTTPException(422, f"分数不能超过满分 {mx}")
    s.adjudication = {**s.adjudication, body.item_id: {"score": body.score, "note": body.note, "by": str(actor.id),
                                                       "at": datetime.now(timezone.utc).isoformat()}}
    _log(db, request, actor, "gold_adjudicate", "gold_sample", s.id, item_id=body.item_id, score=body.score)
    consolidate(db, s, actor_id=str(actor.id))
    db.commit()
    return sample_detail(sample_id, db, actor)


# ───────────── 校准员 ─────────────


def _assignment(db: Session, aid: uuid.UUID, user: User) -> CalibrationAssignment:
    a = db.get(CalibrationAssignment, aid)
    if a is None or a.calibrator_id != user.id:
        raise HTTPException(404, "任务不存在")  # 只能看分给自己的
    return a


@router.get("/my-tasks")
def my_tasks(db: Session = DB, user: User = Score) -> list[dict]:
    out = []
    for a in db.scalars(select(CalibrationAssignment).where(CalibrationAssignment.calibrator_id == user.id).order_by(CalibrationAssignment.created_at)):
        s = db.get(GoldSample, a.sample_id)
        gs = db.get(GoldSet, s.gold_set_id)
        rec = db.get(Recording, s.recording_id)
        out.append({"id": str(a.id), "set_name": gs.name, "status": a.status, "submitted_at": a.submitted_at,
                    "sheet_code": db.get(AuditionSheet, rec.sheet_id).code, "evidence_count": len(a.evidence)})
    return out


@router.get("/assignments/{aid}")
def task_detail(aid: uuid.UUID, request: Request, db: Session = DB, user: User = Score) -> dict[str, Any]:
    """打分所需的全部材料：视频、分段、题单、卖点卡、各条目的打分方式。不含 AI 结果和其他人的打分。"""
    a = _assignment(db, aid, user)
    s = db.get(GoldSample, a.sample_id)
    gs = db.get(GoldSet, s.gold_set_id)
    rec = db.get(Recording, s.recording_id)
    sheet = db.get(AuditionSheet, rec.sheet_id)
    card = db.get(ProductCard, sheet.product_card_id).content
    ccfg = calibration_config(parse_config(yaml.safe_load(db.get(RubricVersion, gs.rubric_version_id).yaml_text)))
    _, dcfg = detector_config(db)
    video = db.scalar(select(MediaAsset).where(MediaAsset.recording_id == rec.id, MediaAsset.kind == "raw_video", MediaAsset.deleted_at.is_(None)))
    _log(db, request, user, "calibration_task_view", "calibration_assignment", a.id)
    db.commit()
    return {
        "id": str(a.id), "status": a.status, "evidence": a.evidence, "note": a.note, "set_name": gs.name,
        "video_asset_id": str(video.id) if video else None, "segments": rec.segments, "props_available": rec.props_available,
        "mode": rec.mode, "exclusions": rec.exclusions or [],
        "audience": rec.audience,
        "objections": [{"objection_id": o["objection_id"], "video_ms": o["video_ms"],
                        "text": next(x["text"] for x in sheet.objections if x["objection_id"] == o["objection_id"])} for o in rec.objection_times],
        "questions": sheet.questions,
        "card": {"checklist": [{"id": p["id"], "name": p["name"]} for p in card.get("checklist", [])],
                 "fixed_script": card.get("fixed_script"),
                 "glossary": [g["term"] for g in card.get("glossary", [])], "targeted_points": card.get("targeted_points", [])},
        "p2_categories": [c.label for c in dcfg.p2.categories],
        "dimensions": [{"id": d.id, "name": d.name, "items": [it.model_dump(mode="json") for it in d.items]} for d in ccfg.dimensions],
    }


@router.put("/assignments/{aid}")
def save_task(aid: uuid.UUID, body: EvidenceIn, db: Session = DB, user: User = Score) -> dict:
    a = _assignment(db, aid, user)
    if a.status == "submitted":
        raise HTTPException(409, "已提交，不能再改")
    s = db.get(GoldSample, a.sample_id)
    rv = db.get(RubricVersion, db.get(GoldSet, s.gold_set_id).rubric_version_id)
    ids = {it.id for _, it in parse_config(yaml.safe_load(rv.yaml_text)).items()}
    a.evidence, a.note = normalize_evidence(body.evidence, ids), body.note
    db.commit()
    return {"id": str(a.id), "status": a.status, "evidence_count": len(a.evidence)}


@router.post("/assignments/{aid}/submit")
def submit_task(aid: uuid.UUID, request: Request, db: Session = DB, user: User = Score) -> dict:
    a = _assignment(db, aid, user)
    if a.status == "submitted":
        raise HTTPException(409, "已提交")
    a.result = score_assignment(db, a)  # 缺条目会在这里拒绝
    a.status, a.submitted_at = "submitted", datetime.now(timezone.utc)
    _log(db, request, user, "calibration_submit", "calibration_assignment", a.id, total_grade=a.result["total_grade"])
    consolidate(db, db.get(GoldSample, a.sample_id))
    db.commit()
    return {"id": str(a.id), "status": a.status, "total_grade": a.result["total_grade"]}
