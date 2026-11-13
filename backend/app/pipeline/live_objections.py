"""录播的观众异议自动识别（2026-11-13，修订 C37）：不要求员工逐条看录播标注。

系统听不到观众，只有主播的逐字稿。主播念出、转述或明确在回答的观众问题能从逐字稿里找到；
主播没理会的弹幕找不到，所以自动识别时评不了“有人问了没回”，也量不出回应速度（O4 不用这两项）。
人工标注仍然可以做：标了就以人工为准，不再自动识别。画面里的弹幕区以后可以用视觉模型读，现在没做。
"""
from __future__ import annotations

import uuid

from . import llm
from .text import SegmentText, locate_chars, locate_fuzzy

MAX_AUTO = 20  # 一条录播最多取这么多条，避免长录播里模型罗列过多
MIN_CONFIDENCE = 0.5
SAME_PLACE_MS = 15_000  # 15 秒内的两条视为同一处回应


def detect(llm_provider, st: SegmentText, *, round_no: int = 1) -> list[dict]:
    """返回 [{text, video_ms}]，按时间排序。video_ms 是主播开始回应的时间；引用定位不到原文的丢掉，不凭模型说的算。"""
    if not st.text.strip():
        return []
    r = llm.ask(llm_provider, "live_objections", {"transcript": st.text}, round_no=round_no)
    found: list[dict] = []
    for x in r["items"]:
        question = x["question"].strip()
        if not question or x["confidence"] < MIN_CONFIDENCE:
            continue
        span = locate_chars(st, x["quote"])
        if span is None and (fz := locate_fuzzy(st, x["quote"])) is not None:
            span = fz[:2]
        if span is None:
            continue
        ms = st.span(*span)[0]
        if any(abs(ms - f["video_ms"]) < SAME_PLACE_MS for f in found):
            continue
        found.append({"text": question[:500], "video_ms": ms})
    return sorted(found, key=lambda f: f["video_ms"])[:MAX_AUTO]


def as_records(found: list[dict]) -> tuple[list[dict], list[dict]]:
    """存到题单内部记录和录像上的形式，和人工标注同构，多一个 source=auto。"""
    ids = [str(uuid.uuid4()) for _ in found]
    sheet = [{"objection_id": i, "text": f["text"], "at_ms": f["video_ms"], "source": "auto"} for i, f in zip(ids, found)]
    times = [{"objection_id": i, "at_ms": f["video_ms"], "video_ms": f["video_ms"], "source": "auto"} for i, f in zip(ids, found)]
    return sheet, times
