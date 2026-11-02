"""维度折算、取整、档位、达标线、临界、红线、低置信、缺失证据、可追溯。"""
from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st

from scoring import EvidenceError, ScoringInputError, config_hash, parse_config, round_half_up, score_round
from scoring.types import Review
from tests.scoring.helpers import ALL_ITEMS, context, dim, full_marks, item, item_raw, modified, raw_config


# ───────────── 取整与档位 ─────────────


@pytest.mark.parametrize("x,expected", [(Fraction(905, 10), 91), (Fraction(895, 10), 90), (Fraction(1, 2), 1),
                                        (Fraction(5, 2), 3), (Fraction(8947, 100), 89), (Fraction(0), 0), (Fraction(100), 100)])
def test_round_half_up(x, expected):
    assert round_half_up(x) == expected  # 内置 round(90.5) == 90，这里必须是 91


@given(st.fractions(min_value=0, max_value=100))
def test_round_half_up_property(x):
    r = round_half_up(x)
    assert x - Fraction(1, 2) < r <= x + Fraction(1, 2)


@pytest.mark.parametrize("score,grade", [(100, 1), (96, 1), (95, 2), (91, 2), (90, 3), (81, 3), (80, 4), (71, 4),
                                         (70, 5), (61, 5), (60, 6), (51, 6), (50, 7), (41, 7), (40, 8), (0, 8)])
def test_grade_bands(cfg, score, grade):
    assert cfg.grade_for(score) == grade


# ───────────── 人设塑造折算（P0 验收：按 95 满分正确折算） ─────────────


def _p_with_deductions(n_p2: int, props: bool = True):
    b = full_marks(props)
    for _ in range(20 + n_p2):
        b.occ("P2", "那么")
    return b


@pytest.mark.parametrize("deduct,raw,scaled_int,grade", [
    (0, 95, 100, 1),
    (4, 91, 96, 1),   # 91 ÷ 95 × 100 = 95.79 → 96 → 1 档
    (5, 90, 95, 2),   # 94.74 → 95 → 2 档
    (10, 85, 89, 3),  # 89.47 → 89 → 3 档
    (19, 76, 80, 4),  # 80.00
    (40, 55, 58, 6),  # 57.89 → 58
])
def test_persona_scaled_from_95_with_props(cfg, deduct, raw, scaled_int, grade):
    r = score_round(_p_with_deductions(deduct).items, cfg, context())
    p = dim(r, "P")
    assert p.applicable_max == 95
    assert p.raw == raw
    assert p.scaled == pytest.approx(raw * 100 / 95)
    assert p.score == scaled_int
    assert p.grade == grade


@pytest.mark.parametrize("deduct,raw,scaled_int,grade", [
    (0, 90, 100, 1),
    (4, 86, 96, 1),   # 86 ÷ 90 × 100 = 95.56 → 96
    (5, 85, 94, 2),   # 94.44 → 94
    (9, 81, 90, 3),
    (10, 80, 89, 3),  # 88.89 → 89
])
def test_persona_no_props_p9_not_applicable_scaled_from_90(cfg, deduct, raw, scaled_int, grade):
    r = score_round(_p_with_deductions(deduct, props=False).items, cfg, context(props=False))
    assert item(r, "P9").status == "not_applicable"
    p = dim(r, "P")
    assert (p.applicable_max, p.raw, p.score, p.grade) == (90, raw, scaled_int, grade)


def test_no_props_ignores_p9_evidence(cfg):
    b = full_marks(props=True)  # 带了 P9 证据
    r = score_round(b.items, cfg, context(props=False))
    assert item(r, "P9").status == "not_applicable" and item(r, "P9").score is None
    assert dim(r, "P").raw == 90 and dim(r, "P").score == 100


def test_props_available_but_unused_scores_zero_for_p9(cfg):
    b = full_marks(props=False)  # 有道具但没有正确使用的证据
    r = score_round(b.items, cfg, context(props=True))
    assert item(r, "P9").score == 0
    assert dim(r, "P").score == round_half_up(Fraction(90 * 100, 95))  # 94.74 → 95


def test_other_dimensions_max_100(cfg):
    r = score_round(full_marks().items, cfg, context())
    assert [(d.id, d.applicable_max) for d in r.dimensions] == [("P", 95), ("S", 100), ("L", 100), ("O", 100)]


