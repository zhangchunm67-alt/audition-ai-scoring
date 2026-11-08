"""本地语音能力（sherpa-onnx，CPU 即可，Linux / macOS 通用）：
- SherpaSenseVoiceASR：SenseVoice 语音识别，silero VAD 切段（SenseVoice 单段须短于 30 秒），逐字时间戳。
  SenseVoice 不输出逐字置信度（ys_log_probs 为空），置信度一律记 1.0，所以语音识别不会触发低置信标记；
- SherpaLaughDetector：CED 音频事件分类，滑窗找“笑声”候选，是否算“嘻嘻哈哈”仍由大模型结合上下文判断（P10）。

模型文件从 sherpa-onnx 的 GitHub Releases 下载（见 scripts/download_models.sh），目录通过环境变量传入。
SenseVoice 没有“顺滑”后处理开关，本实现也不做任何口头禅过滤；但模型本身会不会漏识别口头禅只能实测（见 README）。
"""
from __future__ import annotations

import csv
import math
import os
import wave
from functools import cached_property
from pathlib import Path

import numpy as np

from .base import LaughCandidate, ProviderError, SegmentHint, TranscriptResult, Word

SR = 16000


def read_wav(path: str) -> np.ndarray:
    with wave.open(path, "rb") as w:
        if w.getframerate() != SR or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ProviderError(f"{path}: 需要 16 kHz 单声道 16 位 wav")
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


def _need(path: Path) -> str:
    if not path.exists():
        raise ProviderError(f"模型文件不存在：{path}（先运行 scripts/download_models.sh）")
    return str(path)


class SherpaSenseVoiceASR:
    name = "sherpa-sensevoice"

    def __init__(self, model_dir: str, vad_model: str, *, num_threads: int = 4, use_int8: bool = True,
                 max_segment_s: float = 20.0, min_silence_s: float = 0.25):
        self.model_dir, self.vad_model = Path(model_dir), Path(vad_model)
        self.num_threads, self.use_int8 = num_threads, use_int8
        self.max_segment_s, self.min_silence_s = max_segment_s, min_silence_s
        self.model_version = f"{self.model_dir.name}{'-int8' if use_int8 else ''}"

    @cached_property
    def _rec(self):
        import sherpa_onnx

        model = self.model_dir / ("model.int8.onnx" if self.use_int8 else "model.onnx")
        return sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=_need(model), tokens=_need(self.model_dir / "tokens.txt"), use_itn=True, language="zh",
            num_threads=self.num_threads)

    def _segments(self, x: np.ndarray) -> list[tuple[int, np.ndarray]]:
        """VAD 切出语音段，返回 [(起点采样序号, 波形)]。"""
        import sherpa_onnx

        cfg = sherpa_onnx.VadModelConfig()
        cfg.silero_vad.model = _need(self.vad_model)
        cfg.silero_vad.min_silence_duration = self.min_silence_s
        cfg.silero_vad.max_speech_duration = self.max_segment_s
        cfg.sample_rate = SR
        vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=int(len(x) / SR) + 60)
        win = cfg.silero_vad.window_size
        out = []
        for i in range(0, len(x), win):
            vad.accept_waveform(x[i: i + win])
            while not vad.empty():
                out.append((vad.front.start, np.array(vad.front.samples, dtype=np.float32)))
                vad.pop()
        vad.flush()
        while not vad.empty():
            out.append((vad.front.start, np.array(vad.front.samples, dtype=np.float32)))
            vad.pop()
        return out

    def transcribe(self, audio_path: str, *, disfluency_removal: bool, word_timestamps: bool, hint: SegmentHint) -> TranscriptResult:
        if disfluency_removal or not word_timestamps:
            raise ProviderError("必须关闭顺滑并返回字级时间戳")
        x = read_wav(audio_path)
        words: list[Word] = []
        for start, seg in self._segments(x):
            s = self._rec.create_stream()
            s.accept_waveform(SR, seg)
            self._rec.decode_stream(s)
            r = s.result
            base = start * 1000 // SR
            seg_end = base + len(seg) * 1000 // SR
            probs = list(r.ys_log_probs) if len(r.ys_log_probs) == len(r.tokens) else [0.0] * len(r.tokens)
            for k, (tok, t) in enumerate(zip(r.tokens, r.timestamps)):
                a = base + int(t * 1000)
                b = base + int(r.timestamps[k + 1] * 1000) if k + 1 < len(r.timestamps) else seg_end
                words.append(Word(tok, a, max(a + 1, b), round(min(1.0, math.exp(probs[k])), 3)))
            if words and words[-1].text not in "。！？；，,.!?;":
                words.append(Word("，", seg_end, seg_end + 1, 1.0))  # 段间停顿处补逗号，避免跨段粘连
        return TranscriptResult(words, self.name, self.model_version, {
            "disfluency_removal": False, "word_timestamps": True, "use_itn": True, "vad": "silero",
            "note": "SenseVoice 无顺滑开关，未做任何口头禅过滤；不提供逐字置信度（记 1.0）"})


