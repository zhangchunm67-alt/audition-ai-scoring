"""引用须来自指定原文范围，时间与置信度必须对应同一次匹配。"""
import pytest

from app.pipeline.detectors.common import Ctx
from types import SimpleNamespace

from app.pipeline.detectors import persona, unsupported_items
from app.pipeline.detectors.sales import S2NotCalibrated, s1, s2, s4
from app.pipeline.text import SegmentText
from app.providers.base import SpeechEvalResult, VisionFinding, VoiceRating, Word
from scoring import parse_config, score_round
from tests.scoring.helpers import context, full_marks, item, legacy_raw, raw_config


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


SCRIPT = {"version": "script-1", "text": "这款产品就三个好。"}
CAL = {"version": "cal-1", "fixed_script_version": "script-1", "status": "validated", "anchors": [{"score": 40, "excerpt": "示例"}]}


def s2_ctx(monkeypatch, response, card=None):
    ctx = make_ctx("真实原文。这款产品就三个好。")
    ctx.card = {"fixed_script": SCRIPT, "s2_calibration": CAL} if card is None else card
    calls = []
    monkeypatch.setattr(ctx, "ask", lambda task, payload: calls.append((task, payload)) or response)
    return ctx, calls


def s2_score(evs):
    b = full_marks()
    b.remove("S2")
    b.items.extend(evs)
    return item(score_round(b.items, parse_config(raw_config()), context()), "S2")


@pytest.mark.parametrize("card,msg", [
    ({}, "固定话术"),
    ({"fixed_script": {"version": "script-1", "text": "  "}}, "固定话术"),
    ({"fixed_script": SCRIPT}, "校准记录"),
    ({"fixed_script": SCRIPT, "s2_calibration": {**CAL, "fixed_script_version": "script-0"}}, "重新校准"),
])
def test_s2_refuses_without_fixed_script_and_matching_calibration(monkeypatch, card, msg):
    """缺少固定话术或对应的校准版本时 S2 不能自动出分：检测器失败 → 条目缺证据，而不是 0 分或满分。"""
    ctx, calls = s2_ctx(monkeypatch, {}, card)
    with pytest.raises(S2NotCalibrated, match=msg):
        s2(ctx)
    assert calls == []  # 不调用模型


def test_s2_single_level_evidence_traceable_to_quote_script_and_calibration(monkeypatch):
    ctx, calls = s2_ctx(monkeypatch, {"score": 37, "quote": "这款产品就三个好", "reason": "话术讲到大部分", "confidence": 0.8,
                                      "errors": [{"quote": "没有等待期", "reason": "与条款不符", "confidence": 0.8}]})
    (ev,) = s2(ctx)
    assert (ev.kind, ev.ref, ev.judgment) == ("level", "fixed_script_accuracy", 37)
    assert ev.label == "fixed_script=script-1;calibration=cal-1"
    assert (ev.start_ms, ev.end_ms) == (500, 1300) and "没有等待期" in ev.reason
    task, payload = calls[0]
    assert task == "s2_fixed_script" and payload["fixed_script"] == SCRIPT["text"] and payload["max_score"] == 50
    assert payload["anchors"] == CAL["anchors"]
    res = s2_score([ev])
    assert res.status == "scored" and res.score == 37


def test_s2_zero_without_quote_scores_zero(monkeypatch):
    ctx, _ = s2_ctx(monkeypatch, {"score": 0, "quote": "", "reason": "没讲产品", "confidence": 0.9, "errors": []})
    (ev,) = s2(ctx)
    assert ev.quote is None and s2_score([ev]).score == 0


@pytest.mark.parametrize("response,msg", [
    ({"score": 30, "quote": "", "reason": "", "confidence": 0.9, "errors": []}, "没有引用"),
    ({"score": 30, "quote": "原文里没有的话", "reason": "", "confidence": 0.9, "errors": []}, "引用无法"),
    ({"score": 51, "quote": "真实原文", "reason": "", "confidence": 0.9, "errors": []}, "0–50"),
])
def test_s2_bad_model_output_fails_detector(monkeypatch, response, msg):
    ctx, _ = s2_ctx(monkeypatch, response)
    with pytest.raises(ValueError, match=msg):
        s2(ctx)


