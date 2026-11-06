"""临界三轮、多数结论、跨轮红线、展示轮、结论标签。"""
import pytest
from hypothesis import given
from hypothesis import strategies as st

from scoring import VerdictError, finalize, parse_config, rounds_required, score_round
from tests.scoring.helpers import ALL_ITEMS, context, full_marks, modified, raw_config


def test_non_critical_pass_recommend(cfg, round_for_total):
    r = round_for_total(12)
    assert rounds_required(r, cfg) == 1
    v = finalize([r], cfg)
    assert (v.status, v.conclusion, v.label, v.label_zh, v.critical) == ("complete", "pass", "recommend", "推荐", False)
    assert v.display_round == 1
    assert "达到达标线" in v.reason


def test_non_critical_fail_not_recommend(cfg, round_for_total):
    v = finalize([round_for_total(17)], cfg)
    assert (v.conclusion, v.label, v.critical) == ("fail", "not_recommend", False)
    assert "未达到达标线" in v.reason


def test_critical_needs_three_rounds_total(cfg, round_for_total):
    r1 = round_for_total(14)
    assert rounds_required(r1, cfg) == 3  # 首轮参与投票，只追加 2 轮
    v = finalize([r1], cfg)
    assert v.status == "needs_more_rounds" and v.rounds_required == 3 and v.rounds_received == 1
    assert finalize([r1, round_for_total(14)], cfg).status == "needs_more_rounds"
    assert finalize([r1, round_for_total(14), round_for_total(15)], cfg).status == "complete"


def test_no_recursion_beyond_three_rounds(cfg, round_for_total):
    rs = [round_for_total(t) for t in (14, 15, 16, 13)]
    with pytest.raises(VerdictError):
        finalize(rs, cfg)


def test_critical_majority_pass_is_pending(cfg, round_for_total):
    v = finalize([round_for_total(t) for t in (14, 15, 13)], cfg)
    assert (v.conclusion, v.label, v.label_zh, v.critical) == ("pass", "pending", "待定", True)
    assert v.majority_grade_pass is True
    assert v.display_round == 1  # 三轮 14/15/13，中位数 14 在第 1 轮
    assert [s.total_grade for s in v.rounds] == [14, 15, 13]
    assert "临界" in v.reason and "2/3" in v.reason


def test_critical_majority_fail_keeps_critical_flag(cfg, round_for_total):
    v = finalize([round_for_total(t) for t in (14, 16, 15)], cfg)
    assert (v.conclusion, v.label, v.critical) == ("fail", "not_recommend", True)
    assert v.display_round == 3  # 中位数 15
    assert "临界" in v.reason


def test_critical_first_round_fail_majority_pass(cfg, round_for_total):
    v = finalize([round_for_total(t) for t in (15, 14, 13)], cfg)
    assert v.label == "pending" and v.display_round == 2


def test_display_round_tie_earliest(cfg, round_for_total):
    v = finalize([round_for_total(t) for t in (16, 14, 14)], cfg)
    assert v.display_round == 2


def test_redline_any_round_not_recommend(rl_cfg, round_for_total):
    cfg = rl_cfg
    """C11：任一轮命中红线即不推荐，即使总档位多数达标；临界标记保留。"""
    rs = [round_for_total(14, config=cfg), round_for_total(13, redline=("R4", 0.9), config=cfg), round_for_total(14, config=cfg)]
    v = finalize(rs, cfg)
    assert (v.conclusion, v.label, v.redline_hit, v.critical) == ("fail", "not_recommend", True, True)
    assert v.majority_grade_pass is True
    assert [(n, h.redline_id) for n, h in v.redline_hits] == [(2, "R4")]
    assert "R4（第 2 轮）" in v.reason and "临界" in v.reason


