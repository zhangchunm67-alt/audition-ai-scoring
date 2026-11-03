"""销售循环 S1–S4（rubric 第 5 节）。"""
from __future__ import annotations

from .common import Ctx, binary


def s1(ctx: Ctx):
    r = ctx.ask("s1_need", {"transcript": ctx.main.text})
    return [ctx.quote_ev("S1", "level", r["quote"], judgment=r["level"], reason=r["reason"], model_conf=r["confidence"])]


def product_check(ctx: Ctx) -> dict:
    card = ctx.card
    return ctx.cached("s2", lambda: ctx.ask("s2_product", {
        "transcript": ctx.main.text,
        "checklist": [{"id": p["id"], "name": p["name"]} for p in card.get("checklist", [])],
        "key_facts": card.get("key_numbers", []),
    }))


def s2(ctx: Ctx):
    """产品讲解：每个必讲要点都要有一条核对证据（讲到且讲对 / 没讲到或讲错），另给结构等级；讲错每处单独一条。"""
    r = product_check(ctx)
    names = {p["id"]: p["name"] for p in ctx.card.get("checklist", [])}
    got = {p["id"] for p in r["points"]}
    if got != set(names):
        raise ValueError(f"大模型漏核对了要点：{sorted(set(names) - got)}")
    out = []
    errors = {e["quote"]: e for e in r["errors"]}
    for p in r["points"]:
        out.append(ctx.quote_ev("S2", "checklist_hit", p["quote"], ref=p["id"], label=names[p["id"]],
                                judgment=binary(p["covered"] and p["correct"]), reason=p["reason"], model_conf=p["confidence"]))
        if p["covered"] and not p["correct"] and p["quote"] not in errors:
            errors[p["quote"]] = {"quote": p["quote"], "reason": p["reason"], "confidence": p["confidence"]}
    out.append(ctx.ev("S2", "level", ref="structure", judgment=r["structure_level"], reason=r["structure_reason"],
                      confidence=r["structure_confidence"], source="llm"))
    for e in errors.values():  # 同一处错误只在 S2 扣一次（L5、O1 不再扣）
        out.append(ctx.quote_ev("S2", "occurrence", e["quote"], label="error", judgment="count", reason=e["reason"], model_conf=e["confidence"]))
    return out


def objection_checks(ctx: Ctx) -> list[dict]:
    main_end = ctx.seg("main")["end_ms"]

    def run():
        res = []
        for o in ctx.objections:
            after = ctx.main.window(o["video_ms"], main_end).text  # 按内容归属（C8）：给出弹出后的全部内容，由模型找对应回答
            res.append(ctx.ask("s3_objection", {"objection": o["text"], "answer_points": o.get("answer_points", []), "transcript_after": after}))
        return res

    return ctx.cached("s3", run)


def s3(ctx: Ctx):
    out = []
    for o, r in zip(ctx.objections, objection_checks(ctx)):
        kw = dict(ref=o["objection_id"], after_ms=o["video_ms"], model_conf=r["confidence"], reason=r["reason"])
        if not r["answered"]:
            out.append(ctx.ev("S3", "question", ref=o["objection_id"], label="no_answer", judgment="count", reason=r["reason"],
                              confidence=r["confidence"], source="llm", start=o["video_ms"]))
            continue
        for el in ("direct_answer", "advantage", "altruistic_close"):
            out.append(ctx.quote_ev("S3", "question", r["quote"], label=el, judgment=binary(r[el]), **kw))
        if r["wrong"]:
            out.append(ctx.quote_ev("S3", "question", r["quote"], label="wrong_answer", judgment="count", **kw))
    return out


def s4(ctx: Ctx):
    r = ctx.ask("s4_closing", {"transcript": ctx.main.text})
    return [ctx.quote_ev("S4", "instance", x["quote"], label=x["method"], judgment=binary(x["compliant"]), reason=x["reason"],
                         model_conf=x["confidence"]) for x in r["items"] if x["method"] != "other"]
