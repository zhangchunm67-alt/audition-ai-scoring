"""T1–T6 计分类型（现行配置 rubric-v0.3，按评分表 20261105）。旧版配置的机制见 test_legacy_v01.py。"""
import pytest

from scoring import EvidenceError, ScoringInputError, score_round
from scoring.types import Review
from tests.scoring.helpers import context, full_marks, item


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


@pytest.mark.parametrize("labels,expected", [((), 10), (("attire",), 0), (("hairstyle",), 0), (("attire", "hairstyle"), 0)])
def test_t1_p1_attire_or_hairstyle_deducts_10(cfg, labels, expected):
    """评分表：穿着、发型不符合要求直接扣 10 分。相貌不做自动评分。"""
    b = full_marks()
    for lab in labels:
        b.occ("P1", lab, source="vision")
    assert item(run(cfg, b), "P1").score == expected


@pytest.mark.parametrize("n,expected", [(0, 10), (1, 9), (3, 7), (10, 0), (12, 0)])
def test_t1_p3_dialect_one_point_each(cfg, n, expected):
    """评分表：方言一处扣 1 分；发音不准（not_count）不扣。"""
    b = full_marks()
    for _ in range(n):
        b.occ("P3", "dialect", source="audio", segment="reading")
    b.occ("P3", "mispronounce", judgment="not_count", source="audio", segment="reading")
    assert item(run(cfg, b), "P3").score == expected


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
    assert item(run(cfg, b, main_duration_ms=720_000), "P2").score == 40  # 12 分钟：15 × 10 ÷ 12 = 12.5 次，免扣内


def test_t1_normalize_long_video_counts_per_ten_minutes(cfg):
    """C36：不截取 10 分钟，整段计次后换算成每 10 分钟的次数。60 分钟讲了 150 处 = 每 10 分钟 25 处，超出免扣 5 处。"""
    b = full_marks()
    for _ in range(150):
        b.occ("P2", "那么")
    r = run(cfg, b, main_duration_ms=3_600_000)
    assert item(r, "P2").score == 35
    assert any("超过 10 分钟" in n for n in item(r, "P2").notes)


def test_t1_normalize_legacy_config_only_scales_up():
    """rubric-v0.2 及以前（both_ways 关）：超过 10 分钟不换算，旧报告重算结果不变；且哈希里不出现新字段。"""
    from scoring import parse_config
    from scoring.config import config_hash
    from tests.scoring.helpers import item_raw, raw_config

    d = raw_config()
    item_raw(d, "P2")["normalize"].pop("both_ways")
    old = parse_config(d)
    b = full_marks()
    for _ in range(30):
        b.occ("P2", "那么")
    assert item(run(old, b, main_duration_ms=1_200_000), "P2").score == 30
    d2 = raw_config()
    item_raw(d2, "P2")["normalize"]["both_ways"] = False
    assert config_hash(parse_config(d2)) == config_hash(old)


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


def test_t2_s4_distinct_methods_sunk_cost_counts(cfg):
    """评分表：从众、损失规避、权威认同、价格拆分、沉没成本，每个 5 分。"""
    b = full_marks()
    b.remove("S4")
    b.inst("S4", "herd")
    b.inst("S4", "herd")  # 同一方法重复不加分
    b.inst("S4", "sunk_cost")  # 沉没成本计分
    b.inst("S4", "price_split", judgment="not_count")  # 算错的价格拆分
    b.inst("S4", "scarcity")  # 评分表未列的方法不计分
    res = item(run(cfg, b), "S4")
    assert res.score == 10
    assert any("不计分" in c.note for c in res.contributions)
    for m in ("loss_aversion", "authority", "price_split"):
        b.inst("S4", m)
    assert item(run(cfg, b), "S4").score == 20  # 封顶 20


def test_t2_o1_o2_three_places_ten_each(cfg):
    """评分表：O1、O2 各 3 处、每处 10 分，满分 30。"""
    b = full_marks()
    b.remove("O1")
    b.inst("O1", "免赔额")
    b.inst("O1", "免赔额")  # 同一术语只算一处（P-O-DISTINCT）
    b.inst("O1", "等待期")
    assert item(run(cfg, b), "O1").score == 20
    for t in ("既往症", "续保"):
        b.inst("O1", t)
    assert item(run(cfg, b), "O1").score == 30
    b.remove("O2")
    b.inst("O2", "儿童医院可用")
    assert item(run(cfg, b), "O2").score == 10


def test_t2_o3_two_places_ten_each(cfg):
    """评分表：O3 场景化 2 处、每处 10 分，满分 20。"""
    b = full_marks()
    b.remove("O3")
    b.inst("O3")
    assert item(run(cfg, b), "O3").score == 10
    for _ in range(4):
        b.inst("O3")
    assert item(run(cfg, b), "O3").score == 20


def test_t2_l2_ten_each(cfg):
    b = full_marks()
    b.remove("L2")
    b.inst("L2")
    assert item(run(cfg, b), "L2").score == 10
    b.remove("L2")
    assert item(run(cfg, b), "L2").score == 0  # 检测器已完成且没有实例：0 分是真实结果


