"""逐句评分的示范说法（M5-6）：对有问题的句子，让大模型给一句改进后的说法。只用于辅导展示，不参与计分。
生成失败不影响出报告（报告照常生成，只是没有示范说法）。"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from ..models.entities import AuditionSheet, ProductCard, Recording
from ..providers.base import Providers
from ..services.report_view import evidence_dicts, sentence_view
from . import llm

log = logging.getLogger("audition.pipeline")
MAX_SENTENCES = 30


def generate(db: Session, rec: Recording, run_id, result: dict, providers: Providers) -> list[dict]:
    sheet = db.get(AuditionSheet, rec.sheet_id)
    card = db.get(ProductCard, sheet.product_card_id).content
    evidence = evidence_dicts(db, run_id, result)
    out = []
    for seg in sentence_view(db, rec, run_id, evidence, []):
        for s in seg["sentences"]:
            if not s["issue"] or len(out) >= MAX_SENTENCES:
                continue
            issues = [{"item": h["item_id"], "item_name": h["item_name"], "label": h["label"], "reason": h["reason"]} for h in s["hits"] if h["issue"]]
            try:
                r = llm.ask(providers.llm, "rewrite", {"sentence": s["text"], "issues": issues, "glossary": card.get("glossary", [])})
            except Exception as exc:  # noqa: BLE001
                log.warning("示范说法生成失败：%s", str(exc)[:200])
                continue
            out.append({"segment": s["segment"], "start_ms": s["start_ms"], "end_ms": s["end_ms"], "sentence": s["text"],
                        "suggestion": r["suggestion"], "source": "llm"})
    return out
