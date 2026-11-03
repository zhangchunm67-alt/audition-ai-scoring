"""看板（M6-2、M6-3）：一致率（按金标准集或提交日期范围）、效率（处理时长、失败率、各条目低置信比例）。"""
from __future__ import annotations

import statistics
import uuid
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.entities import GoldSample, GoldSet, PipelineRun, Recording, Report, User
from ..security.rbac import Perm
from ..services import audit
from ..services.calibration import metrics
from ..services.report_view import score_result
from .deps import DB, require

router = APIRouter(prefix="/dashboard", tags=["看板"])
Read = Depends(require(Perm.dashboard_read))
CN = timezone(timedelta(hours=8))


def _range(q, col, date_from: date | None, date_to: date | None):
    if date_from:
        q = q.where(col >= datetime.combine(date_from, time.min, CN))
    if date_to:
        q = q.where(col < datetime.combine(date_to + timedelta(days=1), time.min, CN))
    return q


@router.get("/agreement")
def agreement(request: Request, set_id: uuid.UUID | None = None, date_from: date | None = None, date_to: date | None = None,
              db: Session = DB, user: User = Read) -> dict:
    """AI 与金标准（含月度抽样）的一致率；不指定金标准集时，按录像提交日期汇总所有金标准样本。"""
    q = select(GoldSample).join(Recording, GoldSample.recording_id == Recording.id)
    if set_id:
        q = q.where(GoldSample.gold_set_id == set_id)
    q = _range(q, Recording.submitted_at, date_from, date_to)
    samples = list(db.scalars(q))
    sets = []
    for gs in db.scalars(select(GoldSet).order_by(GoldSet.created_at.desc())):
        ss = [s for s in samples if s.gold_set_id == gs.id]
        if ss:
            m = metrics(db, ss)
            sets.append({"id": str(gs.id), "name": gs.name, "purpose": gs.purpose, "final": m["final"], "samples": m["samples"],
                         "dimension_agreement": m["dimension_agreement"], "conclusion_agreement": m["conclusion_agreement"]})
    audit.record(db, request, actor_type="user", actor_id=str(user.id), action="dashboard_view", target_type="dashboard", target_id="agreement")
    db.commit()
    return {"overall": metrics(db, samples), "sets": sets}


def _pct(vals: list[float], p: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    return round(s[min(len(s) - 1, max(0, int(round(p * len(s))) - 1))], 1)


@router.get("/efficiency")
def efficiency(request: Request, date_from: date | None = None, date_to: date | None = None, db: Session = DB, user: User = Read) -> dict:
    """处理时长（提交 → 出报告，分钟）、失败率、重试、临界比例、各条目低置信比例；按日统计提交量。"""
    q = _range(select(Recording).where(Recording.submitted_at.is_not(None)), Recording.submitted_at, date_from, date_to)
    recs = list(db.scalars(q))
    done = [r for r in recs if r.status == "done" and r.finished_at]
    failed = [r for r in recs if r.status == "failed"]
    mins = [(r.finished_at - r.submitted_at).total_seconds() / 60 for r in done]
    retries = critical = informal = 0
    low: dict[str, list[int]] = {}
    for r in done:
        retries += sum(x.retry_count for x in db.scalars(select(PipelineRun).where(PipelineRun.recording_id == r.id)))
        rep = db.scalar(select(Report).where(Report.recording_id == r.id, Report.superseded_at.is_(None)))
        if rep is None:
            continue
        critical += rep.critical
        informal += rep.informal
        res = score_result(db, rep.display_run_id, rep.rubric_version_id)
        for it in res["items"]:
            if it["status"] == "not_applicable":
                continue
            st = low.setdefault(it["item_id"], [0, 0, it["name"]])
            st[0] += 1 if it["low_confidence"] else 0
            st[1] += 1
    daily: dict[str, dict] = {}
    for r in recs:
        d = r.submitted_at.astimezone(CN).date().isoformat()
        x = daily.setdefault(d, {"date": d, "submitted": 0, "done": 0, "failed": 0})
        x["submitted"] += 1
        x["done"] += r.status == "done"
        x["failed"] += r.status == "failed"
    finished = len(done) + len(failed)
    audit.record(db, request, actor_type="user", actor_id=str(user.id), action="dashboard_view", target_type="dashboard", target_id="efficiency")
    db.commit()
    return {
        "submitted": len(recs), "done": len(done), "failed": len(failed), "in_progress": len(recs) - finished,
        "failure_rate": round(len(failed) / finished, 4) if finished else None,
        "minutes": {"median": round(statistics.median(mins), 1) if mins else None, "p95": _pct(mins, 0.95), "max": round(max(mins), 1) if mins else None},
        "over_30_min": sum(1 for m in mins if m > 30), "round_retries": retries,
        "critical_share": round(critical / len(done), 4) if done else None, "informal_reports": informal,
        "low_confidence": [{"item_id": k, "name": v[2], "rate": round(v[0] / v[1], 4), "count": v[0], "n": v[1]} for k, v in sorted(low.items())],
        "daily": sorted(daily.values(), key=lambda x: x["date"]),
    }
