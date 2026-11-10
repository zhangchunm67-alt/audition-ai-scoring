"""测试数据构造。现行配置 rubric-v0.3 按评分表 20261105；旧版 rubric-v0.1 的配置快照保留在 tests/fixtures，
用来继续测试计分引擎对旧报告（卖点卡 + 结构、指标分档、O5 等）的重算。示例取自少儿医疗险演示产品。"""
from __future__ import annotations

import copy
import itertools
from pathlib import Path

import pytest
import yaml

from scoring import ChecklistPoint, Evidence, ScoringContext, parse_config, score_round

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "rubric" / "rubric-v0.3.yaml"
LEGACY_CONFIG_PATH = ROOT / "tests" / "fixtures" / "rubric-v0.1.yaml"

# 旧版 rubric-v0.1 的 S2 要点示例（只用于旧配置的重算测试）
CHECKLIST = [
    ChecklistPoint(id="coverage", name="保障范围", points=5),
    ChecklistPoint(id="deductible", name="免赔额", points=4, compliance_required=True),
    ChecklistPoint(id="ratio", name="报销比例", points=3),
    ChecklistPoint(id="waiting", name="等待期", points=4, compliance_required=True),
    ChecklistPoint(id="health", name="健康告知", points=4, compliance_required=True),
    ChecklistPoint(id="exclusion", name="责任免除", points=3, compliance_required=True),
    ChecklistPoint(id="renewal", name="续保条件", points=4),
    ChecklistPoint(id="price", name="价格", points=3),
]
OBJECTIONS = ["obj-medicare", "obj-pneumonia", "obj-cheap", "obj-expensive"]  # rubric 第 2 节异议示例
QUESTIONS = ["q-waiting", "q-med-vs-ci", "q3", "q4", "q5", "q6"]
ALL_ITEMS = ["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9", "P10", "S1", "S2", "S3", "S4",
             "L1", "L2", "L3", "L4", "L5", "O1", "O2", "O3", "O4"]
LEGACY_ITEMS = ["P1", "P2", "P3", "P4", "P5", "P7", "P8", "P9", "P10", "S1", "S2", "S3", "S4",
                "L1", "L2", "L3", "L4", "L5", "O1", "O2", "O3", "O4", "O5"]


