"""引用须来自指定原文范围，时间与置信度必须对应同一次匹配。"""
import pytest

from app.pipeline.detectors.common import Ctx
from app.pipeline.detectors.sales import s2, s4
from app.pipeline.text import SegmentText
from app.providers.base import Word
from scoring import parse_config, score_round
from tests.scoring.helpers import CHECKLIST, context, full_marks, item, raw_config


def make_ctx(text="真实原文", confidence=0.9):
    st = SegmentText("main", [Word(c, i * 100, (i + 1) * 100, confidence) for i, c in enumerate(text)])
    return Ctx(round_no=1, props_available=False, segments=[], objections=[], questions=[], reading_text="",
               card={}, lexicon={}, cfg=None, texts={"main": st}, acoustic={}, media=None, providers=None)


@pytest.mark.parametrize("text,quote", [("", "虚构推荐"), ("真实原文", "虚构推荐"),
                                       ("真实原文", ""), ("真实原文", "， 。 ")])
def test_unmatched_quote_cannot_become_scoring_evidence(text, quote):
    with pytest.raises(ValueError, match="S4: 引用无法"):
        make_ctx(text).quote_ev("S4", "instance", quote, model_conf=0.99, label="herd", judgment="count")


def test_matching_uses_segment_and_after_boundary():
    ctx = make_ctx("真实原文")
    for kw in ({"after_ms": 1}, {"st": SegmentText("reading", [])}):
        with pytest.raises(ValueError, match="引用无法"):
            ctx.quote_ev("S4", "instance", "真实原文", model_conf=0.99, **kw)
    assert ctx.quote_ev("S4", "instance", "真实原文", after_ms=0, model_conf=0.99).start_ms == 0


def test_normalized_repeated_quote_uses_matched_confidence():
    ctx = make_ctx("真实原文。真实原文")
    ctx.main.words[6].confidence = 0.25
    ev = ctx.quote_ev("S4", "instance", "真实，原文", after_ms=500, model_conf=0.99)
    assert (ev.start_ms, ev.end_ms, ev.confidence) == (500, 900, 0.25)
    assert ctx.quote_ev("S4", "instance", "真实原文", model_conf=0.6).confidence == 0.6


def test_valid_quote_still_scores_through_detector(monkeypatch):
    ctx = make_ctx()
    monkeypatch.setattr(ctx, "ask", lambda *a: {"items": [dict(quote="真实原文", method="herd",
                                                               compliant=True, confidence=0.99, reason="test")]})
    b = full_marks()
    b.remove("S4")
    b.items.extend(s4(ctx))
    result = item(score_round(b.items, parse_config(raw_config()), context()), "S4")
    assert result.score == 5
    assert sum(c.delta for c in result.contributions) == 5


def test_unmentioned_checklist_points_remain_zero_score(monkeypatch):
    ctx = make_ctx()
    ctx.card = {"checklist": [p.model_dump() for p in CHECKLIST]}
    response = dict(points=[dict(id=p.id, covered=False, correct=True, quote="", reason="未讲到", confidence=0.9)
                            for p in CHECKLIST], errors=[], structure_level=0, structure_reason="无结构", structure_confidence=0.9)
    monkeypatch.setattr(ctx, "ask", lambda *a: response)
    b = full_marks()
    b.remove("S2")
    b.items.extend(s2(ctx))
    result = item(score_round(b.items, parse_config(raw_config()), context()), "S2")
    assert result.status == "scored" and result.score == 0
    # 声称讲到却没有原文，不能伪装成“未讲到”的正常核对结果。
    response["points"][0]["covered"] = True
    with pytest.raises(ValueError, match="引用无法"):
        s2(ctx)
