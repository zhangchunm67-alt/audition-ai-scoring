"""离线盲打分：不经数据库和上传流程，直接对一条视频跑检测器和计分引擎，输出逐条目得分、证据和逐字稿。

用于金标准到位之前，先用真实录像检验整条流水线和所选模型（本地千问、外部判定回放等）。
与正式流水线的区别：
- 只跑一轮（不做临界三轮），不出结论标签，不写数据库；
- 缺少输入或能力的条目标为“未评”并写明原因（例如没有标注观众异议 → S3、O4 未评；没有朗读段 → P3 未评），
  不会当作 0 分或满分；有条目未评时维度和总档位不出分。
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scoring import RubricConfig, ScoringContext, score_round
from scoring.engine import EvidenceError, ScoringInputError

from ..providers.base import Frame, Providers, SegmentHint, Word
from . import acoustic, prompts
from .detector_config import DetectorConfig
from .detectors import DETECTORS
from .detectors.common import Ctx
from .media import Prepared
from .text import SegmentText


class SpecError(ValueError):
    pass


def parse_time(v: Any) -> int:
    """'mm:ss'、'hh:mm:ss'（可带小数秒）或毫秒整数 → 毫秒。"""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return int(v)
    m = re.fullmatch(r"(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)", str(v).strip())
    if not m:
        raise SpecError(f"时间格式不对：{v!r}（用 mm:ss 或 hh:mm:ss）")
    h, mi, s = int(m.group(1) or 0), int(m.group(2)), float(m.group(3))
    return int(round((h * 3600 + mi * 60 + s) * 1000))


@dataclass
class VideoSpec:
    name: str
    video: Path
    main_start_ms: int | None
    main_end_ms: int | None
    reading: dict | None = None  # {start_ms, end_ms, text}
    objections: list[dict] = field(default_factory=list)  # [{objection_id, text, at_ms（相对主体段）, answer_points}]
    props_available: bool = False
    audience: str = "new_trial"
    card: dict = field(default_factory=dict)


def load_spec(path: str | Path) -> VideoSpec:
    p = Path(path)
    d = json.loads(p.read_text("utf-8"))
    base = p.parent

    def rel(x: str) -> Path:
        q = Path(x)
        return q if q.is_absolute() else base / q

    if "video" not in d:
        raise SpecError(f"{p}: 缺少 video")
    main = d.get("main") or {}
    reading = None
    if d.get("reading"):
        r = d["reading"]
        if not r.get("text"):
            raise SpecError(f"{p}: 朗读段须给出朗读稿原文 text（普通话评测要参考文本）")
        reading = {"start_ms": parse_time(r["start"]), "end_ms": parse_time(r["end"]), "text": r["text"]}
    objs = [{"objection_id": o.get("id") or f"o{i + 1}", "text": o["text"], "at_ms": parse_time(o["at"]),
             "answer_points": o.get("answer_points", [])} for i, o in enumerate(d.get("objections", []))]
    card = d.get("card") or {}
    if isinstance(card, str):
        card = json.loads(rel(card).read_text("utf-8"))
    return VideoSpec(
        name=d.get("name") or p.stem, video=rel(d["video"]),
        main_start_ms=parse_time(main["start"]) if "start" in main else None,
        main_end_ms=parse_time(main["end"]) if "end" in main else None,
        reading=reading, objections=objs, props_available=bool(d.get("props_available", False)),
        audience=d.get("audience", "new_trial"), card=card,
    )


def _run(*args: str) -> str:
    r = subprocess.run(list(args), capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{args[0]} 失败：{r.stderr.strip()[:300]}")
    return r.stdout


def duration_ms(video: Path) -> int:
    out = _run("ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video))
    return int(float(out.strip()) * 1000)


def _wav(video: Path, a: int, b: int, out: Path) -> str:
    _run("ffmpeg", "-v", "error", "-y", "-ss", f"{a / 1000:.3f}", "-to", f"{b / 1000:.3f}", "-i", str(video),
         "-vn", "-ac", "1", "-ar", "16000", str(out))
    return str(out)


def _frames(video: Path, a: int, b: int, every_s: float, out: Path) -> list[Frame]:
    out.mkdir(parents=True, exist_ok=True)
    _run("ffmpeg", "-v", "error", "-y", "-ss", f"{a / 1000:.3f}", "-to", f"{b / 1000:.3f}", "-i", str(video),
         "-vf", f"fps=1/{every_s:g},scale=640:-2", "-q:v", "4", str(out / "%06d.jpg"))
    return [Frame(str(f), a + int(i * every_s * 1000)) for i, f in enumerate(sorted(out.glob("*.jpg")))]


SKIP = {
    "S3": lambda s, n: None if len(s.objections) == n else (
        f"标注了 {len(s.objections)} 条观众异议，评分表要求 {n} 条（每条 5 分），解答异议不按比例折算" if s.objections
        else "录像没有标注观众异议（时间和原文），无法评解答异议"),
    "O4": lambda s, n: None if s.objections else "录像没有标注观众异议，无法评节奏掌控（讲品还是回答问题）",
    "P3": lambda s, n: None if s.reading else "录像没有朗读段，无法做带参考文本的普通话评测",
}


def run_video(spec: VideoSpec, providers: Providers, cfg: RubricConfig, dcfg: DetectorConfig, workdir: Path) -> dict:
    """处理一条视频，返回可直接写成 JSON 的结果。"""
    workdir.mkdir(parents=True, exist_ok=True)
    total = duration_ms(spec.video)
    m0 = spec.main_start_ms or 0
    m1 = spec.main_end_ms or min(total, m0 + 600_000)
    if not 0 <= m0 < m1 <= total:
        raise SpecError(f"{spec.name}: 主体段 {m0}–{m1} 毫秒不在视频时长 {total} 毫秒内")
    segments = [{"segment": "main", "start_ms": m0, "end_ms": m1}]
    audio = {"main": _wav(spec.video, m0, m1, workdir / "main.wav")}
    offsets = {"main": m0}
    if spec.reading:
        r = spec.reading
        segments.append({"segment": "reading", "start_ms": r["start_ms"], "end_ms": r["end_ms"]})
        audio["reading"] = _wav(spec.video, r["start_ms"], r["end_ms"], workdir / "reading.wav")
        offsets["reading"] = r["start_ms"]
    for o in spec.objections:
        if not 0 < o["at_ms"] < m1 - m0:
            raise SpecError(f"{spec.name}: 异议 {o['objection_id']} 的时间须在主体段内（相对主体段起点）")
        o["video_ms"] = m0 + o["at_ms"]
    media = Prepared(audio, offsets, _frames(spec.video, m0, m1, dcfg.frames.appearance_every_s, workdir / "frames-appearance"),
                     _frames(spec.video, m0, m1, 1 / dcfg.frames.motion_fps, workdir / "frames-motion"))

    texts: dict[str, SegmentText] = {}
    asr_info: dict[str, Any] = {}
    for s in segments:
        name = s["segment"]
        tr = providers.asr.transcribe(audio[name], disfluency_removal=False, word_timestamps=True,
                                      hint=SegmentHint(name, reading_text=spec.reading["text"] if name == "reading" else None,
                                                       objection_offsets_ms=[o["at_ms"] for o in spec.objections] if name == "main" else [],
                                                       objection_texts=[o["text"] for o in spec.objections] if name == "main" else []))
        if tr.params.get("disfluency_removal") is not False:
            raise RuntimeError("语音识别没有确认关闭顺滑，拒绝使用该转写")
        texts[name] = SegmentText(name, [Word(w.text, w.start_ms + s["start_ms"], w.end_ms + s["start_ms"], w.confidence) for w in tr.words])
        asr_info[name] = {"provider": tr.provider, "model_version": tr.model_version, "params": tr.params}
    feats = acoustic.features(audio["main"])
    feats["silences_ms"] = [[a + m0, b + m0] for a, b in feats["silences_ms"]]

    ctx = Ctx(round_no=1, props_available=spec.props_available, segments=segments, objections=spec.objections, questions=[],
              reading_text=spec.reading["text"] if spec.reading else "", card=spec.card, lexicon={}, cfg=dcfg, texts=texts,
              acoustic={"main": feats}, media=media, providers=providers)
    evidence, completed, detectors = [], set(), {}
    for _, it in cfg.items():
        if it.applicable_if == "props_available" and not spec.props_available:
            detectors[it.id] = {"status": "not_applicable", "reason": "画面里没有贴片或 KT 板"}
            continue
        reason = SKIP.get(it.id, lambda s, n: None)(spec, getattr(it, "count", 0))
        if reason is None and it.id not in DETECTORS:
            reason = "没有检测器"
        if reason:
            detectors[it.id] = {"status": "skipped", "reason": reason}
            continue
        try:
            evs = DETECTORS[it.id](ctx)
        except Exception as exc:  # noqa: BLE001  检测失败 → 未评，不当作 0 次
            detectors[it.id] = {"status": "failed", "reason": f"{type(exc).__name__}: {exc}"[:500]}
            continue
        detectors[it.id] = {"status": "completed", "evidence": len(evs)}
        evidence.extend(evs)
        completed.add(it.id)

    manifest = {**providers.manifest(), "prompts": prompts.prompt_set_hash(), "detector_config": dcfg.version, "mode": "offline-blind"}
    sctx = ScoringContext(props_available=spec.props_available, audience=spec.audience, completed_detectors=completed,
                          expected_questions={"S3": [o["objection_id"] for o in spec.objections]} if "S3" in completed else {},
                          main_duration_ms=m1 - m0, model_manifest=manifest)
    try:
        result = score_round(evidence, cfg, sctx).model_dump(mode="json")
    except (EvidenceError, ScoringInputError) as exc:  # 检测器产出或输入与配置不符：原样报告
        result = {"error": f"证据或输入与评分配置不符：{exc}"}
    return {
        "name": spec.name, "video": str(spec.video), "duration_ms": total, "segments": segments,
        "objections": spec.objections, "props_available": spec.props_available, "audience": spec.audience,
        "rubric_version": cfg.version, "asr": asr_info, "acoustic": {k: v for k, v in feats.items() if k != "silences_ms"},
        "transcript": {k: v.text for k, v in texts.items()},
        "words": {k: [[w.text, w.start_ms, w.end_ms, w.confidence] for w in v.words] for k, v in texts.items()},
        "detectors": detectors, "evidence": [e.model_dump(mode="json") for e in evidence], "result": result,
    }


def _clock(ms: int | None) -> str:
    if ms is None:
        return "—"
    s = ms // 1000
    return f"{s // 3600:d}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def report_md(out: dict) -> str:
    """一条视频的盲打分报告（Markdown）。"""
    res = out["result"]
    lines = [f"# 盲打分：{out['name']}", "",
             f"- 视频：`{Path(out['video']).name}`，时长 {_clock(out['duration_ms'])}；主体段 "
             f"{_clock(out['segments'][0]['start_ms'])}–{_clock(out['segments'][0]['end_ms'])}",
             f"- 评分标准：{out['rubric_version']}；单轮离线打分，不出结论标签；未评条目不当 0 分",
             f"- 模型：{', '.join(f'{k}={v}' for k, v in res.get('model_manifest', {}).items() if k in ('asr', 'llm', 'vision', 'voice', 'laugh', 'speech_eval'))}",
             ""]
    if "error" in res:
        return "\n".join(lines + [f"**计分失败**：{res['error']}"])
    lines += ["## 维度", "", "| 维度 | 状态 | 得分（折算到 100） | 档位 |", "|---|---|---|---|"]
    for d in res["dimensions"]:
        lines.append(f"| {d['name']} | {'已评' if d['status'] == 'scored' else '不完整'} | {d['score'] if d['score'] is not None else '—'} | {d['grade'] or '—'} |")
    lines += ["", f"总档位：{res['total_grade'] if res['total_grade'] is not None else '不完整，未出'}", "",
              "## 条目", "", "| 条目 | 满分 | 得分 | 说明 |", "|---|---|---|---|"]
    for it in res["items"]:
        det = out["detectors"].get(it["item_id"], {})
        if it["status"] == "scored":
            note = "；".join(it["notes"])[:120]
            if it["low_confidence"]:
                note = ("低置信：" + "；".join(it["low_confidence_reasons"])[:80] + "；" + note).rstrip("；")
            score = f"{it['score']:g}"
        elif it["status"] == "not_applicable":
            score, note = "不适用", "；".join(it["notes"])
        else:
            score, note = "**未评**", det.get("reason") or "；".join(it["missing_reasons"])
        lines.append(f"| {it['item_id']} {it['name']} | {it['max']} | {score} | {note.replace('|', '/')} |")
    lines += ["", "## 证据", ""]
    for e in sorted(out["evidence"], key=lambda e: (e["item_id"], e["start_ms"] or 0)):
        j = e["judgment"]
        q = (e.get("quote") or "")[:60].replace("\n", " ")
        quote = f"：“{q}”" if q else ""
        reason = f"（{e['reason'][:100]}）" if e.get("reason") else ""
        lines.append(f"- {e['item_id']} {_clock(e['start_ms'])} [{e.get('label') or e.get('ref') or e['kind']}] 判定 {j}{quote}{reason}")
    lines += ["", "## 主体段逐字稿", "", out["transcript"].get("main", "")]
    return "\n".join(lines) + "\n"


# ───────────── 与金标准对比（金标准到位后用） ─────────────


def compare_with_gold(results: list[dict], gold: dict[str, dict[str, float]], cfg: RubricConfig) -> dict:
    """results：各视频的离线结果；gold：{视频名: {条目: 人工分}}。
    条目一致 = 相差不超过该条目满分的 10%（I28）；维度一致 = 档位相差 ≤ 1（C34）。AI 未评的条目单独计数，不算一致。"""
    from fractions import Fraction

    from scoring.aggregate import aggregate_item_scores

    items = {it.id: (d, it) for d, it in cfg.items()}
    rows, per_item, dims = [], {i: {"agree": 0, "n": 0, "ai_missing": 0, "abs_err": 0.0} for i in items}, []
    for out in results:
        g = gold.get(out["name"])
        if g is None:
            continue
        ai = {it["item_id"]: it for it in out["result"].get("items", [])}
        for iid, gv in g.items():
            if iid not in items:
                raise ValueError(f"金标准里的条目 {iid} 不在评分标准 {cfg.version} 中")
            mx = items[iid][1].max
            a = ai.get(iid, {})
            st = per_item[iid]
            if a.get("status") == "not_applicable":
                continue
            st["n"] += 1
            if a.get("score") is None:
                st["ai_missing"] += 1
                rows.append({"video": out["name"], "item": iid, "max": mx, "gold": gv, "ai": None, "diff": None, "agree": False})
                continue
            diff = a["score"] - gv
            ok = abs(Fraction(str(diff))) <= Fraction(mx, 10)
            st["agree"] += ok
            st["abs_err"] += abs(diff)
            rows.append({"video": out["name"], "item": iid, "max": mx, "gold": gv, "ai": a["score"], "diff": diff, "agree": ok})
        agg = aggregate_item_scores(cfg, g, props_available=out["props_available"], audience=out["audience"])
        ai_dims = {d["id"]: d for d in out["result"].get("dimensions", [])}
        for d in agg.dimensions:
            a = ai_dims.get(d.id, {})
            if d.grade is None:
                continue
            dims.append({"video": out["name"], "dimension": d.id, "gold_grade": d.grade, "ai_grade": a.get("grade"),
                         "agree": a.get("grade") is not None and abs(a["grade"] - d.grade) <= 1})
    summary = {iid: {**st, "agree_rate": round(st["agree"] / st["n"], 3) if st["n"] else None,
                     "mae": round(st["abs_err"] / (st["n"] - st["ai_missing"]), 2) if st["n"] > st["ai_missing"] else None}
               for iid, st in per_item.items() if st["n"]}
    return {"rows": rows, "items": summary, "dimensions": dims,
            "dimension_agree_rate": round(sum(d["agree"] for d in dims) / len(dims), 3) if dims else None}
