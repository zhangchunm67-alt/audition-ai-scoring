"""处理编排：媒体准备 → 首轮 → （临界）追加 2 轮 → 汇总出报告。

- 每轮失败自动重试 2 次（共 3 次尝试），重试不算新的投票轮次（C5、M4-4）；仍失败则录像标为失败并告警管理员。
  失败多半是模型或系统问题，不自动通知候选人重录；管理员确认是录像本身的问题后再联系候选人。
- 机器部分跑完、只差评委打分时转“等待评委打分”（T39）。
- 断电、重启、队列丢任务会让录像卡在处理中：sweep_stuck() 把超时的标为失败，之后可重新处理。
- 首轮临界且未命中红线才追加第 2、3 轮，两轮并行；首轮已命中红线不追加（C17）；追加后不再递归。
- 执行方式：APP_QUEUE=rq 用 Redis 队列（多 worker 并行），inline 在当前进程同步执行（开发、测试）。
"""
from __future__ import annotations

import logging
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from scoring import RoundResult, finalize, parse_config, rounds_required

from ..db import get_engine
from ..models.entities import AuditionSheet, PipelineRun, RedlineLexiconVersion, Recording, Report, RubricVersion, ScoreResultRow
from ..providers.registry import get_providers
from ..services import audit
from ..services.notify import notify
from ..services.report_creation import build_report
from ..services.storage import get_storage
from ..settings import get_settings
from .media import prepare
from .runner import detector_config, run_round

log = logging.getLogger("audition.pipeline")
QUEUE_NAME = "audition"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _redis():
    if get_settings().queue != "rq":
        return None
    from redis import Redis

    return Redis.from_url(get_settings().redis_url)


def _enqueue(fn, *args) -> None:
    if get_settings().queue == "rq":
        from rq import Queue

        Queue(QUEUE_NAME, connection=_redis(), default_timeout=3600).enqueue(fn, *args, job_timeout=3600)
    else:
        fn(*args)


def start(recording_id: uuid.UUID) -> None:
    """提交后调用：进入处理。"""
    _enqueue(job_first_round, str(recording_id))


# ───────────── 任务 ─────────────


def _mark(recording_id: str, round_no: int, **fields) -> None:
    with Session(get_engine()) as db:
        run = db.scalar(select(PipelineRun).where(PipelineRun.recording_id == uuid.UUID(recording_id), PipelineRun.round_no == round_no))
        if run is not None:
            for k, v in fields.items():
                setattr(run, k, v)
            db.commit()


def _with_retries(recording_id: str, round_no: int, work) -> bool:
    """首次尝试失败后再重试 len(backoff) 次（默认 2 次）。retry_count 记已重试的次数。"""
    backoff = get_settings().retry_backoff_s
    for attempt in range(len(backoff) + 1):
        if attempt:
            time.sleep(backoff[attempt - 1])
            _mark(recording_id, round_no, retry_count=attempt)
        try:
            work(attempt == len(backoff))
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("录像 %s 第 %d 轮第 %d 次尝试失败：%s", recording_id, round_no, attempt + 1, str(exc)[:300])
            _mark(recording_id, round_no, status="failed", error=str(exc)[:2000])
            last = str(exc)
    _fail(recording_id, round_no, last)
    return False


def job_first_round(recording_id: str) -> None:
    rid = uuid.UUID(recording_id)
    with Session(get_engine()) as db:
        rec = db.get(Recording, rid)
        rec.status, rec.processing_started_at, rec.failure_reason = "processing", rec.processing_started_at or _now(), None
        db.commit()

    def work(last: bool):
        with Session(get_engine()) as db, tempfile.TemporaryDirectory(prefix="audition-prep-") as tmp:
            rec = db.get(Recording, rid)
            _, dcfg = detector_config(db)
            prepare(db, rec, get_storage(), dcfg, Path(tmp))
            db.commit()
            run_round(db, rid, 1, get_providers(), get_storage(), _redis(), last_attempt=last)

    if _with_retries(recording_id, 1, work):
        after_round(recording_id)


def job_round(recording_id: str, round_no: int) -> None:
    def work(last: bool):
        with Session(get_engine()) as db:
            run_round(db, uuid.UUID(recording_id), round_no, get_providers(), get_storage(), _redis(), last_attempt=last)

    if _with_retries(recording_id, round_no, work):
        after_round(recording_id)


def _load(db: Session, rec: Recording) -> tuple[list[RoundResult | None], dict]:
    runs = {r.round_no: r for r in db.scalars(select(PipelineRun).where(PipelineRun.recording_id == rec.id))}
    out: list[RoundResult | None] = []
    for n in sorted(runs):
        sr = db.scalar(select(ScoreResultRow).where(ScoreResultRow.run_id == runs[n].id))
        out.append(RoundResult.model_validate(sr.result) if (sr and runs[n].status == "completed") else None)
    return out, runs


