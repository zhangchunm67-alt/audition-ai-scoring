"""检测器的公共上下文和工具。检测器只产出证据（rubric 第 9 节），不产出分数。"""
from __future__ import annotations

import itertools
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from scoring.types import Evidence

from ...providers.base import Providers
from .. import llm as llm_client
from ..detector_config import DetectorConfig
from ..media import Prepared
from ..text import SegmentText, locate, sentences


@dataclass
class Ctx:
    round_no: int
    props_available: bool
    segments: list[dict]  # [{segment, start_ms, end_ms}]，视频时间
    objections: list[dict]  # [{objection_id, text, video_ms, answer_points}]
    questions: list[dict]  # [{question_id, text, full_points}]
    reading_text: str
    card: dict
    lexicon: dict
    cfg: DetectorConfig
    texts: dict[str, SegmentText]
    acoustic: dict[str, dict]  # 分段 → 特征（静音已换算为视频时间）
    media: Prepared
    providers: Providers
    _ids: itertools.count = field(default_factory=lambda: itertools.count(1))
    _cache: dict[str, Any] = field(default_factory=dict)

    def seg(self, name: str) -> dict:
        return next(s for s in self.segments if s["segment"] == name)

    @property
    def main(self) -> SegmentText:
        return self.texts["main"]

    def ask(self, task: str, payload: dict) -> dict:
        return llm_client.ask(self.providers.llm, task, payload, round_no=self.round_no)

    def cached(self, key: str, fn: Callable[[], Any]) -> Any:
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]

    def ev(self, item: str, kind: str, *, confidence: float, source: str, start: int | None = None, end: int | None = None,
           quote: str | None = None, label: str | None = None, judgment: Any = None, reason: str | None = None,
           ref: str | None = None, value: float | None = None, segment: str = "main") -> Evidence:
        return Evidence(
            evidence_id=f"{item}-{next(self._ids):04d}", item_id=item, kind=kind, start_ms=start, end_ms=end, quote=quote,
            label=label, judgment=judgment, reason=reason, confidence=round(max(0.0, min(1.0, confidence)), 3), source=source,
            ref=ref, value=value, segment=segment,
        )

    def quote_ev(self, item: str, kind: str, quote: str, *, st: SegmentText | None = None, after_ms: int | None = None,
                 model_conf: float, source: str = "llm", **kw) -> Evidence:
        """引用原句的证据：定位回时间；置信度取模型把握与该处转写置信度的较小者（转写不清即低置信）。"""
        st = st or self.main
        pos = locate(st, quote, after_ms=after_ms)
        conf = model_conf
        if pos:
            text = st.text
            i = text.find(quote) if quote in text else -1
            if i >= 0:
                conf = min(conf, st.min_confidence(i, i + len(quote)))
        return self.ev(item, kind, start=pos[0] if pos else None, end=pos[1] if pos else None, quote=quote,
                       confidence=conf, source=source, segment=st.segment, **kw)


def main_sentences(ctx: Ctx):
    return sentences(ctx.main)


def binary(flag: bool) -> str:
    return "count" if flag else "not_count"
