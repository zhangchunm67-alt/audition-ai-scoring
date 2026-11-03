"""媒体准备（只在首轮做一次，C11“不重新转码”）：按分段抽 16 kHz 单声道音频，抽帧（P1 每 30 秒 1 帧、P8 每秒 1 帧）。
派生媒体与原视频同样到期删除（含人脸和声音）。之后每一轮从语音识别起重跑，复用这些派生媒体。
"""
from __future__ import annotations

import io
import re
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.entities import MediaAsset, Recording
from ..providers.base import Frame
from ..services.storage import Storage
from .detector_config import DetectorConfig


class MediaError(RuntimeError):
    pass


@dataclass
class Prepared:
    audio: dict[str, str]  # 分段 → 本地 wav 路径
    offsets: dict[str, int]  # 分段 → 起点（视频毫秒）
    appearance_frames: list[Frame]
    motion_frames: list[Frame]


def _safe(seg: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", seg)


def _ffmpeg(*args: str) -> None:
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise MediaError(f"ffmpeg 失败：{r.stderr.strip()[:300]}")


def _raw(db: Session, rec: Recording) -> MediaAsset:
    v = db.scalar(select(MediaAsset).where(MediaAsset.recording_id == rec.id, MediaAsset.kind == "raw_video", MediaAsset.deleted_at.is_(None)))
    if v is None:
        raise MediaError("原视频不存在或已删除")
    return v


def _derived(db: Session, rec: Recording) -> dict[tuple[str, str], MediaAsset]:
    rows = db.scalars(select(MediaAsset).where(MediaAsset.recording_id == rec.id, MediaAsset.kind.in_(["audio", "frame"]), MediaAsset.deleted_at.is_(None)))
    return {(a.kind, a.segment or ""): a for a in rows}


def _frames_tar(src: str, start_ms: int, end_ms: int, fps: float, out_dir: Path) -> bytes:
    out_dir.mkdir(parents=True, exist_ok=True)
    if fps < 1:  # 稀疏抽帧：第一帧必取，之后每隔 1/fps 秒取一帧
        vf = f"select='isnan(prev_selected_t)+gte(t-prev_selected_t\\,{1 / fps:g})',scale=640:-2"
        extra = ["-vsync", "vfr"]
    else:
        vf, extra = f"fps={fps},scale=640:-2", []
    _ffmpeg("-ss", f"{start_ms / 1000:.3f}", "-to", f"{end_ms / 1000:.3f}", "-i", src, "-vf", vf, *extra, "-q:v", "4", str(out_dir / "%06d.jpg"))
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for p in sorted(out_dir.glob("*.jpg")):
            tar.add(p, arcname=p.name)
    return buf.getvalue()


def prepare(db: Session, rec: Recording, storage: Storage, cfg: DetectorConfig, workdir: Path) -> None:
    raw = _raw(db, rec)
    have = _derived(db, rec)
    src = storage.probe_location(raw.storage_key)
    for s in rec.segments:
        name = s["segment"]
        if ("audio", name) in have:
            continue
        wav = workdir / f"{_safe(name)}.wav"
        _ffmpeg("-ss", f"{s['start_ms'] / 1000:.3f}", "-to", f"{s['end_ms'] / 1000:.3f}", "-i", src, "-vn", "-ac", "1", "-ar", "16000", str(wav))
        key = f"recordings/{rec.id}/derived/audio/{_safe(name)}.wav"
        storage.put(key, wav.read_bytes(), "audio/wav")
        db.add(MediaAsset(recording_id=rec.id, kind="audio", segment=name, storage_key=key, size_bytes=wav.stat().st_size,
                          content_type="audio/wav", encrypted=storage.encrypted, retention_until=raw.retention_until))
    main = next(s for s in rec.segments if s["segment"] == "main")
    for label, fps in (("appearance", 1 / cfg.frames.appearance_every_s), ("motion", cfg.frames.motion_fps)):
        if ("frame", label) in have:
            continue
        data = _frames_tar(src, main["start_ms"], main["end_ms"], fps, workdir / label)
        key = f"recordings/{rec.id}/derived/frames/{label}.tar"
        storage.put(key, data, "application/x-tar")
        db.add(MediaAsset(recording_id=rec.id, kind="frame", segment=label, storage_key=key, size_bytes=len(data),
                          content_type="application/x-tar", encrypted=storage.encrypted, retention_until=raw.retention_until))
    db.flush()


def materialize(db: Session, rec: Recording, storage: Storage, cfg: DetectorConfig, workdir: Path) -> Prepared:
    have = _derived(db, rec)
    audio, offsets = {}, {}
    for s in rec.segments:
        a = have.get(("audio", s["segment"]))
        if a is None:
            raise MediaError(f"缺少分段音频 {s['segment']}，请先完成媒体准备")
        p = workdir / f"{_safe(s['segment'])}.wav"
        p.write_bytes(b"".join(storage.read_range(a.storage_key, 0, storage.size(a.storage_key) - 1)))
        audio[s["segment"]], offsets[s["segment"]] = str(p), s["start_ms"]
    main = next(s for s in rec.segments if s["segment"] == "main")
    frames: dict[str, list[Frame]] = {}
    for label, step_ms in (("appearance", cfg.frames.appearance_every_s * 1000), ("motion", 1000 // cfg.frames.motion_fps)):
        a = have.get(("frame", label))
        d = workdir / f"frames-{label}"
        d.mkdir(exist_ok=True)
        if a is None:
            raise MediaError(f"缺少抽帧 {label}")
        blob = b"".join(storage.read_range(a.storage_key, 0, storage.size(a.storage_key) - 1))
        with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
            tar.extractall(d, filter="data")
        frames[label] = [Frame(str(p), main["start_ms"] + i * step_ms) for i, p in enumerate(sorted(d.glob("*.jpg")))]
    return Prepared(audio, offsets, frames["appearance"], frames["motion"])