# ───────────── T4：评分表“根据主观打分”与 S2 固定话术完成准确度 ─────────────


@pytest.mark.parametrize("item_id,max_", [("P5", 5), ("P6", 5), ("P7", 10), ("S1", 10), ("L1", 20), ("O4", 20), ("S2", 50)])
def test_t4_subjective_items_accept_every_integer(cfg, item_id, max_):
    """主观评分条目不再自定分档：0–满分的每个整数都是合法等级。"""
    ref = "fixed_script_accuracy" if item_id == "S2" else None
    for v in range(max_ + 1):
        b = full_marks()
        b.remove(item_id)
        b.level(item_id, v, ref=ref)
        assert item(run(cfg, b), item_id).score == v


@pytest.mark.parametrize("item_id,bad", [("P5", 6), ("P6", -1), ("S1", 11), ("L1", 21), ("O4", 25), ("S2", 51)])
def test_t4_out_of_range_level_raises(cfg, item_id, bad):
    b = full_marks()
    b.remove(item_id)
    b.level(item_id, bad, ref="fixed_script_accuracy" if item_id == "S2" else None)
    with pytest.raises(EvidenceError):
        run(cfg, b)


@pytest.mark.parametrize("v", [0, 1, 25, 49, 50])
def test_t4_s2_fixed_script_accuracy_bounds(cfg, v):
    b = full_marks()
    b.remove("S2")
    b.level("S2", v, ref="fixed_script_accuracy")
    res = item(run(cfg, b), "S2")
    assert res.score == v and res.max == 50
    assert [c.note for c in res.contributions] == ["等级（fixed_script_accuracy）"]


def test_t4_single_part_level_may_omit_ref(cfg):
    """单部分条目的等级证据可以不写 ref（校准员打分页就是这样提交的），S2 的部分名不是 main 也一样。"""
    b = full_marks()
    b.remove("S2")
    b.level("S2", 33)
    assert item(run(cfg, b), "S2").score == 33
    b.level("S2", 30, ref="structure")  # 写了 ref 就必须对得上
    with pytest.raises(EvidenceError):
        run(cfg, b)


def test_t4_s2_missing_level_is_missing_not_zero(cfg):
    """S2 检测器拒绝出分（例如产品未校准）时没有证据：缺证据，不能当 0 分。"""
    b = full_marks()
    b.remove("S2")
    r = run(cfg, b)
    assert item(r, "S2").status == "missing_evidence" and item(r, "S2").score is None
    assert r.status == "incomplete" and r.total_grade is None


@pytest.mark.parametrize("add", [
    lambda b: b.add("S2", "checklist_hit", ref="coverage", judgment="count"),  # 旧版卖点卡要点
    lambda b: b.level("S2", 20, ref="structure"),  # 旧版结构分
    lambda b: b.occ("S2", "error"),  # 旧版讲错扣分
])
def test_t4_s2_rejects_legacy_evidence(cfg, add):
    b = full_marks()
    add(b)
    with pytest.raises(EvidenceError):
        run(cfg, b)


def test_t4_evidence_level(cfg):
    b = full_marks()
    b.remove("P6")
    b.level("P6", 3, source="audio")
    assert item(run(cfg, b), "P6").score == 3


def test_t4_duplicate_level_raises(cfg):
    b = full_marks()
    b.level("S1", 5)
    with pytest.raises(EvidenceError):
        run(cfg, b)


def test_t4_missing_level_is_missing(cfg):
    b = full_marks()
    b.remove("P7")
    r = run(cfg, b)
    assert item(r, "P7").status == "missing_evidence"
    assert r.total_grade is None


@pytest.mark.parametrize("add", [
    lambda b: b.metric("P5", "pitch_range_st", 10),  # 旧版按音高阈值分档，现行配置不接受
    lambda b: b.occ("P7", "stall"),  # 旧版按停顿次数分档
    lambda b: b.occ("L1", "hook_invalid"),  # 旧版钩子封顶
    lambda b: b.level("O4", 8, ref="rhythm"),  # 旧版节奏 + 热情两部分
    lambda b: b.metric("P3", "reading_eval_score", 90),  # 旧版评测分分档
    lambda b: b.add("O5", "question", ref="q1", judgment="full"),  # O5 已删除
])
def test_unused_evidence_rejected(cfg, add):
    b = full_marks()
    add(b)
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
        run(cfg, full_marks(), expected_questions={"S3": ["a", "b", "c"]})


def test_t6_missing_question_list(cfg):
    r = run(cfg, full_marks(), expected_questions={})
    assert item(r, "S3").status == "missing_evidence"





# ───────────── 录播：观众异议按实际条数折算（C37） ─────────────


def _answers(b, refs, full: int):
    b.remove("S3")
    for i, o in enumerate(refs):
        if i < full:
            for el in ("direct_answer", "advantage", "altruistic_close"):
                b.add("S3", "question", ref=o, label=el, judgment="count")
        else:
            b.add("S3", "question", ref=o, label="no_answer", judgment="count")
    return b


