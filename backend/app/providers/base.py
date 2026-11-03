"""外部 AI 能力的接口。真实供应商（须为境内服务）和 Mock 都实现这些接口；流水线只依赖接口。

强制约束：
- 语音识别：必须关闭顺滑（disfluency_removal=False），保留口头禅；必须返回字级时间戳。
- 大模型：温度固定为 0（C5），结构化 JSON 输出，按 schema 校验。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class ProviderError(RuntimeError):
    """供应商调用失败（网络、限流、返回格式不对）。流水线会按策略重试。"""


@dataclass
class Word:
    text: str  # 一个字或一个标点
    start_ms: int
    end_ms: int
    confidence: float = 1.0


@dataclass
class TranscriptResult:
    words: list[Word]
    provider: str
    model_version: str
    params: dict[str, Any]

    @property
    def text(self) -> str:
        return "".join(w.text for w in self.words)


@dataclass
class SegmentHint:
    """只给 Mock 用的上下文（真实供应商忽略）：分段名、题单内容、异议相对时间。"""

    segment: str
    reading_text: str | None = None
    question_text: str | None = None
    objection_offsets_ms: list[int] = field(default_factory=list)  # 相对本段起点
    objection_texts: list[str] = field(default_factory=list)
    round_no: int = 1


class ASR(Protocol):
    name: str
    model_version: str

    def transcribe(self, audio_path: str, *, disfluency_removal: bool, word_timestamps: bool, hint: SegmentHint) -> TranscriptResult: ...


@dataclass
class SpeechEvalResult:
    score: float  # 0–100
    details: dict[str, Any]
    provider: str
    model_version: str


class SpeechEval(Protocol):
    name: str
    model_version: str

    def assess(self, audio_path: str, reference_text: str) -> SpeechEvalResult: ...


class LLM(Protocol):
    name: str
    model_version: str

    def complete_json(self, task: str, system: str, user: str, schema: dict, *, temperature: float, payload: dict) -> dict:
        """payload 是结构化输入（真实实现只用 system/user 文本；Mock 用 payload 做规则判断）。"""
        ...


@dataclass
class Frame:
    path: str
    at_ms: int


@dataclass
class VisionFinding:
    at_ms: int
    end_ms: int
    label: str
    judgment: str | int
    confidence: float
    reason: str


class Vision(Protocol):
    name: str
    model_version: str

    def analyze(self, task: str, frames: list[Frame], context: dict) -> list[VisionFinding]: ...


@dataclass
class LaughCandidate:
    start_ms: int
    end_ms: int
    confidence: float


class LaughDetector(Protocol):
    name: str
    model_version: str

    def detect(self, audio_path: str) -> list[LaughCandidate]: ...


@dataclass
class Providers:
    asr: ASR
    speech_eval: SpeechEval
    llm: LLM
    vision: Vision
    laugh: LaughDetector

    def manifest(self) -> dict[str, str]:
        return {
            "asr": f"{self.asr.name}@{self.asr.model_version}",
            "speech_eval": f"{self.speech_eval.name}@{self.speech_eval.model_version}",
            "llm": f"{self.llm.name}@{self.llm.model_version}",
            "vision": f"{self.vision.name}@{self.vision.model_version}",
            "laugh": f"{self.laugh.name}@{self.laugh.model_version}",
        }