def after_round(recording_id: str) -> None:
    """每轮完成后调用：决定是否追加轮次，或汇总出报告。行锁保证并行的第 2、3 轮只汇总一次。"""
    to_enqueue: list[int] = []
    with Session(get_engine()) as db:
        rec = db.scalar(select(Recording).where(Recording.id == uuid.UUID(recording_id)).with_for_update())
        if rec.status != "processing":
            return
        sheet = db.get(AuditionSheet, rec.sheet_id)
        rv = db.get(RubricVersion, sheet.rubric_version_id)
        cfg = parse_config(yaml.safe_load(rv.yaml_text))
        results, runs = _load(db, rec)
        waiting = sorted(n for n, r in runs.items() if r.status == "awaiting_human")
        if waiting and all(r.status in ("awaiting_human", "completed") for r in runs.values()):
            # 机器部分都跑完了，只差评委打分：转“等待评委打分”，评委录入后继续（services/human_review.py）
            rec.status = "awaiting_human"
            notify(db, audience="admin", recipient_ref="reviewers", template="human_scores_needed", recording_id=recording_id, rounds=waiting)
            audit.record(db, None, actor_type="system", actor_id=None, action="awaiting_human", target_type="recording",
                         target_id=str(rec.id), rounds=waiting)
            db.commit()
            return
        if waiting:  # 并行的其他轮还在跑，等它们
            return
        first = results[0]
        required = rounds_required(first, cfg)
        if required > 1 and len(runs) < required:
            for n in range(len(runs) + 1, required + 1):
                db.add(PipelineRun(recording_id=rec.id, round_no=n, status="queued"))
                to_enqueue.append(n)
            audit.record(db, None, actor_type="system", actor_id=None, action="critical_rerun", target_type="recording",
                         target_id=str(rec.id), total_grade=first.total_grade, rounds=required)
        elif len(results) >= required and all(r is not None for r in results[:required]):
            _make_report(db, rec, sheet, rv, cfg, results[:required], runs)
        db.commit()
    for n in to_enqueue:
        _enqueue(job_round, recording_id, n)


def _make_report(db: Session, rec: Recording, sheet: AuditionSheet, rv: RubricVersion, cfg, results: list[RoundResult], runs: dict) -> None:
    if db.scalar(select(Report).where(Report.recording_id == rec.id, Report.superseded_at.is_(None))):
        return
    v = finalize(results, cfg)
    display = runs[v.display_round]
    dv, _ = detector_config(db)
    lex = db.get(RedlineLexiconVersion, sheet.redline_lexicon_version_id) if sheet.redline_lexicon_version_id else None
    try:
        from ..providers.resilient import resilient
        from .suggest import generate

        s = get_settings()
        prov = resilient(get_providers(), limits={"llm": s.limit_llm}, redis_conn=_redis(), backoff=s.call_retry_backoff_s)
        suggestions = generate(db, rec, display.id, results[v.display_round - 1].model_dump(mode="json"), prov)
    except Exception as exc:  # noqa: BLE001  示范说法只用于辅导，失败不影响出报告
        log.warning("录像 %s 示范说法生成失败：%s", rec.id, str(exc)[:200])
        suggestions = []
    report = build_report(
        recording_id=rec.id, revision=1, rubric=rv, detector_config=dv, lexicon=lex,
        verdict=v, results=results, display_run_id=display.id, suggestions=suggestions,
    )
    db.add(report)
    rec.status, rec.finished_at = "done", _now()
    audit.record(db, None, actor_type="system", actor_id=None, action="report_create", target_type="recording", target_id=str(rec.id),
                 label=v.label, critical=v.critical, rounds=len(results), informal=report.informal)


def _fail(recording_id: str, round_no: int, reason: str) -> None:
    with Session(get_engine()) as db:
        rec = db.scalar(select(Recording).where(Recording.id == uuid.UUID(recording_id)).with_for_update())
        if rec.status == "failed":
            return
        rec.status, rec.finished_at = "failed", _now()
        rec.failure_reason = f"第 {round_no} 轮处理失败（已自动重试 2 次）：{reason}"[:2000]
        notify(db, audience="admin", recipient_ref="admins", template="processing_failed_alert",
               recording_id=recording_id, round_no=round_no, reason=reason[:500])
        audit.record(db, None, actor_type="system", actor_id=None, action="processing_failed", target_type="recording",
                     target_id=recording_id, round_no=round_no, reason=reason[:500])
        db.commit()


def sweep_stuck(db: Session, *, older_than_min: int | None = None) -> list[str]:
    """把卡在“已提交 / 处理中”超过设定时长的录像标为失败（断电、容器重启、队列丢任务），之后可在页面上重新处理。"""
    from datetime import timedelta

    minutes = older_than_min if older_than_min is not None else get_settings().stuck_after_min
    cutoff = _now() - timedelta(minutes=minutes)
    stuck = db.scalars(select(Recording).where(Recording.status.in_(("submitted", "processing")),
                                               (Recording.processing_started_at.is_(None) & (Recording.submitted_at < cutoff))
                                               | (Recording.processing_started_at < cutoff)).with_for_update()).all()
    for rec in stuck:
        rec.status, rec.finished_at = "failed", _now()
        rec.failure_reason = f"处理超过 {minutes} 分钟没有完成（可能因断电、重启或队列丢失而中断），请重新处理"
        for run in db.scalars(select(PipelineRun).where(PipelineRun.recording_id == rec.id, PipelineRun.status.in_(("queued", "running")))):
            run.status, run.error = "failed", "处理中断（超时）"
        notify(db, audience="admin", recipient_ref="admins", template="processing_stuck_alert", recording_id=str(rec.id), minutes=minutes)
        audit.record(db, None, actor_type="system", actor_id=None, action="processing_stuck", target_type="recording",
                     target_id=str(rec.id), minutes=minutes)
    db.commit()
    return [str(r.id) for r in stuck]
