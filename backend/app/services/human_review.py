"""评委人工打分（decisions.md T39）：机器评不了或须人工确认的条目，由评委在系统里补分，然后继续出报告。

- 人工分存在录像上（recordings.human_scores），各轮共用；
- 录入后用已存的证据重新计分（不重跑模型），等评委打分的轮次补齐后改为完成，接着按原流程决定是否追加轮次或出报告；
- 可以分几次录入；全部补齐前录像保持“等待评委打分”。
"""
from __future__ import annotations

from datetime import datetime, timezone

import yaml
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from scoring import EvidenceError, RoundResult, ScoringInputError, parse_config, score_round

from ..models.convert import row_to_evidence
from ..models.entities import (
    AuditionSheet, DetectorRun, EvidenceRow, PipelineRun, ProductCard, Recording, RubricVersion, ScoreResultRow, User,
)
from ..pipeline.runner import scoring_context


def _ctx(db: Session, rec: Recording):
    sheet = db.get(AuditionSheet, rec.sheet_id)
    rv = db.get(RubricVersion, sheet.rubric_version_id)
    return sheet, rv, parse_config(yaml.safe_load(rv.yaml_text)), db.get(ProductCard, sheet.product_card_id).content


def waiting_runs(db: Session, rec: Recording) -> list[PipelineRun]:
    return list(db.scalars(select(PipelineRun).where(PipelineRun.recording_id == rec.id, PipelineRun.status == "awaiting_human")
                           .order_by(PipelineRun.round_no)))


def _rescore(db: Session, rec: Recording, run: PipelineRun) -> RoundResult:
    sheet, rv, cfg, card = _ctx(db, rec)
    evs = [row_to_evidence(r) for r in db.scalars(select(EvidenceRow).where(EvidenceRow.run_id == run.id).order_by(EvidenceRow.id))]
    done = set(db.scalars(select(DetectorRun.detector_id).where(DetectorRun.run_id == run.id, DetectorRun.status == "completed")))
    try:
        return score_round(evs, cfg, scoring_context(rec, sheet, card, done, run.model_manifest))
    except (EvidenceError, ScoringInputError) as exc:
        raise HTTPException(422, str(exc)) from exc


def pending_items(db: Session, rec: Recording) -> list[dict]:
    """等评委打分的条目：机器建议分（各轮）、原因、相关证据原句。"""
    out: dict[str, dict] = {}
    _, _, cfg, _ = _ctx(db, rec)
    dim_name = {d.id: d.name for d in cfg.dimensions}
    for run in waiting_runs(db, rec):
        row = db.scalar(select(ScoreResultRow).where(ScoreResultRow.run_id == run.id))
        if row is None:
            continue
        res = RoundResult.model_validate(row.result)
        for it in res.items:
            if it.status != "awaiting_human":
                continue
            d = out.setdefault(it.item_id, {"item_id": it.item_id, "name": it.name, "dimension": it.dimension,
                                            "label": f"{dim_name.get(it.dimension, it.dimension)}·{it.name}", "max": it.max,
                                            "reasons": it.missing_reasons, "suggested": {}, "evidence": []})
            d["suggested"][str(run.round_no)] = it.suggested_score
            inj = (run.model_manifest.get("human_review") or {}).get("injection") or []
            if inj and not any(r.startswith("逐字稿里有疑似") for r in d["reasons"]):
                d["reasons"] = [*d["reasons"], "逐字稿里有疑似针对评分的话，模型给分可能受影响：" + "；".join(x["quote"] for x in inj[:3])]
            if not d["evidence"]:
                rows = db.scalars(select(EvidenceRow).where(EvidenceRow.run_id == run.id, EvidenceRow.item_id == it.item_id)
                                  .order_by(EvidenceRow.start_ms))
                d["evidence"] = [{"start_ms": r.start_ms, "end_ms": r.end_ms, "quote": r.quote, "label": r.label,
                                  "judgment": r.judgment, "reason": r.reason} for r in rows][:50]
    return list(out.values())


def submit(db: Session, rec: Recording, scores: dict[str, dict], user: User) -> list[int]:
    """保存人工分并重新计分。返回补齐后可以继续的轮次。调用方提交事务后调用 orchestrator.after_round。"""
    if rec.status != "awaiting_human":
        raise HTTPException(409, "这条录像现在不需要评委打分")
    _, _, cfg, _ = _ctx(db, rec)
    maxes = {it.id: it.max for _, it in cfg.items()}
    waiting = {p["item_id"] for p in pending_items(db, rec)}
    unknown = sorted(set(scores) - waiting)
    if unknown:
        raise HTTPException(422, "这些条目不需要人工打分：" + "、".join(unknown))
    now = datetime.now(timezone.utc).isoformat()
    merged = dict(rec.human_scores or {})
    for item, v in scores.items():
        sc = v.get("score")
        if isinstance(sc, bool) or not isinstance(sc, (int, float)) or not 0 <= sc <= maxes[item] or (sc * 2) != int(sc * 2):
            raise HTTPException(422, f"{item} 的分数应为 0–{maxes[item]} 之间的整数或半分")
        merged[item] = {"score": float(sc), "by": user.username, "at": now, "note": (v.get("note") or None)}
    rec.human_scores = merged
    db.flush()
    ready = []
    for run in waiting_runs(db, rec):
        res = _rescore(db, rec, run)
        row = db.scalar(select(ScoreResultRow).where(ScoreResultRow.run_id == run.id))
        row.config_hash, row.result = res.config_hash, res.model_dump(mode="json")
        if res.status == "complete":
            run.status, run.stage, run.error = "completed", "done", None
            ready.append(run.round_no)
        elif res.missing_items:
            raise HTTPException(422, "缺少机器证据，人工分补不齐，请重新处理：" + "、".join(res.missing_items))
    if not waiting_runs(db, rec):
        rec.status = "processing"  # 交回编排继续：追加轮次或出报告
    return ready