# ───────────── 总档位、达标线、临界 ─────────────


@pytest.mark.parametrize("total,passed,critical", [
    (4, True, False), (12, True, False), (13, True, True), (14, True, True),
    (15, False, True), (16, False, True), (17, False, False), (18, False, False),
])
def test_new_trial_threshold_and_critical(round_for_total, total, passed, critical):
    r = round_for_total(total)
    assert r.threshold == 15
    assert r.grade_pass is passed
    assert r.critical is critical


@pytest.mark.parametrize("audience,threshold", [("veteran", 8), ("month_1", 10)])
def test_other_thresholds(round_for_total, audience, threshold):
    for total in (12, 13, 14):
        r = round_for_total(total, audience=audience)
        assert r.threshold == threshold and r.grade_pass is False and r.critical is False


def test_threshold_examples_from_rubric(cfg):
    """rubric 第 1 节“刚好达标”的例子：1+2+2+2=7 < 8，2+2+2+3=9 < 10，3+3+4+4=14 < 15。"""
    for grades, aud in [((1, 2, 2, 2), "veteran"), ((2, 2, 2, 3), "month_1"), ((3, 3, 4, 4), "new_trial")]:
        thr = cfg.thresholds[aud]
        assert sum(grades) < thr and sum(grades) + 1 >= thr
        band = cfg.critical.review_band
        assert thr - band <= sum(grades) <= thr + band - 1  # 刚好达标的都属于临界


def test_critical_band_veteran_and_month1(cfg):
    band = cfg.critical.review_band
    assert [t for t in range(4, 33) if 8 - band <= t <= 8 + band - 1] == [6, 7, 8, 9]
    assert [t for t in range(4, 33) if 10 - band <= t <= 10 + band - 1] == [8, 9, 10, 11]
    assert [t for t in range(4, 33) if 15 - band <= t <= 15 + band - 1] == [13, 14, 15, 16]


def test_unknown_audience(cfg):
    with pytest.raises(ScoringInputError):
        score_round(full_marks().items, cfg, context(audience="intern"))


# ───────────── 红线 ─────────────


def _with_redline(cfg, judgment="count", confidence=0.85, segment="main", review=None, rid="R1"):
    b = full_marks()
    e = b.add(rid, "redline", judgment=judgment, confidence=confidence, quote="这款稳赚不赔", segment=segment, reason="承诺收益")
    if review:
        e.review = review
    return score_round(b.items, cfg, context())


def test_redline_hit_at_threshold(cfg):
    r = _with_redline(cfg, confidence=0.8)
    assert [h.redline_id for h in r.redline_hits] == ["R1"]
    assert r.redline_hits[0].quote == "这款稳赚不赔"
    assert r.conclusion_pass is False
    assert r.total_grade == 4 and r.grade_pass is True  # 分数照常计算


def test_redline_below_threshold_not_hit(cfg):
    r = _with_redline(cfg, confidence=0.79)
    assert not r.redline_hits and [h.confidence for h in r.redline_below_threshold] == [0.79]
    assert r.conclusion_pass is True


def test_redline_not_count_ignored(cfg):
    r = _with_redline(cfg, judgment="not_count", confidence=0.99)
    assert not r.redline_hits and not r.redline_below_threshold


def test_redline_reading_segment_excluded(cfg):
    r = _with_redline(cfg, segment="reading", confidence=0.99)
    assert not r.redline_hits


def test_redline_per_redline_threshold(cfg):
    data = modified(raw_config(), lambda d: d["redlines"].update(per_redline_threshold={"R8": 0.95}))
    c = parse_config(data)
    b = full_marks()
    b.add("R8", "redline", judgment="count", confidence=0.9, quote="加我微信单独聊")
    assert not score_round(b.items, c, context()).redline_hits


def test_redline_rejected_and_overridden(cfg):
    assert not _with_redline(cfg, review=Review(status="rejected")).redline_hits
    r = _with_redline(cfg, confidence=0.3, review=Review(status="overridden", override="count", reviewer="cal-1"))
    assert r.redline_hits


def test_unknown_redline_raises(cfg):
    with pytest.raises(EvidenceError):
        _with_redline(cfg, rid="R9")


