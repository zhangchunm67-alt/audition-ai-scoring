"""金标准用的条目分汇总、校准员打分配置。"""
import pytest

from scoring import ScoringInputError, score_round
from scoring.aggregate import aggregate_item_scores, calibration_config
from scoring.config import T4Item
from tests.scoring.helpers import builder_for_total, context, full_marks


def test_aggregate_matches_engine(cfg):
    for total in (4, 12, 14, 17):
        r = score_round(builder_for_total(total).items, cfg, context())
        agg = aggregate_item_scores(cfg, {i.item_id: i.score for i in r.items}, props_available=True, audience="new_trial")
        assert agg.total_grade == r.total_grade == total
        assert [d.score for d in agg.dimensions] == [d.score for d in r.dimensions]
        assert agg.critical == r.critical and agg.grade_pass == r.grade_pass


def test_aggregate_scales_without_props_and_median_halves(cfg):
    scores = {i.item_id: i.score for i in score_round(full_marks(props=False).items, cfg, context(props=False)).items}
    scores["P2"] = 37.5  # 两位校准员 35、40 的平均
    agg = aggregate_item_scores(cfg, scores, props_available=False, audience="new_trial")
    p = agg.dimensions[0]
    assert p.applicable_max == 95 and p.raw == 92.5 and p.score == 97  # 92.5 ÷ 95 × 100 = 97.4 → 97


def test_aggregate_missing_and_invalid(cfg):
    scores = {i.item_id: i.score for i in score_round(full_marks().items, cfg, context()).items}
    scores["S3"] = None
    agg = aggregate_item_scores(cfg, scores, props_available=True, audience="new_trial")
    assert agg.status == "incomplete" and agg.missing_items == ["S3"] and agg.total_grade is None
    scores["S3"] = 25
    with pytest.raises(ScoringInputError):
        aggregate_item_scores(cfg, scores, props_available=True, audience="new_trial")


def test_calibration_config_makes_levels_direct(cfg):
    c = calibration_config(cfg)
    parts = {it.id: [p.source for p in it.parts] for _, it in c.items() if isinstance(it, T4Item)}
    assert parts == {"P5": ["evidence"], "P6": ["evidence"], "P7": ["evidence"], "S1": ["evidence"], "S2": ["evidence"],
                     "L1": ["evidence"], "O4": ["evidence"]}
    assert c.version.endswith("+calibration")
    assert next(it for _, it in c.items() if it.id == "P2").free == 20  # 其余计分规则不变
    b = full_marks()
    for it, v in (("P5", 3), ("P6", 4), ("P7", 7), ("O4", 15)):
        b.remove(it)
        b.level(it, v, source="human")
    b.remove("S2")
    b.level("S2", 41, ref="fixed_script_accuracy", source="human")
    r = score_round(b.items, c, context())
    got = {i.item_id: i.score for i in r.items}
    assert (got["P5"], got["P6"], got["P7"], got["O4"], got["S2"]) == (3, 4, 7, 15, 41) and r.status == "complete"


def test_legacy_calibration_config_makes_levels_direct(legacy_cfg):
    c = calibration_config(legacy_cfg)
    parts = {it.id: [p.source for p in it.parts] for _, it in c.items() if isinstance(it, T4Item)}
    assert parts == {"P1": ["evidence"], "P3": ["evidence"], "P5": ["evidence"], "P7": ["evidence"], "S1": ["evidence"],
                     "L1": ["evidence"], "O4": ["evidence", "evidence"]}
