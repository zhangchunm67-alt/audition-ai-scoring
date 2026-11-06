"""旧版 rubric-v0.1 的计分机制（卖点卡 + 结构、指标分档、计次分档、规则分档、等级修正、O5 逐题）。
现行配置不再使用这些写法，但已存报告可能按旧配置重算，计分引擎仍须支持。"""
import pytest

from scoring import EvidenceError, ScoringInputError, parse_config, score_round
from tests.scoring.helpers import CHECKLIST, item, item_raw, legacy_context, legacy_full_marks, legacy_raw, modified


def run(cfg, b, **ctx):
    return score_round(b.items, cfg, legacy_context(**ctx))


def test_legacy_full_marks(legacy_cfg):
    r = run(legacy_cfg, legacy_full_marks())
    assert r.status == "complete" and r.total_grade == 4
    assert [d.applicable_max for d in r.dimensions] == [95, 100, 100, 100]


# ───────────── T3+T4 产品讲解 ─────────────


def _s2(b, hits, structure, errors=0):
    b.remove("S2")
    for p in CHECKLIST:
        b.add("S2", "checklist_hit", ref=p.id, label=p.name, judgment="count" if p.id in hits else "not_count")
    b.level("S2", structure, ref="structure")
    for _ in range(errors):
        b.occ("S2", "error")


def test_t3t4_rubric_example_points_plus_structure(legacy_cfg):
    b = legacy_full_marks()
    hits = {"coverage", "ratio", "health", "exclusion", "renewal", "price"}  # 漏了免赔额、等待期
    _s2(b, hits, 14)
    res = item(run(legacy_cfg, b), "S2")
    assert res.score == 22 + 14
    assert "合规必讲要点未讲：免赔额" in res.notes and "合规必讲要点未讲：等待期" in res.notes


def test_t3t4_error_penalty_from_whole_item(legacy_cfg):
    """C7：讲错从整个 S2 扣。要点 5 + 结构 20 = 25，讲错 2 处 → 15。
    若只从要点部分扣，会是 max(0, 5-10) + 20 = 20。"""
    b = legacy_full_marks()
    _s2(b, {"coverage"}, 20, errors=2)
    res = item(run(legacy_cfg, b), "S2")
    assert res.score == 15
    _s2(b, {"coverage"}, 20, errors=6)
    assert item(run(legacy_cfg, b), "S2").score == 0  # 最低 0


def test_t3t4_missing_point_check_is_missing_not_zero(legacy_cfg):
    b = legacy_full_marks()
    b.remove("S2", kind="checklist_hit")
    b.add("S2", "checklist_hit", ref="coverage", label="保障范围", judgment="count")
    r = run(legacy_cfg, b)
    assert item(r, "S2").status == "missing_evidence"
    assert item(r, "S2").score is None
    assert r.status == "incomplete"


def test_t3t4_missing_structure(legacy_cfg):
    b = legacy_full_marks()
    b.remove("S2", kind="level")
    assert item(run(legacy_cfg, b), "S2").status == "missing_evidence"


def test_t3t4_card_sum_mismatch_raises(legacy_cfg):
    card = CHECKLIST[:-1]  # 合计 27
    with pytest.raises(ScoringInputError):
        b = legacy_full_marks()
        b.remove("S2", kind="checklist_hit")
        for p in card:
            b.add("S2", "checklist_hit", ref=p.id, label=p.name, judgment="count")
        score_round(b.items, legacy_cfg, legacy_context(checklist=card))


def test_t3t4_unknown_point_raises(legacy_cfg):
    b = legacy_full_marks()
    b.add("S2", "checklist_hit", ref="nonexistent", judgment="count")
    with pytest.raises(EvidenceError):
        run(legacy_cfg, b)


# ───────────── T4 分级锚定 ─────────────


def test_t4_evidence_level(legacy_cfg):
    b = legacy_full_marks()
    b.remove("P1")
    b.level("P1", 7, source="vision")
    assert item(run(legacy_cfg, b), "P1").score == 7


def test_t4_invalid_level_raises(legacy_cfg):
    b = legacy_full_marks()
    b.remove("S1")
    b.level("S1", 5)
    with pytest.raises(EvidenceError):
        run(legacy_cfg, b)


def test_t4_missing_level_is_missing(legacy_cfg):
    b = legacy_full_marks()
    b.remove("P1")
    r = run(legacy_cfg, b)
    assert item(r, "P1").status == "missing_evidence"
    assert r.total_grade is None


@pytest.mark.parametrize("v,level", [(100, 10), (90, 10), (89.9, 8), (80, 8), (79, 6), (70, 6), (69, 3), (60, 3), (59.9, 0), (0, 0)])
def test_t4_metric_bands_p3(legacy_cfg, v, level):
    b = legacy_full_marks()
    b.remove("P3")
    b.metric("P3", "reading_eval_score", v)
    assert item(run(legacy_cfg, b), "P3").score == level


