"""本地声学特征（不调用外部服务）：音量起伏、音高起伏、静音和停顿。
- features()：流水线用的整段特征（P5–P7 声音评价的参考输入、O4、冷场判断）；
- profile()：报告里的“声音测量（参考，不计分）”，逐分钟的音高、音量起伏和停顿、连续说话统计。
评分表 P5 语调、P6 音色、P7 节奏都是“根据主观打分”，这些测量值只作参考和校准用，不按阈值换算成分数。
"""
from __future__ import annotations

import wave
from dataclasses import dataclass

import numpy as np

HOP_S, WIN_S = 0.01, 0.03
F0_MIN, F0_MAX = 75.0, 600.0  # 音高搜索范围。上限原为 400 Hz，女声经常超过，会把音高起伏测小（2026-11-09 改）
PITCH_EVERY = 3  # 每 3 帧（30 毫秒）估一次音高
SILENCE_S = 0.3


def _read(path: str) -> tuple[np.ndarray, int]:
    with wave.open(path, "rb") as w:
        sr, n = w.getframerate(), w.getnframes()
        x = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
    return x, sr


def _period(fr: np.ndarray, sr: int, win: int) -> float | None:
    """自相关估音高。取“达到最大峰 90% 的最短周期”的局部峰：
    只取最大峰容易落到两倍周期上（音高测低一个八度），提高上限后也不会因此偏向更高的八度。"""
    fr = fr - fr.mean()
    ac = np.correlate(fr, fr, mode="full")[win - 1:]
    lo, hi = int(sr / F0_MAX), int(sr / F0_MIN)
    if ac[0] <= 0 or hi + 1 >= len(ac):
        return None
    seg = ac[lo: hi + 1]
    peak = float(seg.max())
    if peak / ac[0] <= 0.5:
        return None
    for k in range(1, len(seg) - 1):
        if seg[k] >= 0.9 * peak and seg[k] >= seg[k - 1] and seg[k] >= seg[k + 1]:
            return sr / (lo + k)
    return sr / (lo + int(np.argmax(seg)))


@dataclass
class _Frames:
    rms_db: np.ndarray  # 每 10 毫秒一帧
    voiced: np.ndarray
    f0: np.ndarray  # 每 10 毫秒一格，未估或无声为 nan
    silences_ms: list[list[int]]  # ≥ 0.3 秒的静音，相对本段起点


def _analyze(x: np.ndarray, sr: int) -> _Frames | None:
    hop, win = int(sr * HOP_S), int(sr * WIN_S)
    if len(x) < win * 2:
        return None
    frames = np.lib.stride_tricks.sliding_window_view(x, win)[::hop]
    rms_db = 20 * np.log10(np.sqrt((frames**2).mean(axis=1)) + 1e-9)
    voiced = rms_db > max(-50.0, float(np.percentile(rms_db, 95)) - 30.0)
    f0 = np.full(len(frames), np.nan)
    for i in range(0, len(frames), PITCH_EVERY):
        if voiced[i]:
            p = _period(frames[i], sr, win)
            if p is not None:
                f0[i] = p
    sil, start = [], None
    for i, v in enumerate(voiced):
        if not v and start is None:
            start = i
        elif v and start is not None:
            if (i - start) * HOP_S >= SILENCE_S:
                sil.append([int(start * HOP_S * 1000), int(i * HOP_S * 1000)])
            start = None
    if start is not None and (len(voiced) - start) * HOP_S >= SILENCE_S:
        sil.append([int(start * HOP_S * 1000), int(len(voiced) * HOP_S * 1000)])
    return _Frames(rms_db, voiced, f0, sil)


def _pitch_range_st(f0: np.ndarray) -> float:
    v = f0[~np.isnan(f0)]
    if v.size <= 10:
        return 0.0
    st = 12 * np.log2(v / 100.0)
    return float(np.percentile(st, 95) - np.percentile(st, 5))


def _loudness_range_db(rms_db: np.ndarray, voiced: np.ndarray) -> float:
    loud = rms_db[voiced]
    return float(np.percentile(loud, 95) - np.percentile(loud, 10)) if loud.size > 10 else 0.0


def features(path: str) -> dict:
    x, sr = _read(path)
    a = _analyze(x, sr)
    if a is None:
        return {"loudness_range_db": 0.0, "pitch_range_st": 0.0, "silences_ms": [], "voiced_ratio": 0.0}
    return {"loudness_range_db": round(_loudness_range_db(a.rms_db, a.voiced), 2), "pitch_range_st": round(_pitch_range_st(a.f0), 2),
            "silences_ms": a.silences_ms, "voiced_ratio": round(float(a.voiced.mean()), 3)}


def profile(path: str) -> dict:
    """声音测量（参考，不计分）：整段与逐分钟的音高、音量起伏，停顿与连续说话。"""
    x, sr = _read(path)
    a = _analyze(x, sr)
    if a is None:
        return {}
    per_min = int(60 / HOP_S)
    minutes = []
    for m in range(0, len(a.rms_db), per_min):
        s = slice(m, m + per_min)
        sil = [b - c for c, b in a.silences_ms if m * 10 <= c < (m + per_min) * 10]
        minutes.append({"minute": m // per_min + 1, "pitch_range_st": round(_pitch_range_st(a.f0[s]), 1),
                        "loudness_range_db": round(_loudness_range_db(a.rms_db[s], a.voiced[s]), 1),
                        "pauses": len(sil), "seconds": round(len(a.rms_db[s]) * HOP_S)})
    f0 = a.f0[~np.isnan(a.f0)]
    pauses = np.array([(b - c) / 1000 for c, b in a.silences_ms])
    total_s = len(a.rms_db) * HOP_S
    bounds = [0.0] + [v / 1000 for pair in a.silences_ms for v in pair] + [total_s]
    runs = np.array([bounds[i + 1] - bounds[i] for i in range(0, len(bounds) - 1, 2)])
    runs = runs[runs > 0]
    return {
        "duration_s": round(total_s, 1),
        "pitch_median_hz": round(float(np.median(f0)), 0) if f0.size else None,
        "pitch_range_st": round(_pitch_range_st(a.f0), 1),
        "pitch_near_ceiling_ratio": round(float((f0 >= F0_MAX * 0.97).mean()), 3) if f0.size else None,  # 高说明上限仍可能截断
        "loudness_range_db": round(_loudness_range_db(a.rms_db, a.voiced), 1),
        "voiced_ratio": round(float(a.voiced.mean()), 3),
        "pauses": {"count": int(len(pauses)), "per_minute": round(len(pauses) / max(total_s / 60, 1e-9), 1),
                   "ge_0_6s": int((pauses >= 0.6).sum()), "ge_1s": int((pauses >= 1).sum()),
                   "longest_s": round(float(pauses.max()), 1) if pauses.size else 0.0},
        "speech_runs": {"median_s": round(float(np.median(runs)), 1) if runs.size else 0.0, "gt_10s": int((runs > 10).sum()),
                        "gt_30s": int((runs > 30).sum()), "longest_s": round(float(runs.max()), 1) if runs.size else 0.0},
        "per_minute": minutes,
        "method": f"音高：自相关法 {F0_MIN:g}–{F0_MAX:g} Hz；静音：音量低于整段 95 分位 30 dB 且持续 ≥ {SILENCE_S:g} 秒",
    }
