"""表达逻辑 L1–L5、其他 O1–O5（rubric 第 6、7 节）。"""
from __future__ import annotations

from .common import Ctx, binary
from .sales import objection_checks


def l1(ctx: Ctx):
    start = ctx.seg("main")["start_ms"]
    opening = ctx.main.window(start, start + 30_000)
    r = ctx.ask("l1_opening", {"opening": opening.text})
    out = [ctx.quote_ev("L1", "level", r["quote"], st=opening, judgment=r["level"], reason=r["reason"], model_conf=r["confidence"])]
    if r["hook_invalid"]:
        out.append(ctx.quote_ev("L1", "occurrence", r["quote"], st=opening, label="hook_invalid", judgment="count",
                                reason="钩子不实或诱导", model_conf=r["confidence"]))
    return out


def _founds(ctx: Ctx, task: str, item: str, kind: str, payload: dict | None = None, label=None, judge=None):
    r = ctx.ask(task, payload or {"transcript": ctx.main.text})
    out = []
    for x in r["items"]:
        out.append(ctx.quote_ev(item, kind, x["quote"], label=label(x) if label else (x.get("label") or None),
                                judgment=judge(x) if judge else binary(x["valid"]), reason=x["reason"], model_conf=x["confidence"]))
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
    return _founds(ctx, "o1_terms", "O1", "instance", {"transcript": ctx.main.text, "glossary": ctx.card.get("glossary", [])})


def o2(ctx: Ctx):
    return _founds(ctx, "o2_targeted", "O2", "instance", {"transcript": ctx.main.text, "targeted_points": ctx.card.get("targeted_points", [])})


def o3(ctx: Ctx):
    return _founds(ctx, "o3_scene", "O3", "instance", {"transcript": ctx.main.text, "scenarios": ctx.card.get("scenarios", [])},
                   label=lambda x: "scene")


def o4(ctx: Ctx):
    """节奏与气氛：弹幕到开始回应的时长、是否回到主线、冷场次数、未回应条数，以及音量、音高起伏。"""
    main = ctx.seg("main")
    checks = objection_checks(ctx)
    latencies, unanswered, segs = [], 0, []
    for i, (o, r) in enumerate(zip(ctx.objections, checks)):
        nxt = ctx.objections[i + 1]["video_ms"] if i + 1 < len(ctx.objections) else main["end_ms"]
        after = ctx.main.window(o["video_ms"], nxt)
        first = next((w for w in after.words if w.text.strip()), None)
        if not r["answered"] or first is None:
            unanswered += 1
        else:
            latencies.append((first.start_ms - o["video_ms"]) / 1000)
        segs.append({"objection": o["text"], "text": after.text})
    ml = ctx.ask("o4_mainline", {"segments_after_objection": segs})
    returned = ml["returned"][: len(segs)]
    dead_air = sum(1 for a, b in ctx.acoustic["main"]["silences_ms"] if b - a >= ctx.cfg.o4.dead_air_ms)
    f = ctx.acoustic["main"]
    metrics = {
        "max_response_latency_s": max(latencies) if latencies else (main["end_ms"] - main["start_ms"]) / 1000,
        "returned_to_mainline_ratio": sum(returned) / len(returned) if returned else 0.0,
        "dead_air_count": float(dead_air),
        "unanswered_objections": float(unanswered),
        "loudness_range_db": f["loudness_range_db"],
        "pitch_range_st": f["pitch_range_st"],
    }
    src = {"max_response_latency_s": "rule", "returned_to_mainline_ratio": "llm", "dead_air_count": "audio",
           "unanswered_objections": "llm", "loudness_range_db": "audio", "pitch_range_st": "audio"}
    conf = {"returned_to_mainline_ratio": ml["confidence"]}
    return [ctx.ev("O4", "metric", label=k, value=float(v), source=src[k], confidence=conf.get(k, 0.85),
                   start=main["start_ms"], end=main["end_ms"]) for k, v in metrics.items()]


def o5(ctx: Ctx):
    out = []
    for q in ctx.questions:
        name = f"question:{q['question_id']}"
        st = ctx.texts[name]
        r = ctx.ask("o5_answer", {"question": q["text"], "full_points": q.get("full_points", []), "answer": st.text})
        seg = ctx.seg(name)
        out.append(ctx.ev("O5", "question", ref=q["question_id"], judgment=r["level"], quote=st.text[:200], reason=r["reason"],
                          confidence=r["confidence"], source="llm", start=seg["start_ms"], end=seg["end_ms"], segment=name))
    return out
