"""给供应商调用加上：并发上限（所有 worker 合计）+ 单次调用失败重试。
偶发错误先就地重试本次调用（默认再试 2 次）；仍失败才让检测器失败、整轮按 M4-4 重试。"""
from __future__ import annotations

import logging
import time

from .base import ProviderError, Providers
from .registry import limit

log = logging.getLogger("audition.providers")


def _call(kind: str, n: int, redis_conn, backoff: tuple[float, ...], fn, *a, **kw):
    for attempt in range(len(backoff) + 1):
        try:
            with limit(kind, n, redis_conn):
                return fn(*a, **kw)
        except ProviderError as exc:
            if attempt == len(backoff):
                raise
            log.info("%s 调用失败，%.1f 秒后重试：%s", kind, backoff[attempt], exc)
            time.sleep(backoff[attempt])


class _Wrap:
    def __init__(self, inner, kind: str, method: str, n: int, redis_conn, backoff):
        self._inner, self._kind, self._method, self._n, self._redis, self._backoff = inner, kind, method, n, redis_conn, backoff
        self.name, self.model_version = inner.name, inner.model_version

    def __getattr__(self, attr):
        target = getattr(self._inner, attr)
        if attr != self._method:
            return target
        return lambda *a, **kw: _call(self._kind, self._n, self._redis, self._backoff, target, *a, **kw)


def resilient(p: Providers, *, limits: dict[str, int], redis_conn, backoff: tuple[float, ...]) -> Providers:
    def w(obj, kind, method):
        return _Wrap(obj, kind, method, limits.get(kind, 4), redis_conn, backoff)

    return Providers(w(p.asr, "asr", "transcribe"), w(p.speech_eval, "speech_eval", "assess"), w(p.llm, "llm", "complete_json"),
                     w(p.vision, "vision", "analyze"), w(p.laugh, "laugh", "detect"))
