"""首次用本地模型整段跑出的两个问题：证据挂到上一句、同一处被重复计数。"""
from types import SimpleNamespace

from app.pipeline.detectors.logic_other import _founds
from app.pipeline.text import SegmentText, sentences
from app.providers.base import Word
from app.services.report_view import _sentence_index


def _chained(text: str, per_char_ms: int = 100) -> SegmentText:
    """和 SenseVoice 一样：每个字（含标点）的结束时间就是下一个字的开始时间。"""
    return SegmentText("main", [Word(ch, k * per_char_ms, (k + 1) * per_char_ms, 1.0) for k, ch in enumerate(text)])


def test_evidence_quoting_a_whole_sentence_goes_to_that_sentence_not_the_previous_one():
    st = _chained("不合适随时取消。现在身体好一定提前买。然后继续讲优势。")
    sents = sentences(st)
    second = sents[1]
    assert sents[0].end_ms == second.start_ms  # 时间戳首尾相接，旧的闭区间比较会把它挂到第一句
    assert _sentence_index(sents, second.start_ms, second.end_ms) == 1
    assert _sentence_index(sents, second.start_ms, None) == 1  # 只有时间点的证据
    assert _sentence_index(sents, sents[0].start_ms, sents[0].end_ms) == 0


def test_evidence_spanning_two_sentences_goes_to_the_one_it_overlaps_most():
    sents = sentences(_chained("短句。这是一句长得多的话用来占时间。"))
    assert _sentence_index(sents, sents[0].end_ms - 100, sents[1].end_ms) == 1


def test_evidence_in_a_gap_goes_to_the_sentence_starting_right_after_or_nowhere():
    words = [Word("好", 0, 100, 1.0), Word("。", 100, 200, 1.0), Word("来", 1000, 1100, 1.0), Word("。", 1100, 1200, 1.0)]
    sents = sentences(SegmentText("main", words))
    assert _sentence_index(sents, 900, None) == 1
    assert _sentence_index(sents, 500, None) is None


class _Ctx:
    def __init__(self, items, text):
        self.items, self.main, self.n = items, _chained(text), 0

    def ask(self, task, payload):
        return {"items": self.items}

    def quote_ev(self, item, kind, quote, **kw):
        a = self.main.text.find(quote)
        self.n += 1
        return SimpleNamespace(evidence_id=self.n, quote=quote, label=kw["label"], judgment=kw["judgment"],
                               start_ms=None if a < 0 else a * 100, end_ms=None if a < 0 else (a + len(quote)) * 100)


def _item(quote, valid=False, label=""):
    return {"quote": quote, "valid": valid, "label": label, "reason": "", "confidence": 0.9}


def test_same_place_listed_twice_is_counted_once():
    text = "扛不住三五十万就必须买。大家看一下保障。趁健康提前买保险。"
    ctx = _Ctx([_item("扛不住三五十万就必须买"), _item("扛不住三五十万就必须买。"), _item("趁健康提前买保险")], text)
    out = _founds(ctx, "l3_deduction", "L3", "occurrence", label=lambda x: "deductive_error", judge=lambda x: "count")
    assert [e.quote for e in out] == ["扛不住三五十万就必须买", "趁健康提前买保险"]


def test_two_terms_in_one_sentence_are_both_kept_and_unlocated_ones_are_not_merged():
    text = "等待期就是观察期，免赔额就是自己先掏的钱。"
    whole = text.rstrip("。")
    ctx = _Ctx([_item(whole, True, "等待期"), _item(whole, True, "免赔额"), _item("原文里没有", True, "x"), _item("原文里也没有", True, "x")], text)
    out = _founds(ctx, "o1_terms", "O1", "instance")
    assert [e.label for e in out] == ["等待期", "免赔额", "x", "x"]
