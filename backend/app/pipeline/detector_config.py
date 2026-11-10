from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

PATH = Path(__file__).resolve().parents[3] / "config" / "detectors" / "detectors-v3.yaml"


class _N(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pending: list[str] = Field(default_factory=list)
    calibration_required: bool = False


class Category(_N):
    label: str
    pattern: str


class DetectorConfig(_N):
    version: str
    status: str = "draft"

    class Asr(_N):
        disfluency_removal: bool
        word_timestamps: bool

    class Frames(_N):
        appearance_every_s: int = 30
        motion_fps: int = 1

    class P2(_N):
        categories: list[Category]

    class P7(_N):
        pause_ms: int
        run_on_ms: int
        stall_gap_ms: int
        objection_grace_ms: int
        repetition_patterns: list[str]

    class P8(_N):
        merge_within_ms: int

    class P9(_N):
        scan_every_s: float = 3.0  # 每隔几秒抽一帧直接看画面
        guide_phrases: list[str]  # 引导语前后的帧额外补看
        episode_gap_ms: int = 6000  # 同一块道具的相邻命中帧间隔不超过此值，算同一次使用
        dedupe_within_ms: int  # 同一块内容在此时长内重复使用只算 1 次

    class O4(_N):
        dead_air_ms: int

    class Redlines(_N):
        context_chars: int

    class HumanReview(_N):
        manual: list[str] = Field(default_factory=list)  # 只由评委打分
        confirm: list[str] = Field(default_factory=list)  # 机器建议分，评委确认
        confirm_on_deduction: list[str] = Field(default_factory=list)  # 机器判扣分时评委确认
        fallback: bool = False  # 机器评不出时转评委打分

    asr: Asr
    frames: Frames
    p2: P2
    p7: P7
    p8: P8
    p9: P9
    o4: O4
    redlines: Redlines
    human_review: HumanReview = Field(default_factory=HumanReview)  # v2 及以前没有：全部机器评

    def model_post_init(self, _ctx) -> None:
        if self.asr.disfluency_removal or not self.asr.word_timestamps:
            raise ValueError("检测配置必须关闭顺滑并要求字级时间戳")


def parse(data: dict) -> DetectorConfig:
    return DetectorConfig.model_validate(data)


def load_file(path: Path = PATH) -> tuple[DetectorConfig, dict]:
    data = yaml.safe_load(path.read_text("utf-8"))
    return parse(data), data


def content_hash(data: dict) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
