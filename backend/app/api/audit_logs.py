from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.entities import AuditLog, User
from ..security.rbac import Perm
from ..services import audit
from .deps import DB, require

router = APIRouter(prefix="/audit-logs", tags=["审计日志"])


class AuditOut(BaseModel):
    id: int
    at: datetime
    actor_type: str
    actor_id: str | None
    action: str
    target_type: str
    target_id: str
    detail: dict
    ip: str | None


@router.get("", response_model=list[AuditOut])
def list_logs(
    request: Request,
    action: str | None = None,
    target_id: str | None = None,
    actor_id: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = DB,
    viewer: User = Depends(require(Perm.audit_read)),
) -> list[AuditOut]:
    q = select(AuditLog).order_by(AuditLog.id.desc())
    if action:
        q = q.where(AuditLog.action == action)
    if target_id:
        q = q.where(AuditLog.target_id == target_id)
    if actor_id:
        q = q.where(AuditLog.actor_id == actor_id)
    rows = [AuditOut.model_validate(r, from_attributes=True) for r in db.scalars(q.limit(limit).offset(offset))]
    audit.record(db, request, actor_type="user", actor_id=str(viewer.id), action="audit_view", target_type="audit_log", target_id="*",
                 filters={"action": action, "target_id": target_id, "actor_id": actor_id})
    db.commit()
    return rows
