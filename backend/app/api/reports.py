"""报告（M5）：列表与排名（按日期范围，C32）、详情（含逐句评分）、PDF、Excel、按新版重算、修订历史。
HR 和管理员看全部（C19）；新主播只看关联到本人账号的记录（C31）。所有查看和导出写审计。"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from scoring import RankEntry, rank

from ..models.entities import Candidate, Recording, Report, RubricVersion, User
from ..security.rbac import Perm, allowed
from ..services import audit
from ..services.export import PdfError, html_to_pdf, ranking_xlsx, report_html
from ..services.report_view import detail, score_result
from ..services.report_creation import uses_mock
from ..providers.registry import allow_mock_scoring
from ..services.rescore import rescore
from .candidates import name_of
from .deps import DB, current_user, require

router = APIRouter(prefix="/reports", tags=["报告"])
CN = timezone(timedelta(hours=8))  # 按北京时间的日期筛选


class ReportRow(BaseModel):
    id: uuid.UUID
    rank: int
    recording_id: uuid.UUID
    candidate_name: str
    submitted_at: datetime | None
    audience: str
    mode: str
    label: str
    reason: str
    total_grade: int
    threshold: int
    dimension_scores: dict[str, int]
    dimension_grades: dict[str, int]
    critical: bool
    informal: bool
    low_confidence_count: int
    revision: int


class RescoreIn(BaseModel):
    rubric_version_id: uuid.UUID


def _viewer(user: User = Depends(current_user)) -> User:
    if not (allowed(user.role, Perm.report_read_all) or allowed(user.role, Perm.report_read_own)):
        raise HTTPException(403, "没有权限")
    return user


def _can_see(db: Session, user: User, rep: Report) -> bool:
    if allowed(user.role, Perm.report_read_all):
        return True
    rec = db.get(Recording, rep.recording_id)
    return db.get(Candidate, rec.candidate_id).linked_user_id == user.id


def _get(db: Session, rid: uuid.UUID, user: User) -> Report:
    rep = db.get(Report, rid)
    if rep is None or not _can_see(db, user, rep):
        raise HTTPException(404, "报告不存在")  # 对无权查看的人不暴露是否存在
    return rep


def _rows(db: Session, user: User, date_from: date | None, date_to: date | None, audience: str | None,
          mode: str | None = None) -> list[tuple[Report, Recording, dict]]:
    q = select(Report, Recording).join(Recording, Report.recording_id == Recording.id).where(Report.superseded_at.is_(None))
    if date_from:
        q = q.where(Recording.submitted_at >= datetime.combine(date_from, time.min, CN))
    if date_to:
        q = q.where(Recording.submitted_at < datetime.combine(date_to + timedelta(days=1), time.min, CN))
    if audience:
        q = q.where(Recording.audience == audience)
    if mode:  # 试镜和录播取证方式不同，分数不混在一起排名（C37）
        q = q.where(Recording.mode == mode)
    if not allowed(user.role, Perm.report_read_all):
        q = q.join(Candidate, Recording.candidate_id == Candidate.id).where(Candidate.linked_user_id == user.id)
    out = []
    for rep, rec in db.execute(q).all():
        if uses_mock(rep.model_manifest) and not allow_mock_scoring():
            continue  # 历史模拟报告仍可直接查看，默认不进入真实排名/导出。
        out.append((rep, rec, score_result(db, rep.display_run_id, rep.rubric_version_id)))
    return out


def _ranked(db: Session, user: User, date_from, date_to, label, audience, sort, mode=None) -> list[ReportRow]:
    data = _rows(db, user, date_from, date_to, audience, mode)
    by_id: dict[str, tuple[Report, Recording, dict]] = {str(rep.id): (rep, rec, res) for rep, rec, res in data}
    entries = []
    for rep, rec, res in data:
        rnd = rep.verdict["rounds"][rep.verdict["display_round"] - 1]
        entries.append(RankEntry(report_id=str(rep.id), label=rep.label, total_grade=rnd["total_grade"], dimension_scores=rnd["dimension_scores"],
                                 redline_hit=rep.redline_hit, submitted_at=rec.submitted_at or rep.created_at))
    if sort not in ("default", "P", "S", "L", "O"):
        raise HTTPException(422, "排序方式应为 default 或维度编号 P / S / L / O")
    rows = []
    for i, e in enumerate(rank(entries, by=sort), start=1):
        rep, rec, res = by_id[e.report_id]
        rnd = rep.verdict["rounds"][rep.verdict["display_round"] - 1]
        if label and rep.label != label:
            continue
        rows.append(ReportRow(
            id=rep.id, rank=i, recording_id=rec.id, candidate_name=name_of(db.get(Candidate, rec.candidate_id)), submitted_at=rec.submitted_at,
            audience=rec.audience, mode=rec.mode, label=rep.label, reason=rep.verdict["reason"], total_grade=rnd["total_grade"], threshold=res["threshold"],
            dimension_scores=rnd["dimension_scores"], dimension_grades=rnd["dimension_grades"], critical=rep.critical, informal=rep.informal,
            low_confidence_count=len(res["low_confidence_items"]), revision=rep.revision,
        ))
    return rows


@router.get("", response_model=list[ReportRow])
def list_reports(
    request: Request,
    date_from: date | None = None,
    date_to: date | None = None,
    label: str | None = Query(None, pattern=r"^(recommend|pending|not_recommend)$"),
    audience: str | None = None,
    mode: str | None = Query(None, pattern=r"^(audition|live)$"),
    sort: str = "default",
    db: Session = DB,
    user: User = Depends(_viewer),
) -> list[ReportRow]:
    """排名口径（C9、I4）：同一日期范围内的报告一起排名，筛选标签不改变名次。
    mode 给出时只在试镜或录播内部排名（C37）。"""
    rows = _ranked(db, user, date_from, date_to, label, audience, sort, mode)
    audit.record(db, request, actor_type="user", actor_id=str(user.id), action="report_list", target_type="report", target_id="*",
                 date_from=str(date_from), date_to=str(date_to), label=label, sort=sort, count=len(rows))
    db.commit()
    return rows


@router.get("/export.xlsx")
def export_xlsx(
    request: Request,
    date_from: date | None = None,
    date_to: date | None = None,
    label: str | None = Query(None, pattern=r"^(recommend|pending|not_recommend)$"),
    audience: str | None = None,
    mode: str | None = Query(None, pattern=r"^(audition|live)$"),
    sort: str = "default",
    db: Session = DB,
    user: User = Depends(require(Perm.report_read_all)),
) -> Response:
    rows = _ranked(db, user, date_from, date_to, label, audience, sort, mode)
    items = {str(r.id): score_result(db, db.get(Report, r.id).display_run_id, db.get(Report, r.id).rubric_version_id)["items"] for r in rows}
    desc = f"{date_from or '最早'} 至 {date_to or '今天'}"
    data = ranking_xlsx([r.model_dump() for r in rows], {k: v for k, v in items.items()}, desc)
    audit.record(db, request, actor_type="user", actor_id=str(user.id), action="report_export_excel", target_type="report", target_id="*",
                 date_from=str(date_from), date_to=str(date_to), label=label, count=len(rows))
    db.commit()
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename=audition-ranking.xlsx", "Cache-Control": "no-store"})


@router.get("/{rid}")
def get_report(rid: uuid.UUID, request: Request, db: Session = DB, user: User = Depends(_viewer)) -> dict[str, Any]:
    rep = _get(db, rid, user)
    out = detail(db, rep)
    audit.record(db, request, actor_type="user", actor_id=str(user.id), action="report_view", target_type="report", target_id=str(rid))
    db.commit()
    return out


@router.get("/{rid}/revisions")
def revisions(rid: uuid.UUID, db: Session = DB, user: User = Depends(_viewer)) -> list[dict]:
    rep = _get(db, rid, user)
    rows = db.scalars(select(Report).where(Report.recording_id == rep.recording_id).order_by(Report.revision.desc()))
    return [{"id": str(r.id), "revision": r.revision, "label": r.label, "rubric_version": db.get(RubricVersion, r.rubric_version_id).version,
             "created_at": r.created_at, "superseded_at": r.superseded_at} for r in rows]


@router.get("/{rid}/pdf")
def export_pdf(rid: uuid.UUID, request: Request, db: Session = DB, user: User = Depends(_viewer)) -> Response:
    rep = _get(db, rid, user)
    try:
        pdf = html_to_pdf(report_html(detail(db, rep)))
    except PdfError as exc:
        raise HTTPException(503, str(exc)) from exc
    audit.record(db, request, actor_type="user", actor_id=str(user.id), action="report_export_pdf", target_type="report", target_id=str(rid))
    db.commit()
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename=report-{str(rid)[:8]}.pdf", "Cache-Control": "no-store"})


@router.post("/{rid}/rescore")
def rescore_report(rid: uuid.UUID, body: RescoreIn, request: Request, db: Session = DB,
                   user: User = Depends(require(Perm.config_write))) -> dict[str, Any]:
    rep = _get(db, rid, user)
    if rep.superseded_at is not None:
        raise HTTPException(409, "只能对最新修订重算")
    rv = db.get(RubricVersion, body.rubric_version_id)
    if rv is None:
        raise HTTPException(404, "评分标准版本不存在")
    new = rescore(db, rep, rv)
    audit.record(db, request, actor_type="user", actor_id=str(user.id), action="report_rescore", target_type="report", target_id=str(new.id),
                 previous=str(rep.id), rubric_version=rv.version, label_before=rep.label, label_after=new.label)
    db.commit()
    return detail(db, new)
