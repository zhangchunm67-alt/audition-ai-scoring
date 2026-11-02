"""T1–T6 六种计分类型。"""
import pytest

from scoring import EvidenceError, ScoringInputError, parse_config, score_round
from scoring.types import Review
from tests.scoring.helpers import CHECKLIST, context, full_marks, item, item_raw, modified, raw_config


def run(cfg, b, **ctx):
    return score_round(b.items, cfg, context(**ctx))


def test_full_marks_baseline(cfg):
    r = run(cfg, full_marks())
    assert r.status == "complete"
    assert all(i.score == i.max for i in r.items), [(i.item_id, i.score, i.missing_reasons) for i in r.items if i.score != i.max]
    assert [d.score for d in r.dimensions] == [100, 100, 100, 100]
    assert r.total_grade == 4


# ───────────── T1 逐次扣分 ─────────────


@pytest.mark.parametrize("n,expected", [(0, 40), (20, 40), (21, 39), (25, 35), (59, 1), (60, 0), (75, 0)])
def test_t1_p2_free_20(cfg, n, expected):
    b = full_marks()
    for _ in range(n):
        b.occ("P2", "那么")
    assert item(run(cfg, b), "P2").score == expected


def test_t1_not_count_rejected_and_overridden(cfg):
    b = full_marks()
    for _ in range(22):
        b.occ("P2", "一个")
    b.occ("P2", "一个", judgment="not_count")  # 真实数量“一个孩子”，不算
    rej = b.occ("P2", "是……的")
    rej.review = Review(status="rejected")
    ov = b.occ("P2", "那么")
    ov.review = Review(status="overridden", override="not_count", reviewer="cal-1")
    assert item(run(cfg, b), "P2").score == 38


def test_t1_contributions_chronological(cfg):
    b = full_marks()
    for i in range(22):
        b.occ("P2", "那么", t=100_000 + i * 1000)
    res = item(run(cfg, b), "P2")
    deltas = [c.delta for c in res.contributions]
    assert deltas[:20] == [0] * 20 and deltas[20:] == [-1, -1]
    assert sum(deltas) == res.score - res.max


def test_t1_l3_and_p10(cfg):
    b = full_marks()
    b.occ("L3", "deductive_error")
    b.occ("P10", "laugh")
    r = run(cfg, b)
    assert item(r, "L3").score == 10
    assert item(r, "P10").score == 0
    b.occ("L3", "deductive_error")
    b.occ("L3", "deductive_error")
    assert item(run(cfg, b), "L3").score == 0  # 最低 0


def test_t1_p8_per_one(cfg):
    b = full_marks()
    for _ in range(3):
        b.occ("P8", "touch_face", source="vision")
    assert item(run(cfg, b), "P8").score == 2


def test_t1_normalize_short_main_segment(cfg):
    """Q8 默认（待确认）：不足 10 分钟时次数 × 10 ÷ 实际分钟数。"""
    b = full_marks()
    for _ in range(15):
        b.occ("P2", "那么")
    r = run(cfg, b, main_duration_ms=300_000)  # 5 分钟：15 × 2 = 30 次
    assert item(r, "P2").score == 30
    assert item(run(cfg, b, main_duration_ms=600_000), "P2").score == 40
    assert item(run(cfg, b, main_duration_ms=720_000), "P2").score == 40  # 超过 10 分钟不换算


def test_t1_normalize_needs_duration(cfg):
    r = run(cfg, full_marks(), main_duration_ms=None)
    assert item(r, "P2").status == "missing_evidence"
    assert r.status == "incomplete"


# ───────────── T2 逐次加分 ─────────────


def test_t2_p9_awards_and_cap(cfg):
    b = full_marks()
    b.remove("P9")
    b.inst("P9", "sticker")
    assert item(run(cfg, b), "P9").score == 2
    b.inst("P9", "kt_board")
    assert item(run(cfg, b), "P9").score == 3
    b.inst("P9", "sticker")
    b.inst("P9", "kt_board")
    res = item(run(cfg, b), "P9")
    assert res.score == 5  # 2+1+2+1=6，封顶 5
    assert [c.delta for c in res.contributions] == [2, 1, 2, 0]


