"""用 ffprobe 读取视频信息。"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass


class ProbeError(ValueError):
    pass


@dataclass
class ProbeInfo:
    duration_ms: int
    has_video: bool
    has_audio: bool
    width: int | None
    height: int | None
    format_name: str


def probe(location: str, timeout: int = 120) -> ProbeInfo:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", location],
            capture_output=True, timeout=timeout, check=True,
        ).stdout
        data = json.loads(out)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        raise ProbeError("无法识别的视频文件") from exc
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    try:
        duration = float(data.get("format", {}).get("duration") or video.get("duration"))  # type: ignore[union-attr]
    except (TypeError, ValueError, AttributeError) as exc:
        raise ProbeError("读不出视频时长") from exc
    return ProbeInfo(
        duration_ms=round(duration * 1000), has_video=video is not None, has_audio=audio is not None,
        width=video.get("width") if video else None, height=video.get("height") if video else None,
        format_name=data.get("format", {}).get("format_name", ""),
    )
