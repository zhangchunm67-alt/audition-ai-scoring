"""跑一轮：语音识别 → 声学特征 → 各检测器出证据 → 计分引擎算分。每一轮都从语音识别起重跑（C11），复用首轮准备好的音频和抽帧。"""
from __future__ import annotations

import logging
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import yaml
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from scoring import ChecklistPoint, HumanScore, RoundResult, ScoringContext, parse_config, score_round

from ..models.convert import evidence_to_row
from ..models.entities import (
    AcousticFeatures, AuditionSheet, DetectorConfigVersion, DetectorRun, EvidenceRow, Objection, PipelineRun, ProductCard, Question,
    Recording, RedlineLexiconVersion, RubricVersion, ScoreResultRow, Transcript,
)
from ..providers.base import Providers, SegmentHint, Word
from ..providers.resilient import resilient
from ..services.storage import Storage
from ..settings import get_settings
from . import acoustic, prompts, readiness
from .detector_config import DetectorConfig, parse as parse_detector_cfg
from .detectors import DETECTORS, NEEDS_PROPS, human_plan
from .detectors.common import Ctx
from .media import materialize
from .text import SegmentText

log = logging.getLogger("audition.pipeline")


class RoundIncomplete(RuntimeError):
    """本轮有检测器失败或缺必需证据：重试本轮（重试不算新的投票轮次）。"""


def detector_config(db: Session) -> tuple[DetectorConfigVersion, DetectorConfig]:
    from sqlalchemy import case

    row = db.scalar(select(DetectorConfigVersion).where(DetectorConfigVersion.status != "retired")
                    .order_by(case((DetectorConfigVersion.status == "published", 0), else_=1), DetectorConfigVersion.created_at.desc()).limit(1))
    if row is None:
        raise RuntimeError("没有检测配置版本，请先导入（python -m app.cli seed-demo）")
    return row, parse_detector_cfg(row.content)