def test_critical_first_round_redline_no_extra_rounds(rl_cfg, round_for_total):
    cfg = rl_cfg
    """C17：首轮已命中红线的临界样本不追加 2 轮；临界标记保留。"""
    r1 = round_for_total(14, redline=("R3", 0.9), config=cfg)
    assert r1.critical is True
    assert rounds_required(r1, cfg) == 1
    v = finalize([r1], cfg)
    assert (v.status, v.label, v.critical, v.redline_hit, v.rounds_received) == ("complete", "not_recommend", True, True, 1)
    assert "临界" in v.reason and "未追加轮次" in v.reason
    with pytest.raises(VerdictError):
        finalize([r1, round_for_total(14, config=cfg), round_for_total(14, config=cfg)], cfg)


def test_critical_redline_below_threshold_still_three_rounds(rl_cfg, round_for_total):
    cfg = rl_cfg
    r1 = round_for_total(14, redline=("R3", 0.5), config=cfg)
    assert not r1.redline_hits and rounds_required(r1, cfg) == 3


def test_redline_non_critical_not_recommend(rl_cfg, round_for_total):
    cfg = rl_cfg
    v = finalize([round_for_total(4, redline=("R1", 0.95), config=cfg)], cfg)
    assert (v.label, v.critical, v.conclusion) == ("not_recommend", False, "fail")
    assert v.rounds[0].total_grade == 4  # 分数照常计算


def test_first_round_incomplete_cannot_decide(cfg):
    done = set(ALL_ITEMS) - {"S3"} | {"redlines"}
    r = score_round(full_marks().items, cfg, context(completed=done))
    with pytest.raises(VerdictError):
        rounds_required(r, cfg)
    v = finalize([r], cfg)
    assert v.status == "incomplete" and v.label is None and "S3" in v.message


def test_later_round_incomplete(cfg, round_for_total):
    done = set(ALL_ITEMS) - {"O4"} | {"redlines"}
    bad = score_round(full_marks().items, cfg, context(completed=done))
    v = finalize([round_for_total(14), bad, round_for_total(14)], cfg)
    assert v.status == "incomplete" and v.label is None


def test_rounds_must_share_config(cfg, round_for_total):
    c2 = parse_config(modified(raw_config(), lambda d: d.update(version="rubric-v0.2-alt")))
    b = full_marks()
    other = score_round(b.items, c2, context())
    with pytest.raises(VerdictError):
        finalize([round_for_total(14), round_for_total(14), other], cfg)


@pytest.mark.parametrize("critical,majority_pass,redline,label", [
    (False, True, False, "recommend"),
    (False, False, False, "not_recommend"),
    (True, True, False, "pending"),
    (True, False, False, "not_recommend"),
    (False, True, True, "not_recommend"),
    (True, True, True, "not_recommend"),
])
def test_label_precedence(rl_cfg, round_for_total, critical, majority_pass, redline, label):
    cfg = rl_cfg
    if critical:
        totals = (14, 14, 15) if majority_pass else (15, 16, 14)
    else:
        totals = (12,) if majority_pass else (17,)
    rs = [round_for_total(t, redline=("R2", 0.9) if (redline and i == 0) else None, config=cfg) for i, t in enumerate(totals)]
    rs = rs[: rounds_required(rs[0], cfg)]  # 首轮命中红线的临界样本只有 1 轮
    v = finalize(rs, cfg)
    assert v.label == label and v.critical is critical


@given(st.lists(st.sampled_from([13, 14, 15, 16]), min_size=2, max_size=2))
def test_display_round_always_matches_majority(totals):
    """性质：三轮中位数所在轮的结论一定与多数结论一致。"""
    from tests.scoring.helpers import builder_for_total

    cfg = parse_config(raw_config())
    rs = [score_round(builder_for_total(t).items, cfg, context()) for t in [14, *totals]]
    v = finalize(rs, cfg)
    assert v.rounds[v.display_round - 1].grade_pass == v.majority_grade_pass



def test_redlines_disabled_label_by_grade_only(cfg, round_for_total):
    """C33：试镜关闭红线，红线说法不改变结论；标签只由总档位和临界决定。"""
    r = round_for_total(4, redline=("R1", 0.99))
    v = finalize([r], cfg)
    assert (v.label, v.redline_hit, v.conclusion) == ("recommend", False, "pass")
