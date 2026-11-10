"""从条目分汇总出维度分、档位、总档位和结论（不经证据）。用于金标准：条目分取校准员的中位数或裁决值后再汇总。
另提供校准员打分用的配置：需要仪器测量的等级（普通话评测分、音高音量、停顿次数、节奏指标）改为由校准员直接给等级。"""
from __future__ import annotations

from fractions import Fraction

from pydantic import BaseModel

from .config import RubricConfig, T4Item, parse_config
from .engine import ScoringInputError, dimension_result, total_verdict
from .types import DimensionResult


class Aggregate(BaseModel):
    status: str  # complete / incomplete
    dimensions: list[DimensionResult]
    total_grade: int | None
    threshold: int
    grade_pass: bool | None
    critical: bool | None
    missing_items: list[str]


def aggregate_item_scores(cfg: RubricConfig, scores: dict[str, float | None], *, props_available: bool, audience: str,
                          not_applicable: frozenset[str] | set[str] = frozenset()) -> Aggregate:
    """not_applicable：本条录像不适用的条目（录播里没有标出观众异议时的 S3），不计入维度满分。"""
    if audience not in cfg.thresholds:
        raise ScoringInputError(f"未知的达标线 {audience!r}")
    dims, missing = [], []
    for dim in cfg.dimensions:
        raw, app_max, complete = Fraction(0), 0, True
        for it in dim.items:
            if (it.applicable_if == "props_available" and not props_available) or it.id in not_applicable:
                continue
            app_max += it.max
            v = scores.get(it.id)
            if v is None:
                complete = False
                missing.append(it.id)
                continue
            f = Fraction(str(v))
            if not 0 <= f <= it.max:
                raise ScoringInputError(f"{it.id} 分数 {v} 超出 0–{it.max}")
            raw += f
        dims.append(dimension_result(cfg, dim.id, dim.name, raw, app_max, complete))
    threshold = cfg.thresholds[audience]
    total, grade_pass, critical = total_verdict(cfg, dims, threshold)
    return Aggregate(status="complete" if total is not None else "incomplete", dimensions=dims, total_grade=total,
                     threshold=threshold, grade_pass=grade_pass, critical=critical, missing_items=missing)


def calibration_config(cfg: RubricConfig) -> RubricConfig:
    """校准员打分用的配置：T4 各部分都改为直接给等级（等级表、封顶和降级修正不变），其余计分规则与正式配置相同。
    P4 语速是按时间戳机械计数的，沿用流水线测得的指标。"""
    data = cfg.model_dump(mode="json", by_alias=True)
    data["version"] = f"{cfg.version}+calibration"
    data["status"] = "draft"
    for d in data["dimensions"]:
        for it in d["items"]:
            if it["type"] != "T4":
                continue
            for part in it["parts"]:
                part.update(source="evidence", metric=None, metric_bands=[], count_labels=[], count_bands=[], rules=[],
                            boundary_flag=None, pending=[], calibration_required=False)
    out = parse_config(data)
    assert all(p.source == "evidence" for _, it in out.items() if isinstance(it, T4Item) for p in it.parts)
    return out
