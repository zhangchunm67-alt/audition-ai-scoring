"""计分引擎的输入输出类型。

证据结构按 docs/rubric.md 第 9 节；扩展字段（ref、value、segment）见 docs/decisions.md I6。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

EvidenceKind = Literal[
    "occurrence",  # 逐次
    "instance",  # 加分实例
    "checklist_hit",  # 要点
    "level",  # 等级
    "question",  # 逐题
    "metric",  # 指标
    "redline",  # 红线
]
EvidenceSource = Literal["rule", "llm", "audio", "vision", "human"]
ReviewStatus = Literal["pending", "confirmed", "overridden", "rejected"]

COUNT = "count"
NOT_COUNT = "not_count"


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ReviewStatus = "pending"
    reviewer: str | None = None
    override: Any = None
    note: str | None = None


class Evidence(BaseModel):
    """一条证据。检测器只产出它，不产出分数。"""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    item_id: str  # 条目编号（P2、S3…）或红线编号（R1–R8）
    kind: EvidenceKind
    start_ms: int | None = None
    end_ms: int | None = None
    quote: str | None = None
    label: str | None = None
    judgment: str | int | float | None = None
    reason: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    source: EvidenceSource
    review: Review = Field(default_factory=Review)
    # —— 扩展字段（decisions.md I6）——
    ref: str | None = None  # 要点 id / 题目或异议 id / 子项（structure、rhythm…）
    value: float | None = None  # 指标数值（kind=metric）
    segment: str | None = None  # main / question / reading

    def effective_judgment(self) -> Any:
        """人工改过的证据取 override，其余取模型判定。"""
        if self.review.status == "overridden":
            return self.review.override
        return self.judgment

    @property
    def excluded(self) -> bool:
        return self.review.status == "rejected"


class ChecklistPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    points: int = Field(ge=0)
    compliance_required: bool = False


class ScoringContext(BaseModel):
    """一次计分需要的录制上下文。由流水线根据批次和录制记录填好。"""

    model_config = ConfigDict(extra="forbid")

    props_available: bool  # 画面里有无贴片 / KT 板（C26）：决定 P9 是否适用
    audience: str  # 达标线键：veteran / month_1 / new_trial
    completed_detectors: set[str]  # 已成功运行的检测器：条目编号，以及 "redlines"
    checklist: list[ChecklistPoint] = Field(default_factory=list)  # 卖点卡必讲要点（S2）
    expected_questions: dict[str, list[str]] = Field(default_factory=dict)  # {"S3": [异议 id], "O5": [题目 id]}
    main_duration_ms: int | None = None
    model_manifest: dict[str, Any] = Field(default_factory=dict)  # 模型版本清单，原样写入结果


class Contribution(BaseModel):
    """某条证据对条目分的贡献，供逐句评分展示（M5-6）。"""

    evidence_id: str
    delta: float
    note: str


class ItemResult(BaseModel):
    item_id: str
    name: str
    dimension: str
    type: str
    status: Literal["scored", "not_applicable", "missing_evidence"]
    score: float | None
    max: int
    low_confidence: bool = False
    low_confidence_reasons: list[str] = Field(default_factory=list)
    missing_reasons: list[str] = Field(default_factory=list)
    contributions: list[Contribution] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class DimensionResult(BaseModel):
    id: str
    name: str
    status: Literal["scored", "incomplete"]
    raw: float | None
    applicable_max: int
    scaled: float | None  # 折算到 100、取整前
    score: int | None  # 取整后
    grade: int | None


class RedlineHit(BaseModel):
    redline_id: str
    evidence_id: str
    quote: str | None
    start_ms: int | None
    end_ms: int | None
    confidence: float
    threshold: float
    reason: str | None


class RoundResult(BaseModel):
    """一轮计分的结果。"""

    rubric_version: str
    config_hash: str
    status: Literal["complete", "incomplete"]
    items: list[ItemResult]
    dimensions: list[DimensionResult]
    total_grade: int | None
    audience: str
    threshold: int
    grade_pass: bool | None  # 只看总档位是否达标，不含红线
    critical: bool | None
    redlines_completed: bool
    redline_hits: list[RedlineHit]
    redline_below_threshold: list[RedlineHit]  # 判为红线但置信度未达阈值，只展示不影响结论
    missing_items: list[str]
    low_confidence_items: list[str]
    model_manifest: dict[str, Any]

    @property
    def conclusion_pass(self) -> bool | None:
        """本轮结论：达标 = 总档位达标且无红线。"""
        if self.status != "complete":
            return None
        return bool(self.grade_pass) and not self.redline_hits


Label = Literal["recommend", "pending", "not_recommend"]
LABEL_ZH: dict[str, str] = {"recommend": "推荐", "pending": "待定", "not_recommend": "不推荐"}


class RoundSummary(BaseModel):
    round_no: int
    total_grade: int
    grade_pass: bool
    redline_ids: list[str]
    dimension_scores: dict[str, int]
    dimension_grades: dict[str, int]


class FinalVerdict(BaseModel):
    status: Literal["complete", "incomplete", "needs_more_rounds"]
    conclusion: Literal["pass", "fail"] | None = None
    label: Label | None = None
    label_zh: str | None = None
    reason: str | None = None
    critical: bool = False
    redline_hit: bool = False
    redline_hits: list[tuple[int, RedlineHit]] = Field(default_factory=list)  # (轮次, 命中)
    majority_grade_pass: bool | None = None
    display_round: int | None = None  # 报告展示哪一轮（从 1 计）
    rounds: list[RoundSummary] = Field(default_factory=list)
    rounds_required: int = 1
    rounds_received: int = 0
    message: str | None = None