@pytest.mark.parametrize("level,ok", [(0, True), (10, True), (11, False), (-1, False)])
def test_s1_subjective_level_range(monkeypatch, level, ok):
    ctx = make_ctx()
    monkeypatch.setattr(ctx, "ask", lambda *a: {"level": level, "quote": "真实原文" if level else "", "reason": "", "confidence": 0.9})
    if ok:
        assert s1(ctx)[0].judgment == level
    else:
        with pytest.raises(ValueError, match="0–10"):
            s1(ctx)


def _persona_ctx(providers):
    ctx = make_ctx()
    ctx.segments = [{"segment": "main", "start_ms": 0, "end_ms": 60_000}, {"segment": "reading", "start_ms": 60_000, "end_ms": 90_000}]
    ctx.reading_text = "各位家长大家好"
    ctx.media = SimpleNamespace(audio={"main": "main.wav", "reading": "reading.wav"}, appearance_frames=["f"])
    ctx.providers = providers
    return ctx


def test_p3_counts_dialect_only_in_reading_segment():
    errors = [{"text": "家", "start_ms": 1000, "end_ms": 1200, "type": "dialect", "confidence": 0.8},
              {"text": "好", "start_ms": 2000, "end_ms": 2200, "type": "mispronounce", "confidence": 0.8}]
    speech = SimpleNamespace(assess=lambda audio, ref: SpeechEvalResult(80, {"errors": errors}, "x", "1"))
    evs = persona.p3(_persona_ctx(SimpleNamespace(speech_eval=speech)))
    assert [(e.label, e.judgment, e.start_ms, e.segment) for e in evs] == [("dialect", "count", 61_000, "reading"),
                                                                         ("mispronounce", "not_count", 62_000, "reading")]
    b = full_marks()
    b.remove("P3")
    b.items.extend(evs)
    assert item(score_round(b.items, parse_config(raw_config()), context()), "P3").score == 9
    speech = SimpleNamespace(assess=lambda audio, ref: SpeechEvalResult(80, {}, "x", "1"))
    with pytest.raises(ValueError, match="逐处问题"):
        persona.p3(_persona_ctx(SimpleNamespace(speech_eval=speech)))


def test_p1_attire_finding_deducts_ten():
    found = [VisionFinding(0, 30_000, "attire", "count", 0.8, "穿着不符合要求"), VisionFinding(0, 30_000, "hairstyle", "not_count", 0.8, "")]
    evs = persona.p1(_persona_ctx(SimpleNamespace(vision=SimpleNamespace(analyze=lambda *a: found))))
    b = full_marks()
    b.remove("P1")
    b.items.extend(evs)
    assert item(score_round(b.items, parse_config(raw_config()), context()), "P1").score == 0
    bad = [VisionFinding(0, 1, "appearance", 10, 0.8, "")]  # 不判相貌等其他方面
    with pytest.raises(ValueError, match="穿着或发型"):
        persona.p1(_persona_ctx(SimpleNamespace(vision=SimpleNamespace(analyze=lambda *a: bad))))


@pytest.mark.parametrize("score,ok", [(5, True), (0, True), (6, False)])
def test_p6_voice_rating_range(score, ok):
    voice = SimpleNamespace(rate=lambda *a, **k: VoiceRating(score, 0.7, "音色"))
    ctx = _persona_ctx(SimpleNamespace(voice=voice))
    ctx.acoustic = {"main": {"pitch_range_st": 6.0, "loudness_range_db": 8.0}}
    if ok:
        (ev,) = persona.p6(ctx)
        assert (ev.item_id, ev.kind, ev.judgment, ev.source) == ("P6", "level", score, "audio")
    else:
        with pytest.raises(ValueError, match="0–5"):
            persona.p6(ctx)


def test_detectors_match_current_rubric_but_not_legacy():
    assert unsupported_items(parse_config(raw_config())) == []
    bad = unsupported_items(parse_config(legacy_raw()))
    assert any(b.startswith("S2") for b in bad) and any(b.startswith("O5") for b in bad)
