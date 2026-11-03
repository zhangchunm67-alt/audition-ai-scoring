"""人设塑造 P1–P10（rubric 第 4 节；P6 音色已删除）。"""
from __future__ import annotations

import math
import re

from ..text import char_count, sentences
from .common import Ctx, binary, main_sentences

TEN_MIN = 600_000


def p1(ctx: Ctx):
    """形象：每 30 秒 1 帧，多模态模型给建议等级（不判相貌本身）。"""
    found = ctx.providers.vision.analyze("appearance", ctx.media.appearance_frames, {})
    out = []
    for f in found[:1]:
        out.append(ctx.ev("P1", "level", judgment=int(f.judgment), confidence=f.confidence, source="vision",
                          start=f.at_ms, end=f.end_ms, reason=f.reason))
    return out


def p2(ctx: Ctx):
    """语言干净：词表召回候选 → 大模型逐个判断“删掉后意思是否不变”。统计窗口为主体段 10 分钟。"""
    main = ctx.seg("main")
    window = ctx.main.window(main["start_ms"], main["start_ms"] + TEN_MIN)
    cands = []
    for s in sentences(window):
        for cat in ctx.cfg.p2.categories:
            for m in re.finditer(cat.pattern, s.text):
                cands.append({"id": str(len(cands)), "sentence": s.text, "word": m.group(0), "category": cat.label,
                              "context": s.text, "_pos": (s.char_start + m.start(), s.char_start + m.end())})
    out = []
    for i in range(0, len(cands), 50):
        batch = cands[i: i + 50]
        res = ctx.ask("p2_filler", {"candidates": [{k: v for k, v in c.items() if not k.startswith("_")} for c in batch]})
        by_id = {r["id"]: r for r in res["items"]}
        for c in batch:
            r = by_id.get(c["id"])
            if r is None:
                raise ValueError(f"大模型漏判了 P2 候选 {c['id']}")
            a, b = window.span(*c["_pos"])
            conf = min(r["confidence"], window.min_confidence(*c["_pos"]))
            out.append(ctx.ev("P2", "occurrence", start=a, end=b, quote=c["sentence"], label=c["category"],
                              judgment=binary(r["count"]), reason=r["reason"], confidence=conf, source="llm"))
    return out


def p3(ctx: Ctx):
    """普通话：朗读段带参考文本的语音评测（C15）。"""
    seg = ctx.seg("reading")
    r = ctx.providers.speech_eval.assess(ctx.media.audio["reading"], ctx.reading_text)
    return [ctx.ev("P3", "metric", label="reading_eval_score", value=float(r.score), confidence=0.9, source="audio",
                   start=seg["start_ms"], end=seg["end_ms"], segment="reading", reason="朗读段语音评测分")]


def p4(ctx: Ctx):
    """语速：主体段按自然分钟切段，每段字数（数字按读出的字数计）。最后不满一分钟的一段按实际字数计。"""
    main = ctx.seg("main")
    dur = main["end_ms"] - main["start_ms"]
    out = []
    for m in range(max(1, math.ceil(dur / 60_000))):
        a = main["start_ms"] + m * 60_000
        b = min(main["end_ms"], a + 60_000)
        w = ctx.main.window(a, b)
        conf = sum(x.confidence for x in w.words) / len(w.words) if w.words else 1.0
        out.append(ctx.ev("P4", "metric", label="chars_per_min", value=float(char_count(w.text)), start=a, end=b,
                          confidence=conf, source="rule", reason=f"第 {m + 1} 分钟"))
    return out


def p5(ctx: Ctx):
    f = ctx.acoustic["main"]
    seg = ctx.seg("main")
    return [ctx.ev("P5", "metric", label=k, value=float(f[k]), confidence=0.8, source="audio", start=seg["start_ms"], end=seg["end_ms"])
            for k in ("pitch_range_st", "loudness_range_db")]


