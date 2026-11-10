"""校准（M6）：校准员证据级打分 → 同一个计分引擎算分 → 金标准（中位数、分歧裁决）→ 与 AI 对比、一致率。
口径见 docs/decisions.md C34（上线门槛）、C35（金标准与统计分母）。"""
from __future__ import annotations

import statistics
from datetime import datetime, timezone
from fractions import Fraction
from typing import Any

import yaml
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from scoring import Evidence, EvidenceError, ScoringInputError, parse_config, score_round
from scoring.aggregate import aggregate_item_scores, calibration_config

from ..models.entities import (
    AuditionSheet, CalibrationAssignment, EvidenceRow, GoldSample, GoldSet, Notification, PipelineRun, ProductCard, Recording, Report,
    RubricVersion,
)
from ..models.convert import row_to_evidence
from ..pipeline.runner import not_applicable_items, scoring_context
from . import audit
from .notify import notify
from .rescore import ai_outcome

FLAG_RATIO = Fraction(1, 5)  # 校准员之间条目分相差超过满分 20% → 裁决（C35）
ITEM_AGREE_RATIO = Fraction(1, 10)  # 条目一致：AI 与金标准相差不超过满分 10%（I28）
TARGET_DIM = 0.85  # 维度档位相差 ≤ 1 档的比例（PRD 第 1 节，C34）
TARGET_CONCLUSION = 0.95  # 结论一致（PRD 第 1 节，C34）
TARGET_ITEM = 0.85  # 条目级监控线（Q20 改作监控，C34）
MIN_GATE_SAMPLES = 30  # 上线门槛的最小定稿样本数：样本太少时一致率不可信（全面审查功能性第 7 条）


def _cfg(rv: RubricVersion):
    return parse_config(yaml.safe_load(rv.yaml_text))


def _sample_bits(db: Session, sample: GoldSample):
    gs = db.get(GoldSet, sample.gold_set_id)
    rv = db.get(RubricVersion, gs.rubric_version_id)
    rec = db.get(Recording, sample.recording_id)
    sheet = db.get(AuditionSheet, rec.sheet_id)
    card = db.get(ProductCard, sheet.product_card_id).content
    return gs, rv, rec, sheet, card


def _ai_p4(db: Session, rec: Recording) -> list[Evidence]:
    """P4 语速是按时间戳机械计数，校准时沿用流水线首轮测得的指标。"""
    run = db.scalar(select(PipelineRun).where(PipelineRun.recording_id == rec.id, PipelineRun.round_no == 1))
    if run is None:
        return []
    rows = db.scalars(select(EvidenceRow).where(EvidenceRow.run_id == run.id, EvidenceRow.item_id == "P4").order_by(EvidenceRow.id))
    return [row_to_evidence(r).model_copy(update={"evidence_id": f"AI-{r.evidence_id}"}) for r in rows]


def normalize_evidence(raw: list[dict], item_ids: set[str]) -> list[dict]:
    """校验校准员提交的证据：结构与 rubric 第 9 节一致，来源一律记为 human，编号由系统分配。"""
    out = []
    for i, e in enumerate(raw, start=1):
        if not isinstance(e, dict):
            raise HTTPException(422, "证据格式不对")
        e = {**e, "evidence_id": f"H{i:04d}", "source": "human", "confidence": 1.0}
        if e.get("item_id") not in item_ids or e.get("item_id") == "P4":
            raise HTTPException(422, f"条目 {e.get('item_id')!r} 不能由校准员录入")
        try:
            out.append(Evidence.model_validate(e).model_dump(mode="json"))
        except ValidationError as exc:
            raise HTTPException(422, f"第 {i} 条证据不合法：{exc.errors()[0]['msg']}") from exc
    return out


def score_assignment(db: Session, a: CalibrationAssignment) -> dict[str, Any]:
    """用校准配置（等级类直接给等级）和同一个计分引擎算出该校准员的条目分。缺条目则拒绝提交。"""
    sample = db.get(GoldSample, a.sample_id)
    _, rv, rec, sheet, card = _sample_bits(db, sample)
    ccfg = calibration_config(_cfg(rv))
    evs = [Evidence.model_validate(e) for e in a.evidence] + _ai_p4(db, rec)
    done = {it.id for _, it in ccfg.items()}
    try:
        r = score_round(evs, ccfg, scoring_context(rec, sheet, card, done, {"source": "human"}))
    except (EvidenceError, ScoringInputError) as exc:
        raise HTTPException(422, f"打分有误：{exc}") from exc
    if r.status != "complete":
        raise HTTPException(422, "还有条目没打完：" + "、".join(r.missing_items))
    return {"items": {i.item_id: i.score for i in r.items}, "dimensions": [d.model_dump() for d in r.dimensions],
            "total_grade": r.total_grade, "grade_pass": r.grade_pass, "critical": r.critical}


