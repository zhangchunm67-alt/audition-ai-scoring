"""测试数据构造。示例取自 docs/rubric.md（少儿医疗险卖点卡、异议示例、各条目计分说明）。"""
from __future__ import annotations

import copy
import itertools
from pathlib import Path

import pytest
import yaml

from scoring import ChecklistPoint, Evidence, ScoringContext, parse_config, score_round

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "rubric" / "rubric-v0.1.yaml"

# rubric 第 5 节 S2 要点示例
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
ALL_ITEMS = ["P1", "P2", "P3", "P4", "P5", "P7", "P8", "P9", "P10", "S1", "S2", "S3", "S4",
             "L1", "L2", "L3", "L4", "L5", "O1", "O2", "O3", "O4", "O5"]


def raw_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.fixture(scope="session")
def cfg():
    return parse_config(raw_config())


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


def full_marks(location: str = "studio") -> EvidenceBuilder:
    """所有条目满分的一组证据。"""
    b = EvidenceBuilder()
    b.level("P1", 10, source="vision")
    b.metric("P3", "reading_eval_score", 95)
    for m in range(10):
        b.metric("P4", "chars_per_min", 300, t=m * 60_000)
    b.metric("P5", "pitch_range_st", 10)
    b.metric("P5", "loudness_range_db", 12)
    if location == "studio":
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


def context(location: str = "studio", audience: str = "new_trial", completed=None, **kw) -> ScoringContext:
    base = dict(
        location=location,
        audience=audience,
        completed_detectors=set(ALL_ITEMS) | {"redlines"} if completed is None else set(completed),
        checklist=CHECKLIST,
        expected_questions={"S3": list(OBJECTIONS), "O5": list(QUESTIONS)},
        main_duration_ms=600_000,
        model_manifest={"asr": "mock-asr@1", "llm": "mock-llm@1", "prompt": "p-v1"},
    )
    base.update(kw)
    return ScoringContext(**base)


def item(result, item_id):
    return next(i for i in result.items if i.item_id == item_id)


def dim(result, dim_id):
    return next(d for d in result.dimensions if d.id == dim_id)


# 总档位构造：P1 + S? + L4 + O6 = 11 + S 档位（S2 每处讲错 -5，从 50 扣）
S2_ERRORS_FOR_S_GRADE = {1: 0, 2: 1, 3: 2, 4: 4, 5: 6, 6: 8, 7: 10}


def builder_for_total(total: int) -> EvidenceBuilder:
    """构造总档位为 total（4 或 12–18）的证据。"""
    b = full_marks()
    if total == 4:
        return b
    s_grade = total - 11
    for _ in range(S2_ERRORS_FOR_S_GRADE[s_grade]):
        b.occ("S2", "error")
    b.occ("L3", "deductive_error")
    b.occ("L3", "deductive_error")  # L = 80 → 4 档
    b.remove("O1")
    b.remove("O2")  # O = 60 → 6 档
    return b


@pytest.fixture
def round_for_total(cfg):
    def make(total: int, audience: str = "new_trial", redline: tuple[str, float] | None = None):
        b = builder_for_total(total)
        if redline:
            b.add(redline[0], "redline", judgment="count", confidence=redline[1], quote="稳赚不赔", segment="main")
        r = score_round(b.items, cfg, context(audience=audience))
        assert r.total_grade == total, r.total_grade
        return r

    return make


def modified(data: dict, fn) -> dict:
    d = copy.deepcopy(data)
    fn(d)
    return d
