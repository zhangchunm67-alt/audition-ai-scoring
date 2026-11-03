"""合规红线 R1–R8（rubric 第 8 节）：词表召回候选句 + 大模型结合上下文判断。朗读段不检测（C10）。
S2 判为“讲错”的句子也送进 R2 检查（rubric：讲错了按红线 R2 检查）。"""
from __future__ import annotations

from ..text import sentences
from .common import Ctx, binary
from .sales import product_check

SKIP = {"reading"}


def redlines(ctx: Ctx):
    cands = []
    n = ctx.cfg.redlines.context_chars
    for name, st in ctx.texts.items():
        if name in SKIP:
            continue
        text = st.text
        for s in sentences(st):
            for rid, entry in ctx.lexicon.items():
                kw = next((k for k in entry.get("keywords", []) if k and k in s.text), None)
                if kw:
                    ctx_text = text[max(0, s.char_start - n): s.char_start + len(s.text) + n]
                    cands.append({"id": str(len(cands)), "redline_id": rid, "redline": entry.get("name", rid), "keyword": kw,
                                  "sentence": s.text, "context": ctx_text, "_s": s})
    if "R2" in ctx.lexicon:
        for e in product_check(ctx)["errors"]:
            hit = next((s for s in sentences(ctx.main) if e["quote"] and e["quote"] in s.text), None)
            if hit and not any(c["_s"] is hit and c["redline_id"] == "R2" for c in cands):
                cands.append({"id": str(len(cands)), "redline_id": "R2", "redline": ctx.lexicon["R2"].get("name", "R2"), "keyword": "",
                              "sentence": hit.text, "context": hit.text, "_s": hit})
    if not cands:
        return []
    res = {r["id"]: r for r in ctx.ask("redline_judge", {"candidates": [{k: v for k, v in c.items() if k != "_s"} for c in cands]})["items"]}
    out = []
    for c in cands:
        r = res.get(c["id"])
        if r is None:
            raise ValueError(f"大模型漏判了红线候选 {c['id']}")
        s = c["_s"]
        st = ctx.texts[s.segment]
        conf = min(r["confidence"], st.min_confidence(s.char_start, s.char_start + len(s.text)))
        out.append(ctx.ev(c["redline_id"], "redline", start=s.start_ms, end=s.end_ms, quote=s.text, label=c["keyword"] or "讲错",
                          judgment=binary(r["hit"]), reason=r["reason"], confidence=conf, source="llm", segment=s.segment))
    return out
