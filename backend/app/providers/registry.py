"""按配置选择供应商实现。APP_PROVIDERS=mock 时全部用 Mock；真实供应商（须境内服务）接入后在这里注册。

测试可用 set_providers() 替换为带故障注入或逐轮差异的实现。
"""
from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager

from .base import ProviderError, Providers

_override: Providers | None = None
_lock = threading.Lock()


def set_providers(p: Providers | None) -> None:
    global _override
    _override = p


def get_providers() -> Providers:
    if _override is not None:
        return _override
    return production_guard(_build(), os.environ)


def production_guard(p: Providers, env) -> Providers:
    """生产环境（APP_ENV=production）不使用 Mock：Mock 的能力一律视为未配置，依赖它的条目转评委打分，
    绝不出现用假数据算出的分数。"""
    if env.get("APP_ENV", "development") != "production":
        return p
    caps = ("asr", "speech_eval", "llm", "vision", "laugh", "voice")
    return Providers(*[Unavailable(c) if getattr(p, c).name.startswith("mock") else getattr(p, c) for c in caps])


def _build() -> Providers:
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
    if kind == "config":
        return from_env(os.environ)
    raise RuntimeError(f"未知的供应商配置 APP_PROVIDERS={kind}；接入真实供应商的方法见 README“更换真实 AI 供应商”")


class Unavailable:
    """未配置的能力：一调用就失败，对应检测器失败、条目缺证据（未评），绝不当作没有扣分事件（C16）。"""

    model_version = "-"

    def __init__(self, capability: str):
        self.capability, self.name = capability, f"none:{capability}"

    def __getattr__(self, method):
        if method.startswith("_"):
            raise AttributeError(method)

        def fail(*a, **kw):
            raise ProviderError(f"{self.capability} 未配置（APP_PROVIDERS=config 下没有为它选实现）")
        return fail


def from_env(env) -> Providers:
    """APP_PROVIDERS=config：逐项选择实现，未选的为“未配置”。
    APP_ASR / APP_LAUGH：mock | sherpa；APP_LLM：mock | openai | replay；APP_VISION：mock | openai | replay；
    APP_VOICE：mock | openai；APP_SPEECH_EVAL：mock（真实普通话评测尚未接入）。
    openai 类的模型名分别为 APP_LLM_MODEL、APP_VLM_MODEL、APP_OMNI_MODEL，服务地址见 oa()。"""
    import json

    from . import mock
    from .openai_compat import OpenAICompatLLM, OpenAICompatVision, OpenAICompatVoice
    from .replay import ReplayLLM, ReplayVision

    def pick(cap: str) -> str:
        return env.get(f"APP_{cap}", "none").lower()

    def oa(cls, model_var: str, **kw):
        # 每类模型可以各起一个服务（llama-server 一个进程一个模型）：APP_LLM_BASE_URL / APP_VLM_BASE_URL / APP_OMNI_BASE_URL，
        # 没设时用公共的 APP_OPENAI_BASE_URL
        base = env.get(model_var.replace("_MODEL", "_BASE_URL")) or env.get("APP_OPENAI_BASE_URL")
        if not base or not env.get(model_var):
            raise RuntimeError(f"选了 openai 实现，但缺少 {model_var.replace('_MODEL', '_BASE_URL')}（或 APP_OPENAI_BASE_URL）或 {model_var}")
        return cls(base, env[model_var], api_key=env.get("APP_OPENAI_API_KEY") or None, json_mode=env.get("APP_OPENAI_JSON_MODE", "json_schema"),
                   timeout_s=float(env.get("APP_OPENAI_TIMEOUT_S", "600")), extra=json.loads(env.get("APP_OPENAI_EXTRA", "{}")), **kw)

    sherpa = None
    if "sherpa" in (pick("ASR"), pick("LAUGH")):
        from .sherpa import SherpaLaughDetector, SherpaSenseVoiceASR
        sherpa = (SherpaSenseVoiceASR, SherpaLaughDetector)
    replay_root = env.get("APP_REPLAY_DIR", "var/replay")
    choices = {
        "ASR": {"mock": lambda: mock.MockASR(), "sherpa": lambda: sherpa[0](env["APP_SENSEVOICE_DIR"], env["APP_VAD_MODEL"],
                                                                             num_threads=int(env.get("APP_ASR_THREADS", "4")))},
        "SPEECH_EVAL": {"mock": lambda: mock.MockSpeechEval()},
        "LLM": {"mock": lambda: mock.MockLLM(), "openai": lambda: oa(OpenAICompatLLM, "APP_LLM_MODEL"),
                "replay": lambda: ReplayLLM(replay_root, env.get("APP_REPLAY_JUDGE", "external"))},
        "VISION": {"mock": lambda: mock.MockVision(), "openai": lambda: oa(OpenAICompatVision, "APP_VLM_MODEL", dress_code=env.get("APP_DRESS_CODE", "")),
                   "replay": lambda: ReplayVision(
                       replay_root, set(filter(None, env.get("APP_REPLAY_VISION_TASKS", "attire,prop_pointing").split(","))),
                       env.get("APP_REPLAY_JUDGE", "external"))},
        "LAUGH": {"mock": lambda: mock.MockLaugh(), "sherpa": lambda: sherpa[1](env["APP_CED_DIR"],
                                                                                threshold=float(env.get("APP_LAUGH_THRESHOLD", "0.3")))},
        "VOICE": {"mock": lambda: mock.MockVoice(), "openai": lambda: oa(OpenAICompatVoice, "APP_OMNI_MODEL",
                                                                         clips=int(env.get("APP_VOICE_CLIPS", "3")),
                                                                         clip_s=float(env.get("APP_VOICE_CLIP_S", "45")))},
    }
    built = {}
    for cap, opts in choices.items():
        c = pick(cap)
        if c == "none":
            built[cap] = Unavailable(cap)
        elif c in opts:
            built[cap] = opts[c]()
        else:
            raise RuntimeError(f"APP_{cap}={c} 不支持，可选：none、{'、'.join(opts)}")
    return Providers(built["ASR"], built["SPEECH_EVAL"], built["LLM"], built["VISION"], built["LAUGH"], built["VOICE"])


# ───────────── 并发限流：多个 worker 共用同一个上限，没有 Redis 时退回进程内计数 ─────────────
# Redis 里用有序集合记每个占用的名额（成员 = 令牌，分值 = 到期时间）。每个名额单独到期：
# worker 在调用中途被杀，它占的名额到期后自动归还，不会越积越多把所有处理卡死。

_local_counts: dict[str, int] = {}
_ACQUIRE = """
local now = tonumber(ARGV[1])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
if redis.call('ZCARD', KEYS[1]) < tonumber(ARGV[2]) then
  redis.call('ZADD', KEYS[1], now + tonumber(ARGV[3]), ARGV[4])
  redis.call('EXPIRE', KEYS[1], math.ceil(tonumber(ARGV[3])) + 60)
  return 1
end
return 0
"""


@contextmanager
def limit(kind: str, max_concurrent: int, redis_conn=None, poll_s: float = 0.05, ttl_s: int = 900):
    """ttl_s：单个名额的租期，须长于单次模型调用的超时（APP_OPENAI_TIMEOUT_S 默认 600 秒）。"""
    import uuid

    key = f"audition:lease:{kind}"
    token = uuid.uuid4().hex
    while True:
        if redis_conn is not None:
            if redis_conn.eval(_ACQUIRE, 1, key, time.time(), max_concurrent, ttl_s, token):
                break
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
            redis_conn.zrem(key, token)
        else:
            with _lock:
                _local_counts[key] -= 1