def test_redline_detector_incomplete(cfg):
    r = score_round(full_marks().items, cfg, context(completed=ALL_ITEMS))
    assert r.status == "incomplete" and "redlines" in r.missing_items
    assert r.total_grade == 4  # 分数仍可算，但本轮不出结论
    assert r.conclusion_pass is None


# ───────────── 低置信 ─────────────


def test_low_confidence_flagged_score_unchanged(cfg):
    b = full_marks()
    b.remove("P1")
    b.level("P1", 7, confidence=0.4, source="vision")
    r = score_round(b.items, cfg, context())
    res = item(r, "P1")
    assert res.score == 7 and res.low_confidence and "P1" in r.low_confidence_items
    assert r.status == "complete"


def test_low_confidence_item_override(cfg):
    data = modified(raw_config(), lambda d: item_raw(d, "P1").update(low_confidence_threshold=0.95))
    r = score_round(full_marks().items, parse_config(data), context())
    assert item(r, "P1").low_confidence


# ───────────── 缺失证据与检测失败 ─────────────


def test_detector_failure_is_not_a_clean_score(cfg):
    """P2 检测器失败：不能当作“0 次口头禅”给满分。"""
    done = set(ALL_ITEMS) - {"P2"} | {"redlines"}
    r = score_round(full_marks().items, cfg, context(completed=done))
    p2 = item(r, "P2")
    assert p2.status == "missing_evidence" and p2.score is None
    assert dim(r, "P").status == "incomplete" and r.total_grade is None and r.critical is None
    assert r.status == "incomplete" and "P2" in r.missing_items


def test_detector_completed_with_no_events_scores_full(cfg):
    r = score_round(full_marks().items, cfg, context())
    assert item(r, "P2").score == 40 and item(r, "P2").status == "scored"


def test_not_applicable_item_needs_no_detector(cfg):
    done = set(ALL_ITEMS) - {"P9"} | {"redlines"}
    r = score_round(full_marks(props=False).items, cfg, context(props=False, completed=done))
    assert r.status == "complete"


# ───────────── 证据校验 ─────────────


def test_evidence_for_removed_item_p6_rejected(cfg):
    b = full_marks()
    b.level("P6", 5)
    with pytest.raises(EvidenceError):
        score_round(b.items, cfg, context())


def test_wrong_kind_rejected(cfg):
    b = full_marks()
    b.inst("P2", "那么")
    with pytest.raises(EvidenceError):
        score_round(b.items, cfg, context())


def test_bad_binary_judgment_rejected(cfg):
    b = full_marks()
    b.occ("P2", "那么", judgment="maybe")
    with pytest.raises(EvidenceError):
        score_round(b.items, cfg, context())


def test_duplicate_evidence_id_rejected(cfg):
    b = full_marks()
    b.items.append(b.items[0])
    with pytest.raises(EvidenceError):
        score_round(b.items, cfg, context())


# ───────────── 可追溯与“只改配置” ─────────────


def test_traceability_fields(cfg):
    r = score_round(full_marks().items, cfg, context())
    assert r.rubric_version == "rubric-v0.1"
    assert r.config_hash == config_hash(cfg) and r.config_hash.startswith("sha256:")
    assert r.model_manifest == {"asr": "mock-asr@1", "llm": "mock-llm@1", "prompt": "p-v1"}
    for i in r.items:
        if i.status == "scored":
            assert set(c.evidence_id for c in i.contributions) <= set(i.evidence_ids)


def test_rule_change_only_in_config_same_evidence(cfg):
    b = full_marks()
    for _ in range(25):
        b.occ("P2", "那么")
    before = item(score_round(b.items, cfg, context()), "P2").score
    data = modified(raw_config(), lambda d: item_raw(d, "P2").update(free=10))
    c2 = parse_config(data)
    after = item(score_round(b.items, c2, context()), "P2").score
    assert (before, after) == (35, 25)
    assert config_hash(c2) != config_hash(cfg)


def test_engine_is_pure(cfg):
    b = full_marks()
    snapshot = [e.model_copy(deep=True) for e in b.items]
    r1 = score_round(b.items, cfg, context())
    r2 = score_round(b.items, cfg, context())
    assert r1 == r2 and b.items == snapshot
