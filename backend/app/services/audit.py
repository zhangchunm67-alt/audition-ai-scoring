"""审计日志：只增不改。调用方在同一事务里写入，业务失败回滚时审计一起回滚；登录失败等单独提交。"""
from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from ..models.entities import AuditLog


def record(
    db: Session,
    request: Request | None,
    *,
    actor_type: str,
    actor_id: str | None,
    action: str,
    target_type: str,
    target_id: str,
    **detail: Any,
) -> AuditLog:
    row = AuditLog(
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        detail=detail,
        ip=request.client.host if request and request.client else None,
        user_agent=(request.headers.get("user-agent") or "")[:512] if request else None,
    )
    db.add(row)
    return row
