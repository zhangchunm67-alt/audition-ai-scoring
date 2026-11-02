"""媒体读取：一律经后端流式代理，每次读取（含每个 Range 请求）写审计（T10、A1）。"""
from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..models.entities import MediaAsset, User
from ..security.rbac import Perm
from ..services import audit
from ..services.storage import get_storage
from .deps import DB, require

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


@router.get("/{asset_id}")
def read_media(asset_id: uuid.UUID, request: Request, db: Session = DB, viewer: User = Depends(require(Perm.report_read_all))):
    asset = db.get(MediaAsset, asset_id)
    if asset is None:
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