def raw_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def legacy_raw() -> dict:
    with open(LEGACY_CONFIG_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.fixture(scope="session")
def cfg():
    return parse_config(raw_config())


@pytest.fixture(scope="session")
def legacy_cfg():
    return parse_config(legacy_raw())


def rl_raw() -> dict:
    """打开红线的配置（C33 后试镜默认关闭；红线逻辑保留给以后的直播评分，照样要测）。"""
    d = raw_config()
    d["redlines"]["enabled"] = True
    return d


@pytest.fixture(scope="session")
def rl_cfg():
    return parse_config(rl_raw())


def item_raw(data: dict, item_id: str) -> dict:
    for d in data["dimensions"]:
        for it in d["items"]:
            if it["id"] == item_id:
                return it
    raise KeyError(item_id)


class EvidenceBuilder:
    def __init__(self) -> None:
        self._n = itertools.count(1)
        self.items: list[Evidence] = []

    def add(self, item_id: str, kind: str, *, confidence: float = 0.9, source: str = "llm", t: int | None = None, **kw) -> Evidence:
        n = next(self._n)
        start = t if t is not None else n * 1000
        e = Evidence(
            evidence_id=f"e-{n:04d}", item_id=item_id, kind=kind, start_ms=start, end_ms=start + 800,
            confidence=confidence, source=source, **kw,
        )
        self.items.append(e)
        return e

    def occ(self, item_id: str, label: str = "x", judgment: str = "count", **kw):
        return self.add(item_id, "occurrence", label=label, judgment=judgment, **kw)

    def inst(self, item_id: str, label: str = "x", judgment: str = "count", **kw):
        return self.add(item_id, "instance", label=label, judgment=judgment, **kw)

    def level(self, item_id: str, level: int, ref: str | None = None, **kw):
        return self.add(item_id, "level", judgment=level, ref=ref, **kw)

    def metric(self, item_id: str, label: str, value: float, **kw):
        return self.add(item_id, "metric", label=label, value=value, source="audio", **kw)

    def remove(self, item_id: str, kind: str | None = None, label: str | None = None) -> None:
        self.items = [
            e for e in self.items
            if not (e.item_id == item_id and (kind is None or e.kind == kind) and (label is None or e.label == label))
        ]


def full_marks(props: bool = True) -> EvidenceBuilder:
    """rubric-v0.3 所有条目满分的一组证据。"""
    b = EvidenceBuilder()
    b.occ("P1", "attire", judgment="not_count", source="vision")
    b.occ("P1", "hairstyle", judgment="not_count", source="vision")
    b.occ("P3", "mispronounce", judgment="not_count", source="audio")  # 发音不准不扣分（P-P3-PRON）
    for m in range(10):
        b.metric("P4", "chars_per_min", 300, t=m * 60_000)
    b.level("P5", 5, source="audio")
    b.level("P6", 5, source="audio")
    b.level("P7", 10, source="audio")
    if props:
        for _ in range(3):
            b.inst("P9", "sticker", source="vision")
    b.level("S1", 10)
    b.level("S2", 50, ref="fixed_script_accuracy", label="fixed_script=s1;calibration=c1")
    for o in OBJECTIONS:
        for el in ("direct_answer", "advantage", "altruistic_close"):
            b.add("S3", "question", ref=o, label=el, judgment="count")
    for m in ("herd", "loss_aversion", "authority", "sunk_cost"):
        b.inst("S4", m)
    b.level("L1", 20)
    for it in ("L2", "L4", "L5"):
        b.inst(it)
        b.inst(it)
    for term in ("免赔额", "等待期", "既往症"):
        b.inst("O1", term)
    for pt in ("儿童医院可用", "门急诊不限次", "雾化可报"):
        b.inst("O2", pt)
    for _ in range(2):
        b.inst("O3")
    b.level("O4", 20)
    return b


def context(props: bool = True, audience: str = "new_trial", completed=None, **kw) -> ScoringContext:
    base = dict(
        props_available=props,
        audience=audience,
        completed_detectors=set(ALL_ITEMS) | {"redlines"} if completed is None else set(completed),
        expected_questions={"S3": list(OBJECTIONS)},
        main_duration_ms=600_000,
        model_manifest={"asr": "mock-asr@1", "llm": "mock-llm@1", "prompt": "p-v1"},
    )
    base.update(kw)
    return ScoringContext(**base)


def legacy_full_marks(props: bool = True) -> EvidenceBuilder:
    """旧版 rubric-v0.1 所有条目满分的一组证据。"""
    b = EvidenceBuilder()
    b.level("P1", 10, source="vision")
    b.metric("P3", "reading_eval_score", 95)
    for m in range(10):
        b.metric("P4", "chars_per_min", 300, t=m * 60_000)
    b.metric("P5", "pitch_range_st", 10)
    b.metric("P5", "loudness_range_db", 12)
    if props:
        for _ in range(3):
            b.inst("P9", "sticker", source="vision")
    b.level("S1", 10)
    for p in CHECKLIST:
        b.add("S2", "checklist_hit", ref=p.id, label=p.name, judgment="count")
    b.level("S2", 20, ref="structure")
    for o in OBJECTIONS:
        for el in ("direct_answer", "advantage", "altruistic_close"):
            b.add("S3", "question", ref=o, label=el, judgment="count")
    for m in ("herd", "loss_aversion", "authority", "price_split"):
        b.inst("S4", m)
    b.level("L1", 20)
    for it in ("L2", "L4", "L5"):
        b.inst(it)
        b.inst(it)
    for term in ("免赔额", "等待期", "既往症", "续保"):
        b.inst("O1", term)
    for pt in ("儿童医院可用", "门急诊不限次", "雾化可报", "外购药可报"):
        b.inst("O2", pt)
    for _ in range(3):
        b.inst("O3")
    for k, v in {"max_response_latency_s": 3, "returned_to_mainline_ratio": 1, "dead_air_count": 0,
                 "unanswered_objections": 0, "loudness_range_db": 12, "pitch_range_st": 10}.items():
        b.metric("O4", k, v)
    for q in QUESTIONS:
        b.add("O5", "question", ref=q, judgment="full")
    return b


def legacy_context(**kw) -> ScoringContext:
    base = dict(completed=set(LEGACY_ITEMS) | {"redlines"}, checklist=CHECKLIST,
                expected_questions={"S3": list(OBJECTIONS), "O5": list(QUESTIONS)})
    base.update(kw)
    return context(**base)


def item(result, item_id):
    return next(i for i in result.items if i.item_id == item_id)


def dim(result, dim_id):
    return next(d for d in result.dimensions if d.id == dim_id)


# 总档位构造：P1 + S? + L4 + O6 = 11 + S 档位。S 维度 = 50 + S2 分，按 S2 分取得 S 的 1–7 档
S2_FOR_S_GRADE = {1: 50, 2: 42, 3: 35, 4: 25, 5: 15, 6: 5, 7: 0}


def builder_for_total(total: int) -> EvidenceBuilder:
    """构造总档位为 total（4 或 12–18）的证据。"""
    b = full_marks()
    if total == 4:
        return b
    b.remove("S2")
    b.level("S2", S2_FOR_S_GRADE[total - 11], ref="fixed_script_accuracy")
    b.occ("L3", "deductive_error")
    b.occ("L3", "deductive_error")  # L = 80 → 4 档
    b.remove("O1")
    b.remove("O3")
    b.inst("O3")  # O = 0 + 30 + 10 + 20 = 60 → 6 档
    return b


@pytest.fixture
def round_for_total(cfg):
    def make(total: int, audience: str = "new_trial", redline: tuple[str, float] | None = None, config=None):
        b = builder_for_total(total)
        if redline:
            b.add(redline[0], "redline", judgment="count", confidence=redline[1], quote="稳赚不赔", segment="main")
        r = score_round(b.items, config or cfg, context(audience=audience))
        assert r.total_grade == total, r.total_grade
        return r

    return make


def modified(data: dict, fn) -> dict:
    d = copy.deepcopy(data)
    fn(d)
    return d