@pytest.mark.parametrize("n,full,expected", [(2, 2, 20), (2, 1, 10), (3, 2, 13.33), (4, 3, 15), (8, 6, 15), (1, 0, 0)])
def test_t6_flexible_count_scales_to_item_max(cfg, n, full, expected):
    refs = [f"live-{i}" for i in range(n)]
    r = run(cfg, _answers(full_marks(), refs, full), expected_questions={"S3": refs}, flexible_questions={"S3"})
    assert r.status == "complete"
    assert item(r, "S3").score == pytest.approx(expected, abs=0.01)
    s = next(d for d in r.dimensions if d.id == "S")
    assert s.applicable_max == 100
    if n != 4:
        assert any("折算" in x for x in item(r, "S3").notes)


def test_t6_flexible_none_marked_is_not_applicable(cfg):
    b = full_marks()
    b.remove("S3")
    r = run(cfg, b, expected_questions={"S3": []}, flexible_questions={"S3"})
    assert r.status == "complete" and item(r, "S3").status == "not_applicable"
    s = next(d for d in r.dimensions if d.id == "S")
    assert s.applicable_max == 80 and s.score == 100


def test_t6_fixed_count_still_enforced_without_flexible(cfg):
    with pytest.raises(ScoringInputError):
        run(cfg, full_marks(), expected_questions={"S3": []})


# ───────────── 按每 10 分钟换算（C38）：扣分项、加分项、语速 ─────────────

HOUR = 3_600_000


def test_normalize_deduction_items_long_video(cfg):
    """60 分钟录播：小动作 6 次 = 每 10 分钟 1 次，扣 1 分；嘻嘻哈哈 1 次 ≈ 0.17 次，扣约 0.83 分；演绎错误 3 次 = 0.5 次，扣 5 分。"""
    b = full_marks()
    for _ in range(6):
        b.occ("P8", "touch_face", source="vision")
    b.occ("P10", "laugh", source="audio")
    for _ in range(3):
        b.occ("L3", "deductive_error")
    r = run(cfg, b, main_duration_ms=HOUR)
    assert item(r, "P8").score == 4
    assert item(r, "P10").score == pytest.approx(5 - 5 / 6, abs=0.01)
    assert item(r, "L3").score == 15
    ten = run(cfg, b, main_duration_ms=600_000)  # 10 分钟：不换算，和原来一样
    assert (item(ten, "P8").score, item(ten, "P10").score, item(ten, "L3").score) == (0, 0, 0)


def test_normalize_additive_items_long_and_short_video(cfg):
    """加分项：60 分钟里 2 次结构化表达 = 每 10 分钟 1/3 次，得 3.33 分；12 次才满分。5 分钟里 1 次 = 2 次，满分。"""
    b = full_marks()
    r = run(cfg, b, main_duration_ms=HOUR)  # 满分证据是按 10 分钟的量给的
    assert item(r, "L2").score == pytest.approx(20 / 6, abs=0.01)
    assert any("超过 10 分钟" in n for n in item(r, "L2").notes)
    for _ in range(10):
        b.inst("L2")
    assert item(run(cfg, b, main_duration_ms=HOUR), "L2").score == 20
    short = full_marks()
    short.remove("L2")
    short.inst("L2")
    assert item(run(cfg, short, main_duration_ms=300_000), "L2").score == 20
    assert item(run(cfg, short, main_duration_ms=600_000), "L2").score == 10


def test_normalize_props_scaled_before_cap(cfg):
    b = full_marks()  # 3 次贴片 = 6 分，10 分钟封顶 5
    assert item(run(cfg, b, main_duration_ms=1_200_000), "P9").score == 3  # 20 分钟：6 ÷ 2 = 3


@pytest.mark.parametrize("over,minutes,expected", [(2, 10, 0), (2, 60, 5), (3, 60, 3), (8, 60, 3), (9, 60, 0), (1, 5, 0)])
def test_normalize_speech_rate_over_minutes(cfg, over, minutes, expected):
    """语速：超限分钟数按每 10 分钟换算后四舍五入。60 分钟里 2 分钟超限 ≈ 0.33 → 0 段；3 分钟 = 0.5 → 1 段。"""
    b = full_marks()
    b.remove("P4")
    for m in range(minutes):
        b.metric("P4", "chars_per_min", 450 if m < over else 300, t=m * 60_000)
    assert item(run(cfg, b, main_duration_ms=minutes * 60_000), "P4").score == expected


def test_distinct_items_not_normalized(cfg):
    """按种类去重的加分项（逼单方法、术语、卖点）不按时长折算，配置里也不允许开。"""
    from scoring import parse_config
    from tests.scoring.helpers import item_raw, raw_config

    r = run(cfg, full_marks(), main_duration_ms=HOUR)
    assert (item(r, "S4").score, item(r, "O1").score, item(r, "O2").score) == (20, 30, 30)
    d = raw_config()
    item_raw(d, "S4")["normalize"] = {"enabled": True, "both_ways": True}
    with pytest.raises(Exception, match="不能按时长换算"):
        parse_config(d)