def test_t2_s4_distinct_methods_and_unscored_label(cfg):
    b = full_marks()
    b.remove("S4")
    b.inst("S4", "herd")
    b.inst("S4", "herd")  # 同一方法重复不加分
    b.inst("S4", "sunk_cost")  # 沉没成本暂不计分
    b.inst("S4", "price_split", judgment="not_count")  # 算错的价格拆分
    res = item(run(cfg, b), "S4")
    assert res.score == 5
    assert any("不计分" in c.note for c in res.contributions)


def test_t2_o1_distinct_terms_and_o3_cap(cfg):
    b = full_marks()
    b.remove("O1")
    b.inst("O1", "免赔额")
    b.inst("O1", "免赔额")
    b.inst("O1", "等待期")
    for _ in range(5):
        b.inst("O3")
    r = run(cfg, b)
    assert item(r, "O1").score == 10
    assert item(r, "O3").score == 15


def test_t2_l2_ten_each(cfg):
    b = full_marks()
    b.remove("L2")
    b.inst("L2")
    assert item(run(cfg, b), "L2").score == 10
    b.remove("L2")
    assert item(run(cfg, b), "L2").score == 0  # 检测器已完成且没有实例：0 分是真实结果


# ───────────── T3+T4 产品讲解 ─────────────


def _s2(b, hits, structure, errors=0):
    b.remove("S2")
    for p in CHECKLIST:
        b.add("S2", "checklist_hit", ref=p.id, label=p.name, judgment="count" if p.id in hits else "not_count")
    b.level("S2", structure, ref="structure")
    for _ in range(errors):
        b.occ("S2", "error")


def test_t3t4_rubric_example_points_plus_structure(cfg):
    b = full_marks()
    hits = {"coverage", "ratio", "health", "exclusion", "renewal", "price"}  # 漏了免赔额、等待期
    _s2(b, hits, 14)
    res = item(run(cfg, b), "S2")
    assert res.score == 22 + 14
    assert "合规必讲要点未讲：免赔额" in res.notes and "合规必讲要点未讲：等待期" in res.notes


def test_t3t4_error_penalty_from_whole_item(cfg):
    """C7：讲错从整个 S2 扣。要点 5 + 结构 20 = 25，讲错 2 处 → 15。
    若只从要点部分扣，会是 max(0, 5-10) + 20 = 20。"""
    b = full_marks()
    _s2(b, {"coverage"}, 20, errors=2)
    res = item(run(cfg, b), "S2")
    assert res.score == 15
    _s2(b, {"coverage"}, 20, errors=6)
    assert item(run(cfg, b), "S2").score == 0  # 最低 0


def test_t3t4_missing_point_check_is_missing_not_zero(cfg):
    b = full_marks()
    b.remove("S2", kind="checklist_hit")
    b.add("S2", "checklist_hit", ref="coverage", label="保障范围", judgment="count")
    r = run(cfg, b)
    assert item(r, "S2").status == "missing_evidence"
    assert item(r, "S2").score is None
    assert r.status == "incomplete"


def test_t3t4_missing_structure(cfg):
    b = full_marks()
    b.remove("S2", kind="level")
    assert item(run(cfg, b), "S2").status == "missing_evidence"


def test_t3t4_card_sum_mismatch_raises(cfg):
    card = CHECKLIST[:-1]  # 合计 27
    with pytest.raises(ScoringInputError):
        b = full_marks()
        b.remove("S2", kind="checklist_hit")
        for p in card:
            b.add("S2", "checklist_hit", ref=p.id, label=p.name, judgment="count")
        score_round(b.items, cfg, context(checklist=card))


def test_t3t4_unknown_point_raises(cfg):
    b = full_marks()
    b.add("S2", "checklist_hit", ref="nonexistent", judgment="count")
    with pytest.raises(EvidenceError):
        run(cfg, b)


# ───────────── T4 分级锚定 ─────────────


def test_t4_evidence_level(cfg):
    b = full_marks()
    b.remove("P1")
    b.level("P1", 7, source="vision")
    assert item(run(cfg, b), "P1").score == 7