def _median(vals: list[float]) -> float:
    return float(statistics.median(vals))  # 2 人时即平均数


def consolidate(db: Session, sample: GoldSample, *, actor_id: str | None = None) -> None:
    """全部校准员提交后：条目分取中位数；分歧超过满分 20% 的条目待裁决；都有结果后定稿金标准。"""
    subs = db.scalars(select(CalibrationAssignment).where(CalibrationAssignment.sample_id == sample.id)).all()
    if not subs or any(a.status != "submitted" for a in subs):
        sample.status = "collecting"
        return
    gs, rv, rec, _, _ = _sample_bits(db, sample)
    cfg = _cfg(rv)
    maxes = {it.id: it.max for _, it in cfg.items()}
    per_item: dict[str, list[float]] = {}
    for a in subs:
        for k, v in a.result["items"].items():
            if v is not None:
                per_item.setdefault(k, []).append(v)
    flagged = sorted(k for k, vs in per_item.items() if Fraction(str(max(vs))) - Fraction(str(min(vs))) > FLAG_RATIO * maxes[k])
    sample.flagged_items = flagged
    if any(k not in sample.adjudication for k in flagged):
        sample.status = "needs_adjudication"
        return
    scores = {k: (sample.adjudication[k]["score"] if k in flagged else _median(vs)) for k, vs in per_item.items()}
    agg = aggregate_item_scores(cfg, scores, props_available=rec.props_available, audience=rec.audience,
                                not_applicable=not_applicable_items(rec))
    sample.gold = {"items": scores, "dimensions": [d.model_dump() for d in agg.dimensions], "total_grade": agg.total_grade,
                   "grade_pass": agg.grade_pass, "critical": agg.critical, "calibrators": len(subs), "adjudicated": flagged}
    sample.status, sample.finalized_at = "final", datetime.now(timezone.utc)
    audit.record(db, None, actor_type="user" if actor_id else "system", actor_id=actor_id, action="gold_finalize",
                 target_type="gold_sample", target_id=str(sample.id), total_grade=agg.total_grade, adjudicated=flagged)
    check_alerts(db, gs)


# ───────────── 对比与一致率 ─────────────


def compare(db: Session, sample: GoldSample) -> dict[str, Any] | None:
    """金标准与 AI 的逐项对比。AI 按金标准集的评分标准版本计算；轮次不够或缺证据记为“AI 不完整”。"""
    if sample.status != "final":
        return None
    _, rv, rec, _, _ = _sample_bits(db, sample)
    cfg = _cfg(rv)
    try:
        out = ai_outcome(db, rec, rv)
    except HTTPException:
        out = None
    gold = sample.gold
    gdims = {d["id"]: d for d in gold["dimensions"]}
    if out is None:
        return {"ai_complete": False, "gold": gold, "ai": None, "items": [], "dimensions": [], "conclusion_agree": False}
    verdict, res = out
    adims = {d.id: d for d in res.dimensions}
    maxes = {it.id: it.max for _, it in cfg.items()}
    items = []
    for it in res.items:
        if it.status == "not_applicable":
            continue
        g = gold["items"].get(it.item_id)
        if it.source == "human":  # 评委打的分：人和人比，不算 AI 的准确度，不进条目一致率
            items.append({"item_id": it.item_id, "name": it.name, "ai": None, "gold": g, "max": it.max, "agree": None,
                          "low_confidence": False, "human_scored": True, "human": it.score})
            continue
        agree = it.score is not None and g is not None and abs(Fraction(str(it.score)) - Fraction(str(g))) <= ITEM_AGREE_RATIO * maxes[it.item_id]
        items.append({"item_id": it.item_id, "name": it.name, "ai": it.score, "gold": g, "max": it.max, "agree": agree, "low_confidence": it.low_confidence})
    dims = [{"id": k, "name": gdims[k]["name"], "ai_grade": adims[k].grade, "gold_grade": gdims[k]["grade"],
             "agree": abs(adims[k].grade - gdims[k]["grade"]) <= 1} for k in gdims]
    return {"ai_complete": True, "gold": gold, "ai": {"total_grade": res.total_grade, "conclusion": verdict.conclusion, "label": verdict.label,
                                                      "critical": verdict.critical, "rounds": len(verdict.rounds)},
            "items": items, "dimensions": dims, "conclusion_agree": (verdict.conclusion == "pass") == bool(gold["grade_pass"])}


