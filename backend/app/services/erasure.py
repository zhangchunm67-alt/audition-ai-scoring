"""删除候选人的全部资料（全面审查安全性第 4 条）：候选人撤回同意或要求删除时，由管理员执行。

删除：原视频和全部派生媒体、授权书扫描件（对象存储里的文件）；逐字稿、证据原句和理由、示范说法、
评委备注、校准员标注里的原句；候选人姓名、手机号。
保留（去标识后）：条目分数、维度分、总档位和结论等数字，用于准确度统计；审计记录（只有编号，没有内容）。
候选人记录标为已删除，之后任何页面都查不到、不能再处理。不可恢复。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.entities import (
    CalibrationAssignment, Candidate, EvidenceRow, GoldSample, MediaAsset, PipelineRun, Recording, Report,
    ScoreResultRow, Transcript,
)
from ..security.crypto import encrypt
from ..settings import get_settings
from . import audit
from .storage import Storage

ERASED = "（已删除）"


def _scrub_result(result: dict) -> dict:
    for hit in result.get("redline_hits", []) + result.get("redline_below_threshold", []):
        hit["quote"], hit["reason"] = None, None
    for it in result.get("items", []):
        if it.get("human"):
            it["human"]["note"] = None
    return result


def erase_candidate(db: Session, storage: Storage, cid: uuid.UUID, *, actor_id: str | None, reason: str) -> dict:
    c = db.get(Candidate, cid)
    if c is None or c.deleted_at is not None:
        raise LookupError("候选人不存在或已删除")
    now = datetime.now(timezone.utc)
    recs = db.scalars(select(Recording).where(Recording.candidate_id == cid)).all()
    rec_ids = [r.id for r in recs]
    assets = db.scalars(select(MediaAsset).where((MediaAsset.candidate_id == cid) | MediaAsset.recording_id.in_(rec_ids))).all()
    n_media = 0
    for a in assets:
        if a.deleted_at is None:
            try:
                storage.delete(a.storage_key)
            except FileNotFoundError:
                pass
            a.deleted_at, n_media = now, n_media + 1
        a.original_filename = None
    run_ids = list(db.scalars(select(PipelineRun.id).where(PipelineRun.recording_id.in_(rec_ids))))
    for t in db.scalars(select(Transcript).where(Transcript.run_id.in_(run_ids))):
        t.text, t.words = ERASED, []
    for e in db.scalars(select(EvidenceRow).where(EvidenceRow.run_id.in_(run_ids))):
        e.quote, e.reason = None, None
        if e.review and e.review.get("note"):
            e.review = {**e.review, "note": None}
    for row in db.scalars(select(ScoreResultRow).where(ScoreResultRow.run_id.in_(run_ids))):
        row.result = _scrub_result(dict(row.result))
    for rep in db.scalars(select(Report).where(Report.recording_id.in_(rec_ids))):
        rep.suggestions = []
    for r in recs:
        r.human_scores = {k: {**v, "note": None} for k, v in (r.human_scores or {}).items()}
        r.failure_reason = None
    for gs in db.scalars(select(GoldSample).where(GoldSample.recording_id.in_(rec_ids))):
        gs.adjudication = {k: {**v, "note": None} for k, v in (gs.adjudication or {}).items()}
        for a in db.scalars(select(CalibrationAssignment).where(CalibrationAssignment.sample_id == gs.id)):
            a.evidence = [{**e, "quote": None, "reason": None} for e in (a.evidence or [])]
            a.note = None
    key = get_settings().data_key
    c.name_enc = encrypt(ERASED, key, aad=f"candidate:{cid}:name".encode())
    c.phone_enc, c.phone_hash, c.linked_user_id = None, None, None
    c.deleted_at = now
    c.deletion_requested_at = c.deletion_requested_at or now
    out = {"recordings": len(recs), "media_deleted": n_media}
    audit.record(db, None, actor_type="user" if actor_id else "system", actor_id=actor_id, action="candidate_erase",
                 target_type="candidate", target_id=str(cid), reason=reason[:200], **out)
    db.commit()
    return out
