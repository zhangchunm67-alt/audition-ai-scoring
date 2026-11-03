"""本地声学特征（不调用外部服务）：音量起伏、音高起伏、长静音。用于 P5、O4 和冷场判断。"""
from __future__ import annotations

import wave

import numpy as np

HOP_S, WIN_S = 0.01, 0.03


def _read(path: str) -> tuple[np.ndarray, int]:
    with wave.open(path, "rb") as w:
        sr, n = w.getframerate(), w.getnframes()
        x = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
    return x, sr


def features(path: str) -> dict:
    x, sr = _read(path)
    hop, win = int(sr * HOP_S), int(sr * WIN_S)
    if len(x) < win * 2:
        return {"loudness_range_db": 0.0, "pitch_range_st": 0.0, "silences_ms": [], "voiced_ratio": 0.0}
    frames = np.lib.stride_tricks.sliding_window_view(x, win)[::hop]
    rms_db = 20 * np.log10(np.sqrt((frames**2).mean(axis=1)) + 1e-9)
    thr = max(-50.0, float(np.percentile(rms_db, 95)) - 30.0)
    voiced = rms_db > thr
    loud = rms_db[voiced]
    loudness_range = float(np.percentile(loud, 95) - np.percentile(loud, 10)) if loud.size > 10 else 0.0
    # 音高：自相关法，75–400 Hz
    lo, hi = int(sr / 400), int(sr / 75)
    f0 = []
    for fr, v in zip(frames[:: 3], voiced[:: 3]):
        if not v:
            continue
        fr = fr - fr.mean()
        ac = np.correlate(fr, fr, mode="full")[win - 1:]
        if ac[0] <= 0 or hi >= len(ac):
            continue
        lag = lo + int(np.argmax(ac[lo:hi]))
        if ac[lag] / ac[0] > 0.5:
            f0.append(sr / lag)
    st = 12 * np.log2(np.array(f0) / 100.0) if len(f0) > 10 else np.array([])
    pitch_range = float(np.percentile(st, 95) - np.percentile(st, 5)) if st.size else 0.0
    # 静音段（≥ 0.3 秒），相对本段起点
    sil, start = [], None
    for i, v in enumerate(voiced):
        if not v and start is None:
            start = i
        elif v and start is not None:
            if (i - start) * HOP_S >= 0.3:
                sil.append([int(start * HOP_S * 1000), int(i * HOP_S * 1000)])
            start = None
    if start is not None and (len(voiced) - start) * HOP_S >= 0.3:
        sil.append([int(start * HOP_S * 1000), int(len(voiced) * HOP_S * 1000)])
    return {"loudness_range_db": round(loudness_range, 2), "pitch_range_st": round(pitch_range, 2), "silences_ms": sil,
            "voiced_ratio": round(float(voiced.mean()), 3)}
