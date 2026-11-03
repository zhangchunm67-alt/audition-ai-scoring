"""到期删除（PRD 第 5 节“存储”、C13、C24）：
- 未录用（含未定）候选人的原视频和派生媒体（音频、抽帧、片段）到期即删对象、留记录；报告和文字证据保留；
- 已录用的不自动删除（正式政策待法务，P-B12）；
- 授权书扫描件是授权凭证，暂不随视频删除（P-CONSENT-KEEP）；
- 超过 7 天仍未完成的上传：放弃分片上传，清理临时分片。
由定时任务每天执行：python -m app.cli purge-expired
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.entities import Candidate, MediaAsset, Recording, UploadSession
from . import audit
from .storage import Storage

MEDIA_KINDS = ("raw_video", "normalized_video", "audio", "frame", "clip", "upload_part")
STALE_UPLOAD = timedelta(days=7)


def purge_expired(db: Session, storage: Storage, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    q = (
        select(MediaAsset, Candidate.hiring_status)
        .join(Recording, MediaAsset.recording_id == Recording.id)
        .join(Candidate, Recording.candidate_id == Candidate.id)
        .where(MediaAsset.deleted_at.is_(None), MediaAsset.retention_until <= now, MediaAsset.kind.in_(MEDIA_KINDS))
    )
    deleted, kept_hired = 0, 0
    for asset, hiring in db.execute(q).all():
        if hiring == "hired":
            kept_hired += 1
            continue
        storage.delete(asset.storage_key)
        asset.deleted_at = now
        deleted += 1
        audit.record(db, None, actor_type="system", actor_id=None, action="media_purge", target_type="media_asset", target_id=str(asset.id),
                     kind=asset.kind, recording_id=str(asset.recording_id), reason="保存期限到期")
    aborted = 0
    for u in db.scalars(select(UploadSession).where(UploadSession.status == "open", UploadSession.created_at <= now - STALE_UPLOAD)):
        try:
            storage.abort_multipart(u.storage_key, u.multipart_upload_id)
        finally:
            u.status = "aborted"
            aborted += 1
            audit.record(db, None, actor_type="system", actor_id=None, action="upload_purge", target_type="upload", target_id=str(u.id))
    db.commit()
    return {"deleted": deleted, "kept_hired": kept_hired, "aborted_uploads": aborted}
