"""计分配置的模型、加载、校验和发布检查。

每个配置节点都可以带两个标记：
- pending: [Q6, ...]        规则来自待确认项，未拍板；
- calibration_required: true 数值是测试占位，未经校准。
带任一标记的配置可以用于开发和测试，但不能发布为正式评分配置（见 publish_blockers）。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Any, Literal, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConfigError(ValueError):
    """配置本身不合法。"""


class _Node(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pending: list[str] = Field(default_factory=list)
    calibration_required: bool = False


# ───────────────────────── T4 等级来源 ─────────────────────────


class MetricBand(_Node):
    min: float | None = None  # 下限（含）；None 表示兜底
    level: int


class CountBand(_Node):
    min: int
    max: int | None = None  # 含；None 表示无上限
    level: int


class Condition(_Node):
    metric: str
    op: Literal["<", "<=", ">", ">=", "=="]
    value: float


class LevelRule(_Node):
    level: int
    all: list[Condition] = Field(default_factory=list)
    default: bool = False


class BoundaryFlag(_Node):
    """落在分段边界时标低置信（B3，待确认）。"""

    enabled: bool = True
    margin: float | None = None  # 指标型：离任一分段下限 ≤ margin
    counts: list[int] = Field(default_factory=list)  # 计次型：次数落在这些值上


class Modifier(_Node):
    """等级修正：出现某标签的证据（judgment=count）时封顶或降级。"""

    label: str
    enabled: bool = True
    cap: int | None = None
    downgrade: int | None = None

    @model_validator(mode="after")
    def _one_effect(self) -> "Modifier":
        if (self.cap is None) == (self.downgrade is None):
            raise ValueError("modifier 必须且只能设置 cap 或 downgrade 之一")
        return self


class LevelPart(_Node):
    id: str = "main"
    levels: list[int]  # 从高到低
    source: Literal["evidence", "metric", "count", "rules"] = "evidence"
    metric: str | None = None  # source=metric
    metric_bands: list[MetricBand] = Field(default_factory=list)
    count_labels: list[str] = Field(default_factory=list)  # source=count
    count_bands: list[CountBand] = Field(default_factory=list)
    rules: list[LevelRule] = Field(default_factory=list)  # source=rules
    modifiers: list[Modifier] = Field(default_factory=list)
    boundary_flag: BoundaryFlag | None = None

    @model_validator(mode="after")
    def _check(self) -> "LevelPart":
        if not self.levels or self.levels != sorted(self.levels, reverse=True):
            raise ValueError(f"part {self.id}: levels 必须非空且从高到低")
        if len(set(self.levels)) != len(self.levels):
            raise ValueError(f"part {self.id}: levels 有重复")
        lv = set(self.levels)
        if self.source == "metric":
            if not self.metric or not self.metric_bands:
                raise ValueError(f"part {self.id}: source=metric 需要 metric 和 metric_bands")
            mins = [b.min for b in self.metric_bands]
            if mins[-1] is not None or any(m is None for m in mins[:-1]):
                raise ValueError(f"part {self.id}: metric_bands 最后一档须为兜底（min 为空），其余须有 min")
            if mins[:-1] != sorted(mins[:-1], reverse=True):
                raise ValueError(f"part {self.id}: metric_bands 须按 min 从高到低")
            if not {b.level for b in self.metric_bands} <= lv:
                raise ValueError(f"part {self.id}: metric_bands 的 level 不在 levels 中")
        if self.source == "count":
            if not self.count_labels or not self.count_bands:
                raise ValueError(f"part {self.id}: source=count 需要 count_labels 和 count_bands")
            expect = 0
            for i, b in enumerate(self.count_bands):
                if b.min != expect:
                    raise ValueError(f"part {self.id}: count_bands 须从 0 起连续覆盖")
                last = i == len(self.count_bands) - 1
                if b.max is None and not last:
                    raise ValueError(f"part {self.id}: 只有最后一档可以无上限")
                if b.max is not None:
                    if b.max < b.min:
                        raise ValueError(f"part {self.id}: count_bands max < min")
                    expect = b.max + 1
            if self.count_bands[-1].max is not None:
                raise ValueError(f"part {self.id}: count_bands 最后一档须无上限")
            if not {b.level for b in self.count_bands} <= lv:
                raise ValueError(f"part {self.id}: count_bands 的 level 不在 levels 中")
        if self.source == "rules":
            if not self.rules or not self.rules[-1].default or any(r.default for r in self.rules[:-1]):
                raise ValueError(f"part {self.id}: rules 最后一条须为 default，且只能有一条 default")
            if not {r.level for r in self.rules} <= lv:
                raise ValueError(f"part {self.id}: rules 的 level 不在 levels 中")
        for m in self.modifiers:
            if m.cap is not None and m.cap not in lv:
                raise ValueError(f"part {self.id}: modifier cap {m.cap} 不在 levels 中")
        return self


# ───────────────────────── 条目 ─────────────────────────


class _Item(_Node):
    id: str
    name: str
    max: int = Field(gt=0)
    applicable_if: Literal["studio", "home"] | None = None
    low_confidence_threshold: float | None = Field(default=None, ge=0, le=1)
    window: str | None = None  # 说明性字段：统计窗口
    note: str | None = None


class Normalize(_Node):
    """时长不足时按比例换算次数（P2，Q8）。只在实际时长 < per_minutes 时生效。"""

    enabled: bool = True
    per_minutes: int = 10


class T1Item(_Item):
    type: Literal["T1"]
    per: int = Field(gt=0)
    free: int = Field(ge=0, default=0)
    normalize: Normalize | None = None


class T2Item(_Item):
    type: Literal["T2"]
    award: int | None = Field(default=None, gt=0)  # 统一加分
    awards: dict[str, int] | None = None  # 按标签加分
    labels: list[str] | None = None  # 计分的标签；不在其中的实例不加分
    cap: int = Field(gt=0)
    distinct_by_label: bool = False  # 同一标签只算一次

    @model_validator(mode="after")
    def _check(self) -> "T2Item":
        if (self.award is None) == (self.awards is None):
            raise ValueError(f"{self.id}: award 和 awards 必须且只能设置一个")
        if self.awards is not None and self.labels is not None:
            raise ValueError(f"{self.id}: 用 awards 时不要再设 labels")
        if self.cap != self.max:
            raise ValueError(f"{self.id}: cap ({self.cap}) 应等于满分 ({self.max})")
        return self


class T3T4Item(_Item):
    """S2：要点清单（T3）+ 结构等级（T4），讲错从整个条目扣（decisions.md C7）。"""

    type: Literal["T3+T4"]
    checklist_max: int = Field(gt=0)
    structure_levels: list[int]
    error_penalty: int = Field(gt=0)
    error_label: str = "error"
    penalty_scope: Literal["item"] = "item"

    @model_validator(mode="after")
    def _check(self) -> "T3T4Item":
        if self.structure_levels != sorted(self.structure_levels, reverse=True):
            raise ValueError(f"{self.id}: structure_levels 须从高到低")
        if self.checklist_max + self.structure_levels[0] != self.max:
            raise ValueError(f"{self.id}: checklist_max + 结构最高级 应等于满分")
        return self


class T4Item(_Item):
    type: Literal["T4"]
    parts: list[LevelPart]

    @model_validator(mode="after")
    def _check(self) -> "T4Item":
        ids = [p.id for p in self.parts]
        if len(set(ids)) != len(ids):
            raise ValueError(f"{self.id}: parts id 重复")
        if sum(p.levels[0] for p in self.parts) != self.max:
            raise ValueError(f"{self.id}: 各部分最高级之和应等于满分")
        return self


class T5Item(_Item):
    type: Literal["T5"]
    metric: str
    limit: float
    score_by_over: dict[str, int]  # {"0": 5, "1": 3, "2+": 0}

    @model_validator(mode="after")
    def _check(self) -> "T5Item":
        exact: dict[int, int] = {}
        open_from: int | None = None
        for k, v in self.score_by_over.items():
            if k.endswith("+"):
                if open_from is not None:
                    raise ValueError(f"{self.id}: score_by_over 只能有一个 N+")
                open_from = int(k[:-1])
            else:
                exact[int(k)] = v
            if not 0 <= v <= self.max:
                raise ValueError(f"{self.id}: score_by_over 分值超出 0–满分")
        if open_from is None or sorted(exact) != list(range(open_from)):
            raise ValueError(f"{self.id}: score_by_over 须连续覆盖 0..N-1 并以 N+ 结尾")
        return self

    def score_for(self, over: int) -> int:
        if str(over) in self.score_by_over:
            return self.score_by_over[str(over)]
        return next(v for k, v in self.score_by_over.items() if k.endswith("+"))


class T6Item(_Item):
    type: Literal["T6"]
    count: int = Field(gt=0)  # 题数
    levels: dict[str, int] | None = None  # 按等级给分（O5）
    elements: dict[str, int] | None = None  # 按要素给分（S3）
    zero_labels: list[str] = Field(default_factory=list)  # elements 模式：出现即本题 0 分

    @model_validator(mode="after")
    def _check(self) -> "T6Item":
        if (self.levels is None) == (self.elements is None):
            raise ValueError(f"{self.id}: levels 和 elements 必须且只能设置一个")
        per_q = max(self.levels.values()) if self.levels else sum(self.elements.values())  # type: ignore[union-attr]
        if per_q * self.count != self.max:
            raise ValueError(f"{self.id}: 每题满分 × 题数 应等于满分")
        if self.levels is None and self.zero_labels:
            overlap = set(self.zero_labels) & set(self.elements or {})
            if overlap:
                raise ValueError(f"{self.id}: zero_labels 与 elements 重名: {overlap}")
        return self

    @property
    def per_question_max(self) -> int:
        return max(self.levels.values()) if self.levels else sum(self.elements.values())  # type: ignore[union-attr]


Item = Annotated[Union[T1Item, T2Item, T3T4Item, T4Item, T5Item, T6Item], Field(discriminator="type")]


class Dimension(_Node):
    id: str
    name: str
    items: list[Item]


# ───────────────────────── 顶层 ─────────────────────────


class LowConfidence(_Node):
    default_threshold: float = Field(ge=0, le=1)


class Redlines(_Node):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    ids: list[str] = Field(alias="list")  # YAML 里沿用标准第 9 节的键名 list
    hit_threshold: float = Field(ge=0, le=1)
    per_redline_threshold: dict[str, float] = Field(default_factory=dict)
    exclude_segments: list[str] = Field(default_factory=list)

    def threshold_for(self, rid: str) -> float:
        return self.per_redline_threshold.get(rid, self.hit_threshold)


class Critical(_Node):
    review_band: int = Field(ge=0)
    total_rounds: int = Field(ge=1)

    @model_validator(mode="after")
    def _odd(self) -> "Critical":
        if self.total_rounds % 2 == 0:
            raise ValueError("total_rounds 须为奇数，避免平局")
        return self


class RubricConfig(_Node):
    version: str
    status: Literal["draft", "published"] = "draft"
    rounding: Literal["half_up"] = "half_up"
    grade_bands: list[tuple[int, int, int]]  # [下限, 上限, 档位]
    thresholds: dict[str, int]  # 总档位须小于该值
    critical: Critical
    low_confidence: LowConfidence
    redlines: Redlines
    removed_items: list[str] = Field(default_factory=list)
    expected_item_count: int | None = None
    dimensions: list[Dimension]

    @model_validator(mode="after")
    def _check(self) -> "RubricConfig":
        # 档位表须按分数从高到低、连续覆盖 0–100，档位从 1 起连续
        bands = self.grade_bands
        if bands[0][1] != 100 or bands[-1][0] != 0:
            raise ValueError("grade_bands 须覆盖 0–100")
        for i, (lo, hi, g) in enumerate(bands):
            if lo > hi:
                raise ValueError(f"grade_bands 第 {i + 1} 段下限大于上限")
            if g != i + 1:
                raise ValueError("grade_bands 档位须从 1 起连续，且按分数从高到低排列")
            if i and bands[i - 1][0] != hi + 1:
                raise ValueError("grade_bands 各段须首尾相接，不重叠不留空")
        if len(self.dimensions) != 4:
            raise ValueError("应有 4 个维度")
        ids = [it.id for d in self.dimensions for it in d.items]
        if len(set(ids)) != len(ids):
            raise ValueError("条目编号重复")
        if set(ids) & set(self.removed_items):
            raise ValueError("已删除条目不应出现在 dimensions 中")
        if self.expected_item_count is not None and len(ids) != self.expected_item_count:
            raise ValueError(f"条目数为 {len(ids)}，配置要求 {self.expected_item_count}")
        if len(set(self.redlines.ids)) != len(self.redlines.ids):
            raise ValueError("红线编号重复")
        if not set(self.redlines.per_redline_threshold) <= set(self.redlines.ids):
            raise ValueError("per_redline_threshold 含未列出的红线")
        if not self.thresholds:
            raise ValueError("thresholds 不能为空")
        return self

    # —— 便捷方法 ——
    def items(self):
        for d in self.dimensions:
            for it in d.items:
                yield d, it

    def grade_for(self, score: int) -> int:
        for lo, hi, g in self.grade_bands:
            if lo <= score <= hi:
                return g
        raise ConfigError(f"维度分 {score} 不在档位表内")

    def low_conf_threshold(self, item: Any) -> float:
        if item.low_confidence_threshold is not None:
            return item.low_confidence_threshold
        return self.low_confidence.default_threshold


# ───────────────────────── 加载与发布检查 ─────────────────────────


def parse_config(data: dict[str, Any]) -> RubricConfig:
    try:
        cfg = RubricConfig.model_validate(data)
    except Exception as exc:  # pydantic.ValidationError
        raise ConfigError(str(exc)) from exc
    if cfg.status == "published":
        ensure_publishable(cfg)  # 标为 published 的配置不能带待确认或占位标记
    return cfg


def load_config(path: str | Path) -> RubricConfig:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return parse_config(data)


def config_hash(cfg: RubricConfig) -> str:
    canonical = json.dumps(cfg.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _walk(node: Any, path: str, out: list[str]) -> None:
    if isinstance(node, dict):
        where = path or "(根)"
        if node.get("pending"):
            out.append(f"{where}: 待确认 {', '.join(node['pending'])}")
        if node.get("calibration_required"):
            out.append(f"{where}: 测试占位值，需校准")
        for k, v in node.items():
            if k in ("pending", "calibration_required"):
                continue
            key = v.get("id") if isinstance(v, dict) and "id" in v else k
            _walk(v, f"{path}.{key}" if path else str(key), out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            key = v.get("id") if isinstance(v, dict) and "id" in v else f"[{i}]"
            _walk(v, f"{path}.{key}" if path else str(key), out)


def publish_blockers(cfg: RubricConfig) -> list[str]:
    """列出阻止发布的原因。为空才能发布为正式评分配置。"""
    out: list[str] = []
    _walk(cfg.model_dump(mode="json"), "", out)
    return out


def ensure_publishable(cfg: RubricConfig) -> None:
    blockers = publish_blockers(cfg)
    if blockers:
        raise ConfigError("配置不能发布：\n" + "\n".join(f"- {b}" for b in blockers))