def _rate(ok: int, n: int) -> float | None:
    return round(ok / n, 4) if n else None


def metrics(db: Session, samples: list[GoldSample]) -> dict[str, Any]:
    """一致率（C35 分母）：维度 = 样本数 × 4；结论 = 定稿样本数，AI 不完整计为不一致；临界样本用 3 轮后的结论；低置信照常计入。"""
    final = [s for s in samples if s.status == "final"]
    dim_ok = dim_n = con_ok = 0
    item_stats: dict[str, dict] = {}
    low_conf = item_total = 0
    hh_dim_ok = hh_dim_n = hh_con_ok = hh_con_n = 0
    for s in final:
        c = compare(db, s)
        dim_n += 4
        if c["ai_complete"]:
            dim_ok += sum(1 for d in c["dimensions"] if d["agree"])
            con_ok += 1 if c["conclusion_agree"] else 0
        for it in c["items"]:
            if it.get("human_scored"):
                continue
            st = item_stats.setdefault(it["item_id"], {"item_id": it["item_id"], "name": it["name"], "ok": 0, "n": 0})
            st["n"] += 1
            st["ok"] += 1 if it["agree"] else 0
            item_total += 1
            low_conf += 1 if it["low_confidence"] else 0
        subs = db.scalars(select(CalibrationAssignment).where(CalibrationAssignment.sample_id == s.id)).all()
        res = [a.result for a in subs if a.result]
        for i in range(len(res)):  # 人与人：两两比较（M6-1）
            for j in range(i + 1, len(res)):
                gi = {d["id"]: d["grade"] for d in res[i]["dimensions"]}
                gj = {d["id"]: d["grade"] for d in res[j]["dimensions"]}
                hh_dim_n += 4
                hh_dim_ok += sum(1 for k in gi if abs(gi[k] - gj[k]) <= 1)
                hh_con_n += 1
                hh_con_ok += 1 if res[i]["grade_pass"] == res[j]["grade_pass"] else 0
    items = []
    for st in sorted(item_stats.values(), key=lambda x: x["item_id"]):
        rate = _rate(st["ok"], st["n"])
        items.append({**st, "rate": rate, "alert": rate is not None and rate < TARGET_ITEM})
    dim_rate, con_rate = _rate(dim_ok, dim_n), _rate(con_ok, len(final))
    return {
        "samples": len(samples), "final": len(final), "pending": len(samples) - len(final),
        "dimension_agreement": dim_rate, "conclusion_agreement": con_rate,
        "targets": {"dimension": TARGET_DIM, "conclusion": TARGET_CONCLUSION, "item": TARGET_ITEM},
        "min_gate_samples": MIN_GATE_SAMPLES,
        "gate_passed": len(final) >= MIN_GATE_SAMPLES and dim_rate is not None and con_rate is not None and dim_rate >= TARGET_DIM and con_rate >= TARGET_CONCLUSION,
        "items": items, "low_confidence_share": _rate(low_conf, item_total),
        "human_dimension_agreement": _rate(hh_dim_ok, hh_dim_n), "human_conclusion_agreement": _rate(hh_con_ok, hh_con_n),
    }


def check_alerts(db: Session, gs: GoldSet) -> None:
    """一致率低于目标时告警管理员（M6-2，Mock 渠道）。同一金标准集、同一指标只告警一次。"""
    m = metrics(db, list(db.scalars(select(GoldSample).where(GoldSample.gold_set_id == gs.id))))
    below = []
    if m["dimension_agreement"] is not None and m["dimension_agreement"] < TARGET_DIM:
        below.append(("dimension", m["dimension_agreement"]))
    if m["conclusion_agreement"] is not None and m["conclusion_agreement"] < TARGET_CONCLUSION:
        below.append(("conclusion", m["conclusion_agreement"]))
    below += [(f"item:{it['item_id']}", it["rate"]) for it in m["items"] if it["alert"]]
    sent = {(n.payload.get("set_id"), n.payload.get("metric")) for n in db.scalars(select(Notification).where(Notification.template == "calibration_below_target"))}
    for metric, value in below:
        if (str(gs.id), metric) not in sent:
            notify(db, audience="admin", recipient_ref="admins", template="calibration_below_target", set_id=str(gs.id), set_name=gs.name,
                   metric=metric, value=value)


def ai_report_id(db: Session, rec_id) -> str | None:
    rid = db.scalar(select(Report.id).where(Report.recording_id == rec_id, Report.superseded_at.is_(None)))
    return str(rid) if rid else None
