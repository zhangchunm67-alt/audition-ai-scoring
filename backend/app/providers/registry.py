"""按配置选择供应商实现。APP_PROVIDERS=mock 时全部用 Mock；真实供应商（须境内服务）接入后在这里注册。

测试可用 set_providers() 替换为带故障注入或逐轮差异的实现。
"""
from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager

from .base import Providers

_override: Providers | None = None
_lock = threading.Lock()


def set_providers(p: Providers | None) -> None:
    global _override
    _override = p


def get_providers() -> Providers:
    if _override is not None:
        return _override
    kind = os.environ.get("APP_PROVIDERS", "mock")
    if kind == "mock":
        from .mock import MockASR, MockLaugh, MockLLM, MockSpeechEval, MockVision, MockVoice

        from .mock import Faults

        scenario = os.environ.get("APP_MOCK_SCENARIO", "standard")
        rate = float(os.environ.get("APP_MOCK_FAIL_RATE", "0"))

        def f(kind: str, seed: int) -> Faults:  # 压测用：按环境变量注入每次调用的延迟和随机失败
            return Faults(latency_s=float(os.environ.get(f"APP_MOCK_LATENCY_{kind}", "0")), fail_rate=rate, seed=seed)

        return Providers(MockASR(scenario, f("ASR", 1), rtf=float(os.environ.get("APP_MOCK_ASR_RTF", "0"))), MockSpeechEval(faults=f("EVAL", 2)),
                         MockLLM(faults=f("LLM", 3)), MockVision(faults=f("VISION", 4)), MockLaugh(faults=f("LAUGH", 5)),
                         MockVoice(faults=f("VOICE", 6)))
    raise RuntimeError(f"未知的供应商配置 APP_PROVIDERS={kind}；接入真实供应商的方法见 README“更换真实 AI 供应商”")


# ───────────── 并发限流：多个 worker 共用同一个上限（Redis 计数），没有 Redis 时退回进程内计数 ─────────────

_local_counts: dict[str, int] = {}


@contextmanager
def limit(kind: str, max_concurrent: int, redis_conn=None, poll_s: float = 0.05, ttl_s: int = 600):
    key = f"audition:limit:{kind}"
    while True:
        if redis_conn is not None:
            n = redis_conn.incr(key)
            redis_conn.expire(key, ttl_s)
            if n <= max_concurrent:
                break
            redis_conn.decr(key)
        else:
            with _lock:
                if _local_counts.get(key, 0) < max_concurrent:
                    _local_counts[key] = _local_counts.get(key, 0) + 1
                    break
        time.sleep(poll_s)
    try:
        yield
    finally:
        if redis_conn is not None:
            redis_conn.decr(key)
        else:
            with _lock:
                _local_counts[key] -= 1