@pytest.mark.parametrize("v,flag", [(92, True), (88, True), (85, False), (95, False)])
def test_t4_metric_boundary_flag(legacy_cfg, v, flag):
    b = legacy_full_marks()
    b.remove("P3")
    b.metric("P3", "reading_eval_score", v)
    res = item(run(legacy_cfg, b), "P3")
    assert res.low_confidence is flag
    assert res.status == "scored"


def test_t4_p3_missing_reading_eval_is_missing(legacy_cfg):
    b = legacy_full_marks()
    b.remove("P3")
    res = item(run(legacy_cfg, b), "P3")
    assert res.status == "missing_evidence" and res.score is None


def test_t4_accent_downgrade_disabled_by_default(legacy_cfg):
    b = legacy_full_marks()
    b.occ("P3", "accent_downgrade")
    assert item(run(legacy_cfg, b), "P3").score == 10
    data = modified(legacy_raw(), lambda d: item_raw(d, "P3")["parts"][0]["modifiers"][0].update(enabled=True))
    assert item(score_round(b.items, parse_config(data), legacy_context()), "P3").score == 8


@pytest.mark.parametrize("level,expected", [(20, 14), (14, 14), (8, 8), (0, 0)])
def test_t4_l1_hook_invalid_cap(legacy_cfg, level, expected):
    b = legacy_full_marks()
    b.remove("L1")
    b.level("L1", level)
    b.occ("L1", "hook_invalid")
    assert item(run(legacy_cfg, b), "L1").score == expected


@pytest.mark.parametrize("n,level,flag", [(0, 10, False), (1, 7, False), (2, 7, True), (3, 4, True), (4, 4, False), (5, 4, True), (6, 0, True), (9, 0, False)])
def test_t4_count_bands_p7(legacy_cfg, n, level, flag):
    b = legacy_full_marks()
    for i in range(n):
        b.occ("P7", "run_on" if i % 2 else "stall", source="audio")
    res = item(run(legacy_cfg, b), "P7")
    assert res.score == level
    assert res.low_confidence is flag


@pytest.mark.parametrize("pitch,loud,level", [(25, 12, 3), (10, 12, 5), (10, 5, 3), (5, 20, 3), (2, 20, 1)])
def test_t4_rules_p5(legacy_cfg, pitch, loud, level):
    b = legacy_full_marks()
    b.remove("P5")
    b.metric("P5", "pitch_range_st", pitch)
    b.metric("P5", "loudness_range_db", loud)
    assert item(run(legacy_cfg, b), "P5").score == level


def test_t4_rules_missing_metric(legacy_cfg):
    b = legacy_full_marks()
    b.remove("P5", label="loudness_range_db")
    assert item(run(legacy_cfg, b), "P5").status == "missing_evidence"


def test_t4_parts_o4(legacy_cfg):
    b = legacy_full_marks()
    b.remove("O4")
    for k, v in {"max_response_latency_s": 12, "returned_to_mainline_ratio": 0.5, "dead_air_count": 0,
                 "unanswered_objections": 0, "loudness_range_db": 6, "pitch_range_st": 3}.items():
        b.metric("O4", k, v)
    assert item(run(legacy_cfg, b), "O4").score == 5 + 4


def test_t4_duplicate_metric_raises(legacy_cfg):
    b = legacy_full_marks()
    b.metric("P3", "reading_eval_score", 80)
    with pytest.raises(EvidenceError):
        run(legacy_cfg, b)


def test_t6_o5_levels(legacy_cfg):
    b = legacy_full_marks()
    b.remove("O5")
    for q, lv in zip(["q-waiting", "q-med-vs-ci", "q3", "q4", "q5", "q6"], ["full", "partial", "zero", "full", "partial", "full"]):
        b.add("O5", "question", ref=q, judgment=lv)
    assert item(run(legacy_cfg, b), "O5").score == 5 + 3 + 0 + 5 + 3 + 5


def test_t6_o5_unanswered_question_without_evidence_is_missing(legacy_cfg):
    b = legacy_full_marks()
    b.items = [e for e in b.items if not (e.item_id == "O5" and e.ref == "q6")]
    assert item(run(legacy_cfg, b), "O5").status == "missing_evidence"


def test_t6_o5_duplicate_or_unknown(legacy_cfg):
    b = legacy_full_marks()
    b.add("O5", "question", ref="q3", judgment="zero")
    with pytest.raises(EvidenceError):
        run(legacy_cfg, b)
    b = legacy_full_marks()
    b.add("O5", "question", ref="q-other", judgment="zero")
    with pytest.raises(EvidenceError):
        run(legacy_cfg, b)




@pytest.mark.parametrize("add", [
    lambda b: b.level("P3", 10),  # P3 的等级来自评测分，不接受直接给等级
    lambda b: b.occ("P7", "unknown_label"),
    lambda b: b.metric("P5", "unused_metric", 1),
    lambda b: b.level("O4", 8, ref="tempo"),
    lambda b: b.level("P6", 5),  # v0.1 删除了 P6
])
def test_legacy_unused_evidence_rejected(legacy_cfg, add):
    b = legacy_full_marks()
    add(b)
    with pytest.raises(EvidenceError):
        run(legacy_cfg, b)
