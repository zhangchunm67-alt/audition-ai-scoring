"""表达逻辑 L1–L5、其他 O1–O4（评分表 20261105“表达逻辑运用”“其他”）。"""
from __future__ import annotations

from .common import Ctx, binary, check_level
from .sales import answer_window_end, objection_checks


def l1(ctx: Ctx):
    """电梯法则：主体段开头 30 秒。评分表“根据主观评分”，大模型直接给 0–20 分（须校准）。"""
    start = ctx.seg("main")["start_ms"]
    opening = ctx.main.window(start, start + 30_000)
    r = ctx.ask("l1_opening", {"opening": opening.text})
    level = check_level("L1", r["level"], 20)
    if not r["quote"].strip():
        if level:
            raise ValueError("L1: 给分大于 0 却没有引用原文")
        return [ctx.ev("L1", "level", judgment=0, reason=r["reason"], confidence=r["confidence"], source="llm",
                       start=start, end=start + 30_000)]
    return [ctx.quote_ev("L1", "level", r["quote"], st=opening, judgment=level, reason=r["reason"], model_conf=r["confidence"])]


def _same_place(a, b) -> bool:
    """两条证据是否指向原文同一处：时间区间的重叠超过较短一条的一半。"""
    if None in (a.start_ms, a.end_ms, b.start_ms, b.end_ms):
        return False
    overlap = min(a.end_ms, b.end_ms) - max(a.start_ms, b.start_ms)
    return overlap * 2 > min(a.end_ms - a.start_ms, b.end_ms - b.start_ms)


def _founds(ctx: Ctx, task: str, item: str, kind: str, payload: dict | None = None, label=None, judge=None):
    """模型有时把同一句话重复列出（甚至自己注明“与上一条重复”）。同一处、同一标签的只留第一条，否则逐次计的条目会重复扣分或加分。"""
    r = ctx.ask(task, payload or {"transcript": ctx.main.text})
    out = []
    for x in r["items"]:
        e = ctx.quote_ev(item, kind, x["quote"], strict=False, label=label(x) if label else (x.get("label") or None),
                         judgment=judge(x) if judge else binary(x["valid"]), reason=x["reason"], model_conf=x["confidence"])
        if not any(_same_place(e, prev) and e.label == prev.label for prev in out):  # 同一句里讲了两个术语、两个事实的不算重复
            out.append(e)
    return out


def l2(ctx: Ctx):
    return _founds(ctx, "l2_structure", "L2", "instance")


def l3(ctx: Ctx):
    """推理运用：演绎错误记一次（judgment=count）；成立的推论也留证据（not_count），便于追溯和待确认项 Q16。"""
    return _founds(ctx, "l3_deduction", "L3", "occurrence", label=lambda x: "deductive_error" if not x["valid"] else "inference",
                   judge=lambda x: binary(not x["valid"]))


def l4(ctx: Ctx):
    return _founds(ctx, "l4_induction", "L4", "instance")


def l5(ctx: Ctx):
    return _founds(ctx, "l5_facts", "L5", "instance", {"transcript": ctx.main.text, "key_facts": ctx.card.get("key_numbers", [])})


def o1(ctx: Ctx):
    return _founds(ctx, "o1_terms", "O1", "instance", {"transcript": ctx.main.text, "glossary": ctx.card.get("glossary", []), "reference_script": (ctx.card.get("fixed_script") or {}).get("text", "")})


def o2(ctx: Ctx):
    return _founds(ctx, "o2_targeted", "O2", "instance", {"transcript": ctx.main.text, "targeted_points": ctx.card.get("targeted_points", []), "reference_script": (ctx.card.get("fixed_script") or {}).get("text", "")})


def o3(ctx: Ctx):
    return _founds(ctx, "o3_scene", "O3", "instance", {"transcript": ctx.main.text, "scenarios": ctx.card.get("scenarios", [])},
                   label=lambda x: "scene")


def o4(ctx: Ctx):
    """节奏与气氛：评分表“根据主观打分”。测得弹幕到开始回应的时长、未回应条数、冷场次数和音量、音高起伏，
    连同每条异议之后的讲话交给大模型，直接给 0–20 分（须校准）。"""
    main = ctx.seg("main")
    checks = objection_checks(ctx)
    latencies, unanswered, segs = [], 0, []
    for i, (o, r) in enumerate(zip(ctx.objections, checks)):
        nxt = ctx.objections[i + 1]["video_ms"] if i + 1 < len(ctx.objections) else main["end_ms"]
        after = ctx.main.window(o["video_ms"], answer_window_end(ctx, o["video_ms"], nxt))
        first = next((w for w in after.words if w.text.strip()), None)
        if not r["answered"] or first is None:
            unanswered += 1
        else:
            latencies.append((first.start_ms - o["video_ms"]) / 1000)
        segs.append({"objection": o["text"], "text": after.text})
    f = ctx.acoustic["main"]
    measured = {
        "max_response_latency_s": max(latencies) if latencies else None,
        "unanswered_objections": unanswered,
        "dead_air_count": sum(1 for a, b in f["silences_ms"] if b - a >= ctx.cfg.o4.dead_air_ms),
        "loudness_range_db": f["loudness_range_db"],
        "pitch_range_st": f["pitch_range_st"],
    }
    r = ctx.ask("o4_control", {"segments_after_objection": segs, "measured": measured})
    level = check_level("O4", r["level"], 20)
    lat = "无" if measured["max_response_latency_s"] is None else f"{measured['max_response_latency_s']:.1f} 秒"
    reason = (f"{r['reason']}（参考：最长回应 {lat}、未回应 {unanswered} 条、冷场 {measured['dead_air_count']} 次、"
              f"音量起伏 {f['loudness_range_db']:.1f} dB、音高起伏 {f['pitch_range_st']:.1f} 半音）")
    return [ctx.ev("O4", "level", judgment=level, reason=reason, confidence=r["confidence"], source="llm",
                   start=main["start_ms"], end=main["end_ms"])]