def p7(ctx: Ctx):
    """节奏：停顿 = 静音 ≥ 0.3 秒；连讲 = 连续 30 秒没有停顿；卡壳 = 句中静音 ≥ 3 秒（弹幕弹出后 5 秒内不算），或重复、自我纠正。"""
    c = ctx.cfg.p7
    words = [w for w in ctx.main.words if w.text.strip()]
    pops = [o["video_ms"] for o in ctx.objections]
    out = []
    run_start = words[0].start_ms if words else 0
    for prev, cur in zip(words, words[1:]):
        gap = cur.start_ms - prev.end_ms
        if gap >= c.pause_ms:
            run_start = cur.start_ms
        elif cur.end_ms - run_start >= c.run_on_ms:
            out.append(ctx.ev("P7", "occurrence", label="run_on", judgment="count", start=run_start, end=cur.end_ms,
                              confidence=0.85, source="rule", reason="连续 30 秒没有停顿"))
            run_start = cur.end_ms
        if gap >= c.stall_gap_ms and prev.text not in "。！？；" and not any(p <= prev.end_ms <= p + c.objection_grace_ms for p in pops):
            out.append(ctx.ev("P7", "occurrence", label="stall", judgment="count", start=prev.end_ms, end=cur.start_ms,
                              confidence=0.8, source="rule", reason=f"句中静音 {gap / 1000:.1f} 秒"))
    for s in main_sentences(ctx):
        for pat in c.repetition_patterns:
            for m in re.finditer(pat, s.text):
                a, b = ctx.main.span(s.char_start + m.start(), s.char_start + m.end())
                out.append(ctx.ev("P7", "occurrence", label="stall", judgment="count", start=a, end=b, quote=s.text,
                                  confidence=0.75, source="rule", reason=f"重复或自我纠正：{m.group(0)}"))
    return out


def p8(ctx: Ctx):
    """小动作：每秒 1 帧，多模态模型找候选；同一动作 5 秒内重复算 1 次。"""
    found = sorted(ctx.providers.vision.analyze("fidget", ctx.media.motion_frames, {}), key=lambda f: f.at_ms)
    out, last = [], {}
    for f in found:
        if f.label in last and f.at_ms - last[f.label] <= ctx.cfg.p8.merge_within_ms:
            last[f.label] = f.at_ms
            continue
        last[f.label] = f.at_ms
        out.append(ctx.ev("P8", "occurrence", label=f.label, judgment=f.judgment, start=f.at_ms, end=f.end_ms,
                          confidence=f.confidence, source="vision", reason=f.reason))
    return out


def p9(ctx: Ctx):
    """道具使用：转写里找引导语，抽帧判断是否指向道具；同一块内容 1 分钟内重复指只算 1 次。画面里没有道具时不检测（C26）。"""
    guides = []
    for s in main_sentences(ctx):
        for ph in ctx.cfg.p9.guide_phrases:
            i = s.text.find(ph)
            if i >= 0:
                guides.append(ctx.main.span(s.char_start + i, s.char_start + i + len(ph))[0])
                break
    kept = []
    for t in sorted(guides):
        if not kept or t - kept[-1] > ctx.cfg.p9.dedupe_within_ms:
            kept.append(t)
    near = [f for f in ctx.media.motion_frames if any(abs(f.at_ms - t) <= 3000 for t in kept)]
    found = ctx.providers.vision.analyze("prop_pointing", near, {"guide_ms": kept}) if kept else []
    return [ctx.ev("P9", "instance", label=f.label, judgment=f.judgment, start=f.at_ms, end=f.end_ms, confidence=f.confidence,
                   source="vision", reason=f.reason) for f in found]


def p10(ctx: Ctx):
    """嘻嘻哈哈：音频笑声检测找候选，大模型结合前后文判断是否与内容无关。"""
    base = ctx.seg("main")["start_ms"]
    cands = ctx.providers.laugh.detect(ctx.media.audio["main"])
    if not cands:
        return []
    items = []
    for i, c in enumerate(cands):
        a, b = base + c.start_ms, base + c.end_ms
        context = ctx.main.window(a - 8000, b + 8000).text
        items.append({"id": str(i), "context": context, "_t": (a, b, c.confidence)})
    res = {r["id"]: r for r in ctx.ask("p10_laugh", {"candidates": [{"id": x["id"], "context": x["context"]} for x in items]})["items"]}
    return [ctx.ev("P10", "occurrence", label="laugh", judgment=binary(res[x["id"]]["count"]), start=x["_t"][0], end=x["_t"][1],
                   quote=x["context"], confidence=min(x["_t"][2], res[x["id"]]["confidence"]), source="audio", reason=res[x["id"]]["reason"])
            for x in items]
