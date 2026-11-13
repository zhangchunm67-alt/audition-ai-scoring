"""录播观众异议自动识别：引用必须能在逐字稿里定位，同一处只取一条。"""
from app.pipeline import live_objections
from app.pipeline.text import SegmentText
from app.providers.base import Word


def _st(text: str) -> SegmentText:
    return SegmentText("main", [Word(ch, k * 1000, (k + 1) * 1000, 1.0) for k, ch in enumerate(text)])


class _LLM:
    name, model_version = "fake", "1"

    def __init__(self, items):
        self.items = items

    def complete_json(self, task, system, user, schema, *, temperature, payload):
        assert task == "live_objections" and temperature == 0
        return {"items": self.items}


def _it(question, quote, confidence=0.9):
    return {"question": question, "quote": quote, "reason": "", "confidence": confidence}


TEXT = "大家好欢迎来到直播间。有朋友问等待期多久，我们这款是九十天。接着讲保障范围。刚才有人说太贵了，其实每天几块钱。"


def test_detect_locates_sorts_and_drops_what_cannot_be_grounded():
    st = _st(TEXT)
    found = live_objections.detect(_LLM([
        _it("太贵了", "刚才有人说太贵了"),
        _it("等待期多久", "有朋友问等待期多久"),
        _it("同一处又列一次", "有朋友问等待期多久，我们这款是九十天"),
        _it("编的", "这句话逐字稿里完全不存在哦"),
        _it("没把握", "接着讲保障范围", confidence=0.3),
        _it("  ", "接着讲保障范围"),
    ]), st)
    assert [f["text"] for f in found] == ["等待期多久", "太贵了"]
    assert found[0]["video_ms"] == TEXT.index("有朋友问") * 1000 and found[1]["video_ms"] == TEXT.index("刚才有人说") * 1000


def test_empty_transcript_asks_nothing():
    assert live_objections.detect(_LLM([_it("x", "y")]), _st("")) == []


def test_records_look_like_manual_marks_plus_source():
    sheet, times = live_objections.as_records([{"text": "等待期多久", "video_ms": 12000}])
    assert sheet[0]["text"] == "等待期多久" and sheet[0]["source"] == "auto" and sheet[0]["objection_id"] == times[0]["objection_id"]
    assert times[0]["video_ms"] == times[0]["at_ms"] == 12000 and times[0]["source"] == "auto"
