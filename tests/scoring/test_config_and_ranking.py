"""配置校验、发布检查、批次排名。"""
from datetime import datetime, timedelta

import pytest
import yaml

from scoring import ConfigError, RankEntry, config_hash, ensure_publishable, load_config, parse_config, publish_blockers, rank
from tests.scoring.helpers import CONFIG_PATH, item_raw, modified, raw_config


def test_default_config_shape(cfg):
    items = [it for _, it in cfg.items()]
    assert len(items) == 23 and "P6" not in {i.id for i in items}
    assert {d.id: sum(i.max for i in d.items) for d in cfg.dimensions} == {"P": 95, "S": 100, "L": 100, "O": 100}
    types = {i.id: i.type for i in items}
    assert {types[k] for k in ("P2", "P8", "P10", "L3")} == {"T1"}
    assert {types[k] for k in ("P9", "S4", "L2", "L4", "L5", "O1", "O2", "O3")} == {"T2"}
    assert types["S2"] == "T3+T4" and types["P4"] == "T5"
    assert {types[k] for k in ("P1", "P3", "P5", "P7", "S1", "L1", "O4")} == {"T4"}
    assert {types[k] for k in ("S3", "O5")} == {"T6"}


def test_load_from_file():
    assert load_config(CONFIG_PATH).version == "rubric-v0.1"


def test_hash_stable_and_sensitive(cfg):
    assert config_hash(parse_config(raw_config())) == config_hash(cfg)
    assert config_hash(parse_config(modified(raw_config(), lambda d: item_raw(d, "L3").update(per=5)))) != config_hash(cfg)


# ───────────── 发布检查：待确认规则不得静默进入正式配置 ─────────────


EXPECTED_BLOCKERS = {"Q6", "Q8", "Q9", "Q10", "Q13", "Q14", "Q15", "Q16", "Q17", "Q18", "P-B3", "P-B8", "P-P3-ACCENT"}


def test_draft_config_lists_all_blockers(cfg):
    text = "\n".join(publish_blockers(cfg))
    for q in EXPECTED_BLOCKERS:
        assert q in text, q
    assert not any(b.startswith("redlines") for b in publish_blockers(cfg))  # C33：红线关闭，不再阻碍发布
    for where in ("low_confidence", "P5", "O4.parts.rhythm", "O4.parts.enthusiasm"):
        assert any(where in b and "占位" in b for b in publish_blockers(cfg)), where
    with pytest.raises(ConfigError):
        ensure_publishable(cfg)


def test_published_status_with_markers_is_rejected():
    with pytest.raises(ConfigError, match="不能发布"):
        parse_config(modified(raw_config(), lambda d: d.update(status="published")))


def _strip(node):
    if isinstance(node, dict):
        node.pop("pending", None)
        node.pop("calibration_required", None)
        for v in node.values():
            _strip(v)
    elif isinstance(node, list):
        for v in node:
            _strip(v)


def test_config_without_markers_is_publishable():
    data = raw_config()
    _strip(data)
    data["status"] = "published"
    cfg = parse_config(data)
    assert publish_blockers(cfg) == []


# ───────────── 配置校验 ─────────────


@pytest.mark.parametrize("mutate,msg", [
    (lambda d: d.update(grade_bands=[[96, 100, 1], [90, 95, 2], [81, 90, 3], [71, 80, 4], [61, 70, 5], [51, 60, 6], [41, 50, 7], [0, 40, 8]]), "首尾相接"),
    (lambda d: d.update(grade_bands=[[96, 100, 1], [91, 95, 2], [81, 89, 3], [71, 80, 4], [61, 70, 5], [51, 60, 6], [41, 50, 7], [0, 40, 8]]), "首尾相接"),
    (lambda d: d.update(grade_bands=[[96, 100, 1], [91, 95, 3]]), "覆盖"),
    (lambda d: d["critical"].update(total_rounds=4), "奇数"),
    (lambda d: item_raw(d, "O3").update(cap=20), "cap"),
    (lambda d: item_raw(d, "O5").update(count=5), "题数"),
    (lambda d: item_raw(d, "S2").update(checklist_max=25), "满分"),
    (lambda d: item_raw(d, "P1")["parts"][0].update(levels=[9, 7, 4, 0]), "满分"),
    (lambda d: item_raw(d, "P4").update(score_by_over={"0": 5, "2+": 0}), "连续"),
    (lambda d: item_raw(d, "P7")["parts"][0]["count_bands"][1].update(min=2), "连续"),
    (lambda d: item_raw(d, "P3")["parts"][0].update(levels=[8, 10, 6, 3, 0]), "从高到低"),
    (lambda d: item_raw(d, "P1")["parts"][0].update(levels=[10, 7, 4, 0, 0]), "重复"),
    (lambda d: d["dimensions"][0]["items"].append({"id": "P6", "name": "音色", "type": "T4", "max": 5, "parts": [{"levels": [5, 0]}]}), "已删除"),
    (lambda d: d["dimensions"][0]["items"].pop(), "条目数"),
    (lambda d: d["dimensions"][1]["items"].append(dict(item_raw(d, "S1"))), "重复"),
    (lambda d: item_raw(d, "P2").update(unknown_key=1), "unknown_key"),
    (lambda d: d["redlines"].update(per_redline_threshold={"R9": 0.9}), "未列出"),
    (lambda d: item_raw(d, "L1")["parts"][0]["modifiers"][0].update(cap=15), "cap"),
])
def test_invalid_configs(mutate, msg):
    with pytest.raises(ConfigError, match=msg):
        parse_config(modified(raw_config(), mutate))


def test_yaml_is_valid_utf8_and_safe():
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        assert isinstance(yaml.safe_load(fh), dict)


# ───────────── 排名 ─────────────

T0 = datetime(2026, 11, 2, 9, 0)


def _e(rid, label, total, dims, redline=False, minutes=0):
    return RankEntry(report_id=rid, label=label, total_grade=total, dimension_scores=dict(zip("PSLO", dims)),
                     redline_hit=redline, submitted_at=T0 + timedelta(minutes=minutes))


def test_rank_default_order():
    entries = [
        _e("a", "not_recommend", 9, (90, 90, 90, 90), redline=True, minutes=1),
        _e("b", "pending", 14, (70, 70, 70, 70)),
        _e("c", "recommend", 10, (85, 85, 85, 85)),
        _e("d", "recommend", 8, (90, 85, 85, 85)),
        _e("e", "recommend", 8, (92, 85, 85, 85)),  # 同总档位，维度分之和更高
        _e("f", "not_recommend", 18, (60, 50, 50, 50)),
        _e("g", "not_recommend", 9, (90, 90, 90, 90), redline=False, minutes=2),  # 同分，无红线优先
    ]
    assert [x.report_id for x in rank(entries)] == ["e", "d", "c", "b", "g", "a", "f"]


def test_rank_submission_time_last_tiebreak():
    entries = [_e("late", "recommend", 8, (90,) * 4, minutes=5), _e("early", "recommend", 8, (90,) * 4, minutes=1)]
    assert [x.report_id for x in rank(entries)] == ["early", "late"]


def test_rank_by_dimension():
    entries = [
        _e("a", "recommend", 8, (80, 95, 90, 90)),
        _e("b", "not_recommend", 12, (80, 99, 60, 60)),
        _e("c", "pending", 13, (80, 95, 80, 80)),
        _e("d", "recommend", 13, (80, 95, 80, 80), redline=True),
    ]
    assert [x.report_id for x in rank(entries, by="S")] == ["b", "a", "c", "d"]
    with pytest.raises(ValueError):
        rank(entries, by="X")
