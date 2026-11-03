"""流水线里的纯函数：字数统计（数字按读音）、原句定位、分句、声学特征、检测配置校验。"""
import subprocess
import wave

import numpy as np
import pytest

from app.pipeline import acoustic
from app.pipeline.detector_config import load_file, parse
from app.pipeline.text import SegmentText, _read_int, char_count, locate, sentences, spoken
from app.providers.base import Word


@pytest.mark.parametrize("n,s", [(0, "零"), (10, "十"), (15, "十五"), (105, "一百零五"), (365, "三百六十五"), (1001, "一千零一"),
                                 (10000, "一万"), (105000, "十万五千"), (100010, "十万零一十"), (1000500, "一百万零五百")])
def test_read_int(n, s):
    assert _read_int(n) == s


def test_spoken_and_char_count():
    assert spoken("一年365元") == "一年三百六十五元"
    assert spoken("2026年") == "二零二六年" and spoken("3年") == "三年"
    assert spoken("100%") == "百分之一百" and spoken("3.5天") == "三点五天"
    assert char_count("免赔额0元，等待期30天") == 11  # 免赔额零元 + 等待期三十天，标点不计


def _st(text: str, start=1000, step=100) -> SegmentText:
    return SegmentText("main", [Word(c, start + i * step, start + (i + 1) * step, 0.5 if c == "低" else 0.95) for i, c in enumerate(text)])


def test_sentences_and_locate():
    st = _st("那么我们来看。这款产品很好！低置信的句子？")
    ss = sentences(st)
    assert [s.text for s in ss] == ["那么我们来看。", "这款产品很好！", "低置信的句子？"]
    assert ss[1].start_ms == 1000 + 7 * 100
    assert locate(st, "这款产品很好") == (1700, 2300)
    assert locate(st, "这款，产品很好") == (1700, 2300)  # 忽略标点差异
    assert locate(st, "不存在") is None
    assert locate(st, "那么", after_ms=1500) is None
    assert st.min_confidence(14, 20) == 0.5


def _wav(path, signal, sr=16000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(sr)
        w.writeframes((np.clip(signal, -1, 1) * 32767).astype(np.int16).tobytes())


def test_acoustic_features(tmp_path):
    sr = 16000
    t = np.arange(sr * 2) / sr
    flat = 0.3 * np.sin(2 * np.pi * 200 * t)
    gliss = 0.3 * np.sin(2 * np.pi * (150 * t + 50 * t**2))  # 150 Hz → 350 Hz
    silence = np.zeros(sr)
    _wav(tmp_path / "flat.wav", np.concatenate([flat, silence, flat]))
    _wav(tmp_path / "gliss.wav", np.concatenate([gliss, 0.05 * gliss]))
    f = acoustic.features(str(tmp_path / "flat.wav"))
    assert f["pitch_range_st"] < 1 and any(b - a >= 900 for a, b in f["silences_ms"])
    g = acoustic.features(str(tmp_path / "gliss.wav"))
    assert g["pitch_range_st"] > 8 and g["loudness_range_db"] > 10


def test_detector_config_must_keep_disfluencies():
    cfg, data = load_file()
    assert cfg.asr.disfluency_removal is False and len(cfg.p2.categories) == 8
    bad = {**data, "asr": {"disfluency_removal": True, "word_timestamps": True}}
    with pytest.raises(ValueError, match="顺滑"):
        parse(bad)


def test_mock_asr_spreads_words_after_objections(tmp_path):
    from app.providers.base import SegmentHint
    from app.providers.mock import MockASR

    p = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "120", str(p)], check=True)
    r = MockASR().transcribe(str(p), disfluency_removal=False, word_timestamps=True,
                             hint=SegmentHint("main", objection_offsets_ms=[60000], objection_texts=["孩子有医保了，还需要买吗？"]))
    assert r.params["disfluency_removal"] is False
    after = "".join(w.text for w in r.words if w.start_ms >= 60000)
    assert after.startswith("孩子有医保了还需要买吗") and r.words[-1].end_ms <= 120000
