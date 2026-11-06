"""销售循环 S1–S4（评分表 20261105“销售循环运用”）。"""
from __future__ import annotations

from .common import Ctx, binary, check_level

S2_MAX = 50


class S2NotCalibrated(ValueError):
    """产品缺少固定话术或对应的 S2 校准记录：S2 不能自动出分（CAL-S2-PRODUCT）。"""


def s1(ctx: Ctx):
    """激发需求：评分表“根据主观打分”，大模型直接给 0–10 分（须校准）。"""
    r = ctx.ask("s1_need", {"transcript": ctx.main.text})
    level = check_level("S1", r["level"], 10)
    if not r["quote"].strip():
        if level:
            raise ValueError("S1: 给分大于 0 却没有引用原文")
        return [ctx.ev("S1", "level", judgment=0, reason=r["reason"], confidence=r["confidence"], source="llm")]
    return [ctx.quote_ev("S1", "level", r["quote"], judgment=level, reason=r["reason"], model_conf=r["confidence"])]


def s2_material(card: dict) -> tuple[dict, dict]:
    """取产品的固定话术和 S2 校准记录；任一缺失或版本对不上即拒绝自动出分。"""
    script = card.get("fixed_script") or {}
    cal = card.get("s2_calibration") or {}
    if not str(script.get("text") or "").strip() or not script.get("version"):
        raise S2NotCalibrated("S2: 卖点卡没有带版本的固定话术，产品讲解不能自动出分")
    if not cal.get("version"):
        raise S2NotCalibrated("S2: 该产品没有 S2 校准记录（须先用人工标注样本校准），产品讲解不能自动出分")
    if cal.get("fixed_script_version") != script["version"]:
        raise S2NotCalibrated(f"S2: 校准记录对应固定话术 {cal.get('fixed_script_version')!r}，与当前固定话术 {script['version']!r} 不一致，须重新校准")
    return script, cal


def product_check(ctx: Ctx) -> dict:
    script, cal = s2_material(ctx.card)
    return ctx.cached("s2", lambda: ctx.ask("s2_fixed_script", {
        "transcript": ctx.main.text,
        "fixed_script": script["text"],
        "max_score": S2_MAX,
        "anchors": cal.get("anchors", []),
    }))


def s2(ctx: Ctx):
    """产品讲解：按该产品固定话术的完成准确程度给 0–50 分，只出一条等级证据（ref=fixed_script_accuracy），
    label 记下所用的固定话术版本和校准版本，便于追溯。讲错的说法写进理由，不另行扣分（评分表没有讲错扣分规则）。"""
    script, cal = s2_material(ctx.card)
    r = product_check(ctx)
    score = check_level("S2", r["score"], S2_MAX)
    label = f"fixed_script={script['version']};calibration={cal['version']}"
    reason = r["reason"]
    if r["errors"]:
        reason += "；与固定话术或条款不符：" + "；".join(e["quote"] for e in r["errors"])
    kw = dict(ref="fixed_script_accuracy", label=label, judgment=score, reason=reason)
    if not r["quote"].strip():
        if score:
            raise ValueError("S2: 给分大于 0 却没有引用原文")
        return [ctx.ev("S2", "level", confidence=r["confidence"], source="llm", **kw)]
    return [ctx.quote_ev("S2", "level", r["quote"], model_conf=r["confidence"], **kw)]


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
    """逼单：从众、损失规避、权威认同、价格拆分、沉没成本，各算一次；不合规写法留证据但不计（judgment=not_count）。"""
    r = ctx.ask("s4_closing", {"transcript": ctx.main.text})
    return [ctx.quote_ev("S4", "instance", x["quote"], label=x["method"], judgment=binary(x["compliant"]), reason=x["reason"],
                         model_conf=x["confidence"]) for x in r["items"] if x["method"] != "other"]
