"""检测器的公共上下文和工具。检测器只产出证据（rubric 第 9 节），不产出分数。"""
from __future__ import annotations

import itertools
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from scoring.types import Evidence, Review

from ...providers.base import Providers
from .. import llm as llm_client
from ..detector_config import DetectorConfig
from ..media import Prepared
from ..text import SegmentText, locate_chars, locate_fuzzy, sentences


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
                 model_conf: float, source: str = "llm", strict: bool = True, **kw) -> Evidence:
        """引用须能定位回原文才计分。先精确匹配（忽略标点），不行再容错匹配（相似度 ≥ 0.85，置信度按相似度打折）。
        仍定位不到时：strict（等级、逐题等一条证据决定整条分数的）→ 检测器失败，交给重试或评委；
        非 strict（逐次、加分实例等可以逐条计的）→ 只丢掉这一条：留作“已排除”的证据供复核，不计分，条目标低置信。"""
        st = st or self.main
        span = locate_chars(st, quote, after_ms=after_ms)
        ratio = 1.0
        if span is None and (fz := locate_fuzzy(st, quote, after_ms=after_ms)) is not None:
            span, ratio = fz[:2], fz[2]
        if span is None:
            if strict:
                raise ValueError(f"{item}: 引用无法在指定原文范围定位")
            e = self.ev(item, kind, quote=quote, confidence=0.0, source=source, segment=st.segment, **kw)
            e.review = Review(status="rejected", reviewer="system", note=UNLOCATED)
            return e
        pos = st.span(*span)
        conf = min(model_conf, st.min_confidence(*span)) * ratio
        e = self.ev(item, kind, start=pos[0], end=pos[1], quote=quote, confidence=conf, source=source, segment=st.segment, **kw)
        if ratio < 1:
            e.reason = (e.reason or "") + f"（引用与原文相似度 {ratio:.2f}，按容错匹配定位）"
        return e


UNLOCATED = "引用无法在原文定位，已排除、不计分"


def check_level(item: str, level, max_score: int) -> int:
    """主观评分条目：模型给的分必须是 0–满分的整数，否则检测失败（不交给计分引擎当配置错误处理）。"""
    if isinstance(level, bool) or not isinstance(level, int) or not 0 <= level <= max_score:
        raise ValueError(f"{item}: 模型给分 {level!r} 不是 0–{max_score} 的整数")
    return level


def main_sentences(ctx: Ctx):
    return sentences(ctx.main)


def binary(flag: bool) -> str:
    return "count" if flag else "not_count"
