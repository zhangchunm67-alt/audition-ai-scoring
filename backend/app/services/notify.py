"""通知：候选人（处理失败需重录）和管理员告警。v1 全部走 Mock 渠道（C12）：写入 notifications 表并记日志，不真正发送。
实际渠道确定后实现 Notifier 接口即可。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy.orm import Session

from ..models.entities import Notification

log = logging.getLogger("audition.notify")


class Notifier(Protocol):
    channel: str

    def send(self, n: Notification) -> None: ...


class MockNotifier:
    channel = "mock"

    def send(self, n: Notification) -> None:
        log.info("[mock 通知] %s → %s：%s %s", n.audience, n.recipient_ref, n.template, n.payload)


_notifier: Notifier = MockNotifier()


def notify(db: Session, *, audience: str, recipient_ref: str, template: str, **payload) -> Notification:
    n = Notification(audience=audience, channel=_notifier.channel, recipient_ref=recipient_ref, template=template, payload=payload)
    db.add(n)
    db.flush()
    _notifier.send(n)
    n.status, n.sent_at = "sent", datetime.now(timezone.utc)
    return n