def test_t4_invalid_level_raises(cfg):
    b = full_marks()
    b.remove("S1")
    b.level("S1", 5)
    with pytest.raises(EvidenceError):
        run(cfg, b)


def test_t4_missing_level_is_missing(cfg):
    b = full_marks()
    b.remove("P1")
    r = run(cfg, b)
    assert item(r, "P1").status == "missing_evidence"
    assert r.total_grade is None


@pytest.mark.parametrize("v,level", [(100, 10), (90, 10), (89.9, 8), (80, 8), (79, 6), (70, 6), (69, 3), (60, 3), (59.9, 0), (0, 0)])
def test_t4_metric_bands_p3(cfg, v, level):
    b = full_marks()
    b.remove("P3")
    b.metric("P3", "reading_eval_score", v)
    assert item(run(cfg, b), "P3").score == level


@pytest.mark.parametrize("v,flag", [(92, True), (88, True), (85, False), (95, False)])
def test_t4_metric_boundary_flag(cfg, v, flag):
    b = full_marks()
    b.remove("P3")
    b.metric("P3", "reading_eval_score", v)
    res = item(run(cfg, b), "P3")
    assert res.low_confidence is flag
    assert res.status == "scored"


def test_t4_p3_missing_reading_eval_is_missing(cfg):
    b = full_marks()
    b.remove("P3")
    res = item(run(cfg, b), "P3")
    assert res.status == "missing_evidence" and res.score is None


def test_t4_accent_downgrade_disabled_by_default(cfg):
    b = full_marks()
    b.occ("P3", "accent_downgrade")
    assert item(run(cfg, b), "P3").score == 10
    data = modified(raw_config(), lambda d: item_raw(d, "P3")["parts"][0]["modifiers"][0].update(enabled=True))
    assert item(score_round(b.items, parse_config(data), context()), "P3").score == 8


@pytest.mark.parametrize("level,expected", [(20, 14), (14, 14), (8, 8), (0, 0)])
def test_t4_l1_hook_invalid_cap(cfg, level, expected):
    b = full_marks()
    b.remove("L1")
    b.level("L1", level)
    b.occ("L1", "hook_invalid")
    assert item(run(cfg, b), "L1").score == expected


@pytest.mark.parametrize("n,level,flag", [(0, 10, False), (1, 7, False), (2, 7, True), (3, 4, True), (4, 4, False), (5, 4, True), (6, 0, True), (9, 0, False)])
def test_t4_count_bands_p7(cfg, n, level, flag):
    b = full_marks()
    for i in range(n):
        b.occ("P7", "run_on" if i % 2 else "stall", source="audio")
    res = item(run(cfg, b), "P7")
    assert res.score == level
    assert res.low_confidence is flag


@pytest.mark.parametrize("pitch,loud,level", [(25, 12, 3), (10, 12, 5), (10, 5, 3), (5, 20, 3), (2, 20, 1)])
def test_t4_rules_p5(cfg, pitch, loud, level):
    b = full_marks()
    b.remove("P5")
    b.metric("P5", "pitch_range_st", pitch)
    b.metric("P5", "loudness_range_db", loud)
    assert item(run(cfg, b), "P5").score == level


def test_t4_rules_missing_metric(cfg):
    b = full_marks()
    b.remove("P5", label="loudness_range_db")
    assert item(run(cfg, b), "P5").status == "missing_evidence"


def test_t4_parts_o4(cfg):
    b = full_marks()
    b.remove("O4")
    for k, v in {"max_response_latency_s": 12, "returned_to_mainline_ratio": 0.5, "dead_air_count": 0,
                 "unanswered_objections": 0, "loudness_range_db": 6, "pitch_range_st": 3}.items():
        b.metric("O4", k, v)
    assert item(run(cfg, b), "O4").score == 5 + 4


def test_t4_duplicate_metric_raises(cfg):
    b = full_marks()
    b.metric("P3", "reading_eval_score", 80)
    with pytest.raises(EvidenceError):
        run(cfg, b)


# ───────────── T5 阈值 ─────────────


