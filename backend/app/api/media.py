"""媒体读取：一律经后端流式代理，每次读取（含每个 Range 请求）写审计（T10、A1）。"""
from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.entities import CalibrationAssignment, Candidate, GoldSample, MediaAsset, Recording, User
from ..security.rbac import Perm, allowed
from ..services import audit
from ..services.storage import get_storage
from .deps import DB, current_user

router = APIRouter(prefix="/media", tags=["媒体"])
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


def _parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    if not header:
        return None
    m = _RANGE.match(header.strip())
    if not m or (m.group(1) == "" and m.group(2) == ""):
        raise HTTPException(416, "不支持的 Range")
    a, b = m.group(1), m.group(2)
    if a == "":
        start, end = max(0, size - int(b)), size - 1
    else:
        start, end = int(a), min(int(b) if b else size - 1, size - 1)
    if start > end or start >= size:
        raise HTTPException(416, "Range 超出文件范围")
    return start, end


def _may_read(db: Session, user: User, asset: MediaAsset) -> bool:
    if allowed(user.role, Perm.report_read_all):
        return True
    if allowed(user.role, Perm.report_read_own) and asset.recording_id:  # 新主播只能看本人录像（C31），授权书扫描件不开放
        rec = db.get(Recording, asset.recording_id)
        return db.get(Candidate, rec.candidate_id).linked_user_id == user.id
    if allowed(user.role, Perm.calibration_score) and asset.recording_id and asset.kind == "raw_video":  # 校准员只看分给自己的样本
        return db.scalar(select(CalibrationAssignment.id).join(GoldSample, CalibrationAssignment.sample_id == GoldSample.id)
                         .where(GoldSample.recording_id == asset.recording_id, CalibrationAssignment.calibrator_id == user.id).limit(1)) is not None
    return False


@router.get("/{asset_id}")
def read_media(asset_id: uuid.UUID, request: Request, db: Session = DB, viewer: User = Depends(current_user)):
    asset = db.get(MediaAsset, asset_id)
    if asset is None or not _may_read(db, viewer, asset):
        if not any(allowed(viewer.role, p) for p in (Perm.report_read_all, Perm.report_read_own, Perm.calibration_score)):
            raise HTTPException(403, "没有权限")
        raise HTTPException(404, "媒体不存在")
    if asset.deleted_at is not None:
        raise HTTPException(410, "媒体已按保存期限或申请删除")
    storage = get_storage()
    size = storage.size(asset.storage_key)
    rng = _parse_range(request.headers.get("range"), size)
    start, end = rng if rng else (0, size - 1)
    audit.record(db, request, actor_type="user", actor_id=str(viewer.id), action="media_read", target_type="media_asset",
                 target_id=str(asset.id), kind=asset.kind, recording_id=str(asset.recording_id) if asset.recording_id else None,
                 candidate_id=str(asset.candidate_id) if asset.candidate_id else None, range=[start, end], bytes=end - start + 1)
    db.commit()
    headers = {"Accept-Ranges": "bytes", "Content-Length": str(end - start + 1), "Cache-Control": "no-store, private"}
    if rng:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(storage.read_range(asset.storage_key, start, end), status_code=206 if rng else 200,
                             media_type=asset.content_type or "application/octet-stream", headers=headers)
