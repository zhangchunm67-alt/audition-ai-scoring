"""人工打分来源（decisions.md T39）：评委补分、机器建议分须确认、判扣分须确认、机器评不出转人工。"""
import pytest

from scoring import HumanScore, ScoringInputError, score_round

from .helpers import ALL_ITEMS, cfg, context, full_marks  # noqa: F401


def _item(res, iid):
    return next(i for i in res.items if i.item_id == iid)


def test_human_only_item_waits_then_scores(cfg):
    evs = [e for e in full_marks().items if e.item_id != "P3"]
    done = set(ALL_ITEMS) - {"P3"}
    r = score_round(evs, cfg, context(completed=done, human_only={"P3"}))
    assert r.status == "incomplete" and r.missing_items == [] and r.awaiting_human_items == ["P3"]
    assert _item(r, "P3").status == "awaiting_human" and _item(r, "P3").suggested_score is None
    assert r.total_grade is None
    r = score_round(evs, cfg, context(completed=done, human_only={"P3"}, human_scores={"P3": HumanScore(score=9, by="hr1")}))
    assert r.status == "complete" and r.awaiting_human_items == []
    p3 = _item(r, "P3")
    assert p3.source == "human" and p3.score == 9 and p3.human.by == "hr1"


def test_confirm_item_keeps_machine_suggestion(cfg):
    r = score_round(full_marks().items, cfg, context(human_confirm={"S2"}))
    s2 = _item(r, "S2")
    assert s2.status == "awaiting_human" and s2.suggested_score == 50 and r.awaiting_human_items == ["S2"]
    r = score_round(full_marks().items, cfg, context(human_confirm={"S2"}, human_scores={"S2": HumanScore(score=40)}))
    s2 = _item(r, "S2")
    assert r.status == "complete" and s2.score == 40 and s2.suggested_score == 50 and s2.source == "human"


def test_confirm_on_deduction_only_when_deducted(cfg):
    r = score_round(full_marks().items, cfg, context(human_on_deduction={"P1"}))
    assert r.status == "complete" and _item(r, "P1").source == "machine"
    b2 = full_marks()
    b2.occ("P1", "attire", judgment="count", source="vision")
    evs = [e for e in b2.items if not (e.item_id == "P1" and e.label == "attire" and e.judgment == "not_count")]
    r = score_round(evs, cfg, context(human_on_deduction={"P1"}))
    p1 = _item(r, "P1")
    assert p1.status == "awaiting_human" and p1.suggested_score == 0 and "扣分" in p1.missing_reasons[0]


def test_fallback_turns_missing_into_human(cfg):
    evs = [e for e in full_marks().items if e.item_id != "L3"]
    done = set(ALL_ITEMS) - {"L3"}
    r = score_round(evs, cfg, context(completed=done))
    assert r.missing_items == ["L3"]
    r = score_round(evs, cfg, context(completed=done, human_fallback=True))
    assert r.missing_items == [] and r.awaiting_human_items == ["L3"]
    assert "检测器未成功完成" in " ".join(_item(r, "L3").missing_reasons)


@pytest.mark.parametrize("bad", [21, 3.3])
def test_human_score_validated(cfg, bad):
    with pytest.raises(ScoringInputError):
        score_round(full_marks().items, cfg, context(human_scores={"L3": HumanScore(score=bad)}))