def scoring_context(rec: Recording, sheet: AuditionSheet, card: dict, completed: set[str], manifest: dict) -> ScoringContext:
    """计分上下文。流水线每轮和“按新版重算”共用，保证同一份证据算出同样的结果。
    卖点卡要点（checklist）和知识题（O5）只给旧版 rubric-v0.1 的报告重算用；新版配置不读取它们。
    人工打分分工取自该轮的模型清单（human_review），已录入的人工分取自录像。"""
    plan = manifest.get("human_review") or {}
    return ScoringContext(
        human_scores={k: HumanScore(**v) for k, v in (rec.human_scores or {}).items()},
        human_only=set(plan.get("manual", [])), human_confirm=set(plan.get("confirm", [])),
        human_on_deduction=set(plan.get("confirm_on_deduction", [])), human_fallback=bool(plan.get("fallback_applied")),
        props_available=rec.props_available, audience=rec.audience, completed_detectors=completed,
        checklist=[ChecklistPoint(**{k: p[k] for k in ("id", "name", "points", "compliance_required") if k in p}) for p in card.get("checklist", [])],
        expected_questions={"S3": [o["objection_id"] for o in rec.objection_times], "O5": [q["question_id"] for q in sheet.questions]},
        main_duration_ms=rec.main_duration_ms,
        model_manifest=manifest,
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def run_round(db: Session, recording_id: uuid.UUID, round_no: int, providers: Providers, storage: Storage, redis_conn=None,
              last_attempt: bool = False) -> RoundResult:
    """last_attempt：本轮最后一次尝试。检测配置允许时，机器仍评不出的条目转评委打分，而不是整轮失败。
    返回的结果 awaiting_human_items 非空时，本轮等评委打分（run.status = awaiting_human）。"""
    s = get_settings()
    manifest = providers.manifest()
    raw_providers = providers
    providers = resilient(providers, limits={"llm": s.limit_llm, "asr": s.limit_asr}, redis_conn=redis_conn, backoff=s.call_retry_backoff_s)
    rec = db.get(Recording, recording_id)
    sheet = db.get(AuditionSheet, rec.sheet_id)
    rv = db.get(RubricVersion, sheet.rubric_version_id)
    cfg = parse_config(yaml.safe_load(rv.yaml_text))
    dv, dcfg = detector_config(db)
    run = db.scalar(select(PipelineRun).where(PipelineRun.recording_id == rec.id, PipelineRun.round_no == round_no))
    if run is None:
        run = PipelineRun(recording_id=rec.id, round_no=round_no)
        db.add(run)
    run.status, run.stage, run.started_at, run.detector_config_version_id, run.error = "running", "asr", _now(), dv.id, None
    db.flush()
    for model in (EvidenceRow, DetectorRun, Transcript, AcousticFeatures, ScoreResultRow):  # 重试时清掉上次的半成品
        db.execute(delete(model).where(model.run_id == run.id))
    db.commit()

    card = db.get(ProductCard, sheet.product_card_id).content
    problems = readiness.blockers(db, sheet, raw_providers)
    if problems:
        raise RoundIncomplete("暂不能处理：" + "；".join(problems))
    lexicon = db.get(RedlineLexiconVersion, sheet.redline_lexicon_version_id).content if sheet.redline_lexicon_version_id else {}
    objs = {str(o.id): o for o in db.scalars(select(Objection).where(Objection.id.in_([uuid.UUID(x["objection_id"]) for x in sheet.objections])))}
    qs = {str(q.id): q for q in db.scalars(select(Question).where(Question.id.in_([uuid.UUID(x["question_id"]) for x in sheet.questions])))}
    objections = [{"objection_id": o["objection_id"], "text": next(x["text"] for x in sheet.objections if x["objection_id"] == o["objection_id"]),
                   "video_ms": o["video_ms"], "at_ms": o["at_ms"], "answer_points": objs[o["objection_id"]].answer_points if o["objection_id"] in objs else []}
                  for o in rec.objection_times]
    questions = [{"question_id": q["question_id"], "text": q["text"], "full_points": qs[q["question_id"]].full_points if q["question_id"] in qs else []}
                 for q in sheet.questions]

    with tempfile.TemporaryDirectory(prefix=f"audition-{rec.id}-r{round_no}-") as tmp:
        media = materialize(db, rec, storage, dcfg, Path(tmp))
        texts: dict[str, SegmentText] = {}
        for seg in rec.segments:
            name = seg["segment"]
            hint = SegmentHint(
                segment="question" if name.startswith("question:") else name, round_no=round_no,
                reading_text=sheet.reading_text if name == "reading" else None,
                question_text=next((q["text"] for q in questions if f"question:{q['question_id']}" == name), None),
                objection_offsets_ms=[o["at_ms"] for o in objections] if name == "main" else [],
                objection_texts=[o["text"] for o in objections] if name == "main" else [],
            )
            tr = providers.asr.transcribe(media.audio[name], disfluency_removal=dcfg.asr.disfluency_removal,
                                          word_timestamps=dcfg.asr.word_timestamps, hint=hint)
            if tr.params.get("disfluency_removal") is not False:
                raise RoundIncomplete("语音识别供应商没有确认关闭顺滑，拒绝使用该转写")
            off = seg["start_ms"]
            words = [Word(w.text, w.start_ms + off, w.end_ms + off, w.confidence) for w in tr.words]
            texts[name] = SegmentText(name, words)
            db.add(Transcript(run_id=run.id, segment=name, text=tr.text, provider=tr.provider, model_version=tr.model_version,
                              disfluency_removal=False, words=[[w.text, w.start_ms, w.end_ms, round(w.confidence, 3)] for w in words]))
        run.stage = "acoustic"
        feats = {}
        for name in ("main",):
            f = acoustic.features(media.audio[name])
            f["silences_ms"] = [[a + media.offsets[name], b + media.offsets[name]] for a, b in f["silences_ms"]]
            feats[name] = f
            db.add(AcousticFeatures(run_id=run.id, segment=name, features=f))
        db.commit()

        run.stage = "detectors"
        ctx = Ctx(round_no=round_no, props_available=rec.props_available, segments=rec.segments, objections=objections, questions=questions,
                  reading_text=sheet.reading_text, card=card, lexicon=lexicon, cfg=dcfg, texts=texts, acoustic=feats, media=media,
                  providers=providers)
        item_ids = {it.id for _, it in cfg.items()}
        plan = human_plan(dcfg, raw_providers, item_ids)
        plan["fallback_applied"] = bool(plan["fallback"] and last_attempt)
        todo = {k: fn for k, fn in DETECTORS.items()
                if (k in item_ids or (k == "redlines" and cfg.redlines.enabled)) and not (k in NEEDS_PROPS and not rec.props_available)
                and k not in plan["manual"]}

        def one(item: str):
            try:
                return item, todo[item](ctx), None
            except Exception as exc:  # 检测器失败：记录下来，本轮不完整 → 重试，绝不当作“没有扣分事件”
                log.warning("检测器 %s 失败（第 %d 轮）：%s", item, round_no, exc)
                return item, [], exc

        with ThreadPoolExecutor(max_workers=s.detector_workers) as pool:
            results = list(pool.map(one, todo))
        evidence, completed = [], set()
        for item, evs, exc in results:
            db.add(DetectorRun(run_id=run.id, detector_id=item, status="failed" if exc else "completed", error=str(exc)[:2000] if exc else None))
            if exc is None:
                completed.add(item)
                evidence.extend(evs)
        db.add_all([evidence_to_row(e, run.id) for e in evidence])

        run.stage = "scoring"
        sctx = scoring_context(rec, sheet, card, completed,
                               {**manifest, **readiness.s2_manifest(card), "prompts": prompts.prompt_set_hash(), "detector_config": dv.version,
                                "temperature": "0", "asr_disfluency_removal": "false", "human_review": plan})
        result = score_round(evidence, cfg, sctx)
        db.add(ScoreResultRow(run_id=run.id, rubric_version_id=rv.id, config_hash=result.config_hash, result=result.model_dump(mode="json")))
        run.model_manifest = result.model_manifest
        failed = [i for i, _, e in results if e]
        if result.status != "complete" and not result.missing_items:  # 只差评委打分
            run.status, run.stage, run.finished_at = "awaiting_human", "human", _now()
            run.error = "等评委打分：" + "、".join(result.awaiting_human_items) + (f"；失败的检测器：{'、'.join(failed)}" if failed else "")
            db.commit()
            return result
        if result.status != "complete":
            run.status, run.error, run.finished_at = "failed", f"缺少必需证据：{'、'.join(result.missing_items)}；失败的检测器：{'、'.join(failed) or '无'}", _now()
            db.commit()
            raise RoundIncomplete(run.error)
        run.status, run.stage, run.finished_at = "completed", "done", _now()
        db.commit()
        return result
