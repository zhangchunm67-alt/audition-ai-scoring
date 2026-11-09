"""人设塑造 P1–P10（评分表 20261105“人设塑造”）。"""
from __future__ import annotations

import math
import re

from ..text import char_count, sentences
from .common import Ctx, binary, check_level, main_sentences

TEN_MIN = 600_000


def p1(ctx: Ctx):
    """形象：每 30 秒 1 帧，多模态模型只判穿着、发型是否不符合要求（评分表：不符合直接扣 10 分）。不判相貌（Q5）。"""
    found = ctx.providers.vision.analyze("attire", ctx.media.appearance_frames, {})
    out = []
    for f in found:
        if f.label not in ("attire", "hairstyle"):
            raise ValueError(f"P1: 视觉结果的类别 {f.label!r} 不是穿着或发型")
        out.append(ctx.ev("P1", "occurrence", label=f.label, judgment=f.judgment, confidence=f.confidence, source="vision",
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
    """普通话：朗读段带参考文本的语音评测（C15）。评分表“方言一处扣1分”：方言处记一次；发音不准留作证据、不扣分（P-P3-PRON）。"""
    seg = ctx.seg("reading")
    r = ctx.providers.speech_eval.assess(ctx.media.audio["reading"], ctx.reading_text)
    errors = r.details.get("errors")
    if errors is None:
        raise ValueError("P3: 语音评测没有返回逐处问题，无法按方言计次")
    out = []
    for e in errors:
        if e["type"] not in ("dialect", "mispronounce"):
            raise ValueError(f"P3: 未知的评测问题类型 {e['type']!r}")
        a, b = seg["start_ms"] + e["start_ms"], seg["start_ms"] + e["end_ms"]
        out.append(ctx.ev("P3", "occurrence", label=e["type"], judgment=binary(e["type"] == "dialect"), start=a, end=b,
                          quote=e.get("text"), confidence=e.get("confidence", 0.8), source="audio", segment="reading",
                          reason="方言" if e["type"] == "dialect" else "发音不准（不扣分，待确认 P-P3-PRON）"))
    return out


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


def _voice(ctx: Ctx, item: str, aspect: str, criterion: str, max_score: int, context: dict, reason_extra: str = ""):
    """评分表“根据主观打分”的声音条目：声音评价模型直接给 0–满分的整数分（须校准，CAL-SUBJECTIVE）。"""
    seg = ctx.seg("main")
    r = ctx.providers.voice.rate(ctx.media.audio["main"], aspect, criterion=criterion, max_score=max_score, context=context)
    level = check_level(item, r.score, max_score)
    return [ctx.ev(item, "level", judgment=level, confidence=r.confidence, source="audio", start=seg["start_ms"], end=seg["end_ms"],
                   reason=r.reason + reason_extra)]


def p5(ctx: Ctx):
    f = ctx.acoustic["main"]
    return _voice(ctx, "P5", "intonation", "语调（抑扬顿挫-根据主观打分）", 5,
                  {"pitch_range_st": f["pitch_range_st"], "loudness_range_db": f["loudness_range_db"]})


def p6(ctx: Ctx):
    f = ctx.acoustic["main"]
    return _voice(ctx, "P6", "timbre", "音色-根据主观打分", 5,
                  {"pitch_range_st": f["pitch_range_st"], "loudness_range_db": f["loudness_range_db"]})


def pause_events(ctx: Ctx) -> dict[str, list[tuple[int, int, str]]]:
    """停顿相关的参考测量：停顿 = 静音 ≥ 0.3 秒；连讲 = 连续 30 秒没有停顿；卡壳 = 句中静音 ≥ 3 秒（弹幕弹出后 5 秒内不算），或重复、自我纠正。"""
    c = ctx.cfg.p7
    words = [w for w in ctx.main.words if w.text.strip()]
    pops = [o["video_ms"] for o in ctx.objections]
    ev = {"pause": [], "run_on": [], "stall": []}
    run_start = words[0].start_ms if words else 0
    for prev, cur in zip(words, words[1:]):
        gap = cur.start_ms - prev.end_ms
        if gap >= c.pause_ms:
            ev["pause"].append((prev.end_ms, cur.start_ms, "停顿"))
            run_start = cur.start_ms
        elif cur.end_ms - run_start >= c.run_on_ms:
            ev["run_on"].append((run_start, cur.end_ms, "连续 30 秒没有停顿"))
            run_start = cur.end_ms
        if gap >= c.stall_gap_ms and prev.text not in "。！？；" and not any(p <= prev.end_ms <= p + c.objection_grace_ms for p in pops):
            ev["stall"].append((prev.end_ms, cur.start_ms, f"句中静音 {gap / 1000:.1f} 秒"))
    for s in main_sentences(ctx):
        for pat in c.repetition_patterns:
            for m in re.finditer(pat, s.text):
                a, b = ctx.main.span(s.char_start + m.start(), s.char_start + m.end())
                ev["stall"].append((a, b, f"重复或自我纠正：{m.group(0)}"))
    return ev


def p7(ctx: Ctx):
    """节奏（是否有停顿）：评分表“根据主观打分”。测得的停顿、连讲、卡壳次数作为参考输入交给声音评价模型，不再按次数分档。"""
    ev = pause_events(ctx)
    n = {k: len(v) for k, v in ev.items()}
    return _voice(ctx, "P7", "rhythm", "节奏（是否有停顿）-根据主观打分", 10,
                  {"pause_count": n["pause"], "run_on_count": n["run_on"], "stall_count": n["stall"]},
                  f"（参考：停顿 {n['pause']} 次、连讲 {n['run_on']} 次、卡壳 {n['stall']} 次）")


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


PROP_LABELS = {"sticker": "贴片", "kt_board": "KT 板"}


def p9_frames(ctx: Ctx) -> tuple[list, list[int]]:
    """要看的帧：主体段每 scan_every_s 秒一帧，加上口播引导语（看这里、看屏幕……）前后 3 秒的帧。"""
    c = ctx.cfg.p9
    main = ctx.seg("main")
    step = int(c.scan_every_s * 1000)
    guides = []
    for s in main_sentences(ctx):
        for ph in c.guide_phrases:
            i = s.text.find(ph)
            if i >= 0:
                guides.append(ctx.main.span(s.char_start + i, s.char_start + i + len(ph))[0])
                break
    frames = [f for f in ctx.media.motion_frames
              if (f.at_ms - main["start_ms"]) % step < 1000 or any(abs(f.at_ms - t) <= 3000 for t in guides)]
    return frames, sorted(guides)


def p9(ctx: Ctx):
    """道具使用（评分表：对贴片正确使用 1 次得 2 分，对 KT 板正确使用 1 次得 1 分）。
    v2：直接看画面找“举起 KT 板讲解”“指向屏幕上的贴片”，不再只靠口播引导语（原做法把不出声的举牌、指屏全部漏掉）。
    相邻命中帧（同一类、同一块内容，间隔不超过 episode_gap_ms）合成一次使用；同一块内容 1 分钟内重复使用只算 1 次，
    重复的仍留证据（not_count）便于复核。画面里没有道具时不检测（C26）。"""
    c = ctx.cfg.p9
    frames, guides = p9_frames(ctx)
    found = ctx.providers.vision.analyze("prop_pointing", frames, {"guide_ms": guides}) if frames else []
    hits = sorted((f for f in found if f.judgment == "count"), key=lambda f: f.at_ms)
    episodes: list[dict] = []
    for f in hits:
        if f.label not in PROP_LABELS:
            continue
        key = (f.label, (f.detail or "").strip())
        last = next((e for e in reversed(episodes) if e["key"] == key), None)
        if last and f.at_ms - last["end"] <= c.episode_gap_ms:
            last["end"], last["conf"] = max(last["end"], f.end_ms), min(last["conf"], f.confidence)
            continue
        episodes.append({"key": key, "start": f.at_ms, "end": f.end_ms, "conf": f.confidence, "reason": f.reason})
    out, counted_at = [], {}
    for e in episodes:
        label, detail = e["key"]
        prev = counted_at.get(e["key"])
        repeat = prev is not None and e["start"] - prev < c.dedupe_within_ms
        if not repeat:
            counted_at[e["key"]] = e["start"]
        what = f"{PROP_LABELS[label]}“{detail}”" if detail else PROP_LABELS[label]
        reason = f"{what}：{e['reason']}" + ("；1 分钟内重复使用同一块内容，不重复计分" if repeat else "")
        out.append(ctx.ev("P9", "instance", label=label, judgment="not_count" if repeat else "count", start=e["start"], end=e["end"],
                          confidence=e["conf"], source="vision", reason=reason))
    return out


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