class SherpaLaughDetector:
    """CED 音频事件分类：2 秒窗、1 秒步长，“Laughter”类概率超过阈值的窗合并为一个候选。"""

    name = "sherpa-ced"
    LABELS = ("Laughter", "Giggle", "Chuckle, chortle", "Belly laugh", "Snicker")

    def __init__(self, model_dir: str, *, threshold: float = 0.3, window_s: float = 2.0, hop_s: float = 1.0, num_threads: int = 4):
        self.model_dir, self.threshold, self.window_s, self.hop_s = Path(model_dir), threshold, window_s, hop_s
        self.num_threads = num_threads
        self.model_version = self.model_dir.name

    @cached_property
    def _tagger(self):
        import sherpa_onnx

        model = next((p for p in (self.model_dir / "model.int8.onnx", self.model_dir / "model.onnx") if p.exists()), None)
        if model is None:
            raise ProviderError(f"{self.model_dir} 下没有 CED 模型（先运行 scripts/download_models.sh）")
        cfg = sherpa_onnx.AudioTaggingConfig(
            model=sherpa_onnx.AudioTaggingModelConfig(ced=str(model), num_threads=self.num_threads),
            labels=_need(self.model_dir / "class_labels_indices.csv"), top_k=10)
        return sherpa_onnx.AudioTagging(cfg)

    @cached_property
    def _laugh_names(self) -> set[str]:
        with open(self.model_dir / "class_labels_indices.csv", encoding="utf-8") as fh:
            names = {row["display_name"] for row in csv.DictReader(fh)}
        found = names & set(self.LABELS)
        if not found:
            raise ProviderError("CED 标签表里没有笑声类别")
        return found

    def detect(self, audio_path: str) -> list[LaughCandidate]:
        x = read_wav(audio_path)
        win, hop = int(self.window_s * SR), int(self.hop_s * SR)
        hits: list[tuple[int, int, float]] = []
        for i in range(0, max(1, len(x) - win + 1), hop):
            s = self._tagger.create_stream()
            s.accept_waveform(SR, x[i: i + win])
            p = max((e.prob for e in self._tagger.compute(s) if e.name in self._laugh_names), default=0.0)
            if p >= self.threshold:
                a, b = i * 1000 // SR, (i + win) * 1000 // SR
                if hits and a <= hits[-1][1]:
                    hits[-1] = (hits[-1][0], b, max(hits[-1][2], p))
                else:
                    hits.append((a, b, p))
        return [LaughCandidate(a, b, round(float(p), 3)) for a, b, p in hits]


def from_env() -> dict:
    """按环境变量构造本地语音能力；未配置的返回 None。"""
    out = {}
    if os.environ.get("APP_SENSEVOICE_DIR"):
        out["asr"] = SherpaSenseVoiceASR(os.environ["APP_SENSEVOICE_DIR"], os.environ.get("APP_VAD_MODEL", ""),
                                         num_threads=int(os.environ.get("APP_ASR_THREADS", "4")))
    if os.environ.get("APP_CED_DIR"):
        out["laugh"] = SherpaLaughDetector(os.environ["APP_CED_DIR"], threshold=float(os.environ.get("APP_LAUGH_THRESHOLD", "0.3")))
    return out