@pytest.mark.parametrize("over,expected", [(0, 5), (1, 3), (2, 0), (10, 0)])
def test_t5_p4(cfg, over, expected):
    b = full_marks()
    b.remove("P4")
    for m in range(10):
        b.metric("P4", "chars_per_min", 420 if m < over else 400, t=m * 60_000)  # 恰好 400 不算超
    assert item(run(cfg, b), "P4").score == expected


def test_t5_missing(cfg):
    b = full_marks()
    b.remove("P4")
    assert item(run(cfg, b), "P4").status == "missing_evidence"


# ───────────── T6 逐题 ─────────────


def test_t6_o5_levels(cfg):
    b = full_marks()
    b.remove("O5")
    for q, lv in zip(["q-waiting", "q-med-vs-ci", "q3", "q4", "q5", "q6"], ["full", "partial", "zero", "full", "partial", "full"]):
        b.add("O5", "question", ref=q, judgment=lv)
    assert item(run(cfg, b), "O5").score == 5 + 3 + 0 + 5 + 3 + 5


def test_t6_o5_unanswered_question_without_evidence_is_missing(cfg):
    b = full_marks()
    b.items = [e for e in b.items if not (e.item_id == "O5" and e.ref == "q6")]
    assert item(run(cfg, b), "O5").status == "missing_evidence"


def test_t6_o5_duplicate_or_unknown(cfg):
    b = full_marks()
    b.add("O5", "question", ref="q3", judgment="zero")
    with pytest.raises(EvidenceError):
        run(cfg, b)
    b = full_marks()
    b.add("O5", "question", ref="q-other", judgment="zero")
    with pytest.raises(EvidenceError):
        run(cfg, b)


def test_t6_s3_elements_and_zero(cfg):
    b = full_marks()
    b.remove("S3")
    # obj-medicare：三要素全有 5；obj-pneumonia：只正面回答 2；obj-cheap：答错 0；obj-expensive：没回答 0
    for el in ("direct_answer", "advantage", "altruistic_close"):
        b.add("S3", "question", ref="obj-medicare", label=el, judgment="count")
    b.add("S3", "question", ref="obj-pneumonia", label="direct_answer", judgment="count")
    b.add("S3", "question", ref="obj-pneumonia", label="advantage", judgment="not_count")
    b.add("S3", "question", ref="obj-cheap", label="direct_answer", judgment="count")
    b.add("S3", "question", ref="obj-cheap", label="advantage", judgment="count")
    b.add("S3", "question", ref="obj-cheap", label="wrong_answer", judgment="count")
    b.add("S3", "question", ref="obj-expensive", label="no_answer", judgment="count")
    assert item(run(cfg, b), "S3").score == 5 + 2 + 0 + 0


def test_t6_s3_late_answer_attributed_by_content(cfg):
    """C8：按内容归属。第 1 条异议的回答出现在第 2 条弹出之后，仍计入第 1 条。"""
    b = full_marks()
    b.remove("S3")
    for o in ["obj-pneumonia", "obj-cheap", "obj-expensive"]:
        for el in ("direct_answer", "advantage", "altruistic_close"):
            b.add("S3", "question", ref=o, label=el, judgment="count", t=330_000)
    for el in ("direct_answer", "advantage", "altruistic_close"):
        b.add("S3", "question", ref="obj-medicare", label=el, judgment="count", t=340_000)  # 05:40，晚于 05:30
    assert item(run(cfg, b), "S3").score == 20


def test_t6_wrong_question_count(cfg):
    with pytest.raises(ScoringInputError):
        run(cfg, full_marks(), expected_questions={"S3": ["a", "b", "c"], "O5": ["q1"] * 6})


def test_t6_missing_question_list(cfg):
    r = run(cfg, full_marks(), expected_questions={})
    assert item(r, "S3").status == "missing_evidence" and item(r, "O5").status == "missing_evidence"



@pytest.mark.parametrize("add", [
    lambda b: b.level("P3", 10),  # P3 的等级来自评测分，不接受直接给等级
    lambda b: b.occ("P7", "unknown_label"),
    lambda b: b.metric("P5", "unused_metric", 1),
    lambda b: b.level("O4", 8, ref="tempo"),
])
def test_t4_unused_evidence_rejected(cfg, add):
    b = full_marks()
    add(b)
    with pytest.raises(EvidenceError):
        run(cfg, b)
