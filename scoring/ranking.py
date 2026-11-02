"""批次排名（M5-5）。纯函数。口径见 docs/decisions.md C9、I4。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from .types import Label

LABEL_ORDER: dict[str, int] = {"recommend": 0, "pending": 1, "not_recommend": 2}


class RankEntry(BaseModel):
    report_id: str
    label: Label
    total_grade: int
    dimension_scores: dict[str, int]  # 折算并取整后的维度分
    redline_hit: bool
    submitted_at: datetime


def rank(entries: list[RankEntry], by: str = "default") -> list[RankEntry]:
    """by="default"：结论标签 → 总档位升序 → 四个维度分之和降序 → 无红线优先 → 提交时间升序。
    by=维度编号（P/S/L/O）：该维度分降序 → 总档位升序 → 无红线优先 → 提交时间升序。
    """
    if by == "default":
        key = lambda e: (  # noqa: E731
            LABEL_ORDER[e.label],
            e.total_grade,
            -sum(e.dimension_scores.values()),
            e.redline_hit,
            e.submitted_at,
        )
    else:
        for e in entries:
            if by not in e.dimension_scores:
                raise ValueError(f"{e.report_id} 没有维度 {by!r}")
        key = lambda e: (-e.dimension_scores[by], e.total_grade, e.redline_hit, e.submitted_at)  # noqa: E731
    return sorted(entries, key=key)
