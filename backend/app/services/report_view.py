"""报告内容组装：总览、条目与证据、逐句评分（M5-1、M5-6）。只读，不改任何数据。"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.entities import (
    AuditionSheet, DetectorConfigVersion, EvidenceRow, MediaAsset, PipelineRun, Product, Recording, RedlineLexiconVersion, Report,
    RubricVersion, ScoreResultRow, Transcript,
)
from ..pipeline.text import SegmentText, sentences
from ..providers.base import Word

# 这些证据表示“这句话有问题”（扣分、未加分或答错），逐句评分里标红并给示范说法
ISSUE_OCCURRENCE = {"P1", "P2", "P3", "P7", "P8", "P10", "L3", "S2", "L1"}  # S2、L1、P7 的逐次证据只出现在旧版报告
ISSUE_INSTANCE = {"S4", "L2", "L4", "L5", "O1", "O2", "O3"}


def score_result(db: Session, run_id, rubric_version_id) -> dict:
    return db.scalar(select(ScoreResultRow.result).where(ScoreResultRow.run_id == run_id, ScoreResultRow.rubric_version_id == rubric_version_id))


def _contrib(result: dict) -> dict[str, float]:
    return {c["evidence_id"]: c["delta"] for it in result["items"] for c in it["contributions"]}


def _is_issue(e: EvidenceRow, delta: float | None) -> bool:
    if delta is not None and delta < 0:
        return True
    j = e.judgment
    if e.kind == "occurrence" and e.item_id in ISSUE_OCCURRENCE and j == "count" and e.label != "inference":
        return True
    if e.kind == "instance" and e.item_id in ISSUE_INSTANCE and j == "not_count":
        return True
    if e.kind == "question" and e.item_id == "S3" and ((e.label in ("wrong_answer", "no_answer") and j == "count") or j == "not_count"):
        return True
    return False


def evidence_dicts(db: Session, run_id, result: dict) -> list[dict]:
    contrib = _contrib(result)
    names = {it["item_id"]: it["name"] for it in result["items"]}
    out = []
    for e in db.scalars(select(EvidenceRow).where(EvidenceRow.run_id == run_id).order_by(EvidenceRow.start_ms.nulls_last(), EvidenceRow.id)):
        delta = contrib.get(e.evidence_id)
        out.append({
            "evidence_id": e.evidence_id, "item_id": e.item_id, "item_name": names.get(e.item_id, e.item_id), "kind": e.kind,
            "start_ms": e.start_ms, "end_ms": e.end_ms, "quote": e.quote, "label": e.label, "judgment": e.judgment, "reason": e.reason,
            "confidence": e.confidence, "source": e.source, "ref": e.ref, "value": e.value, "segment": e.segment, "delta": delta,
            "issue": _is_issue(e, delta),
        })
    return out


def _sentence_index(sents, start_ms: int, end_ms: int | None) -> int | None:
    """这条证据归到哪一句：取时间重叠最长的一句；只有一个时间点的，取包含它的那句。
    语音识别的逐字时间戳首尾相接（上一句句号的结束时间 = 下一句第一个字的开始时间），
    所以句子按左闭右开 [start, end) 比较，否则引用整句的证据会被挂到上一句。"""
    end = end_ms if end_ms is not None and end_ms > start_ms else start_ms + 1
    best, best_overlap = None, 0
    for k, s in enumerate(sents):
        overlap = min(end, s.end_ms) - max(start_ms, s.start_ms)
        if overlap > best_overlap:
            best, best_overlap = k, overlap
    if best is not None:
        return best
    # 落在句间空隙里的（抽帧时间点等）：归到 200 毫秒内紧接着开始的那句
    return next((k for k, s in enumerate(sents) if s.start_ms - 200 <= start_ms < s.start_ms), None)


def sentence_view(db: Session, rec: Recording, run_id, evidence: list[dict], suggestions: list[dict]) -> list[dict]:
    """逐句评分：每句标出命中的条目、加扣分和原因；定位不到具体句子的证据挂在分段上。"""
    order = {s["segment"]: i for i, s in enumerate(rec.segments)}
    by_seg: dict[str, list[dict]] = {}
    for e in evidence:
        by_seg.setdefault(e["segment"] or "main", []).append(e)
    sugg = {(x["segment"], x["start_ms"]): x["suggestion"] for x in suggestions}
    out = []
    for tr in sorted(db.scalars(select(Transcript).where(Transcript.run_id == run_id)), key=lambda t: order.get(t.segment, 99)):
        st = SegmentText(tr.segment, [Word(w[0], w[1], w[2], w[3]) for w in tr.words])
        evs = sorted(by_seg.get(tr.segment, []), key=lambda e: (e["start_ms"] is None, e["start_ms"] or 0))
        sents = sentences(st)
        hits_of: dict[int, list[dict]] = {}
        used: set[str] = set()
        for e in evs:
            k = _sentence_index(sents, e["start_ms"], e["end_ms"]) if e["start_ms"] is not None else None
            if k is not None:
                hits_of.setdefault(k, []).append(e)
                used.add(e["evidence_id"])
        rows = []
        for k, s in enumerate(sents):
            hits = hits_of.get(k, [])
            rows.append({"segment": tr.segment, "start_ms": s.start_ms, "end_ms": s.end_ms, "text": s.text, "hits": hits,
                         "issue": any(h["issue"] for h in hits), "suggestion": sugg.get((tr.segment, s.start_ms))})
        rows.sort(key=lambda r: r["start_ms"])
        out.append({"segment": tr.segment, "sentences": rows, "segment_hits": [e for e in evs if e["evidence_id"] not in used]})
    return out


def detail(db: Session, rep: Report) -> dict[str, Any]:
    from ..api.candidates import get_candidate, name_of

    rec = db.get(Recording, rep.recording_id)
    sheet = db.get(AuditionSheet, rec.sheet_id)
    rv = db.get(RubricVersion, rep.rubric_version_id)
    dv = db.get(DetectorConfigVersion, rep.detector_config_version_id)
    lex = db.get(RedlineLexiconVersion, sheet.redline_lexicon_version_id) if sheet.redline_lexicon_version_id else None
    display = db.get(PipelineRun, rep.display_run_id)
    result = score_result(db, display.id, rv.id)
    evidence = evidence_dicts(db, display.id, result)
    video = db.scalar(select(MediaAsset).where(MediaAsset.recording_id == rec.id, MediaAsset.kind == "raw_video"))
    return {
        "id": str(rep.id), "revision": rep.revision, "superseded_at": rep.superseded_at, "created_at": rep.created_at,
        "recording_id": str(rec.id), "candidate_id": str(rec.candidate_id), "candidate_name": name_of(get_candidate(db, rec.candidate_id)),
        "submitted_at": rec.submitted_at, "sheet_code": sheet.code, "product_name": db.get(Product, sheet.product_id).name,
        "audience": rec.audience, "props_available": rec.props_available, "mode": rec.mode,
        "label": rep.label, "conclusion": rep.conclusion, "critical": rep.critical, "redline_hit": rep.redline_hit, "informal": rep.informal,
        "verdict": rep.verdict, "display_round": rep.verdict.get("display_round"),
        "result": {k: result[k] for k in ("items", "dimensions", "total_grade", "threshold", "audience", "critical", "low_confidence_items",
                                         "missing_items", "redlines_enabled", "redline_below_threshold")},
        "evidence": evidence,
        "sentences": sentence_view(db, rec, display.id, evidence, rep.suggestions or []),
        "trace": {
            "rubric_version": rv.version, "rubric_status": rv.status, "config_hash": rep.config_hash,
            "detector_config_version": dv.version, "detector_config_status": dv.status,
            "redline_lexicon_version": lex.version if lex else None, "model_manifest": rep.model_manifest,
        },
        "media": {"video_asset_id": str(video.id) if video and video.deleted_at is None else None,
                  "video_deleted": bool(video and video.deleted_at), "segments": rec.segments, "objection_times": rec.objection_times,
                  "exclusions": rec.exclusions or []},
    }
