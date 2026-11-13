"""逐句评分的示范说法（M5-6）：对有问题的句子，让大模型给一句改进后的说法。只用于辅导展示，不参与计分。
生成失败不影响出报告（报告照常生成，只是没有示范说法）。"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from ..models.entities import AuditionSheet, ProductCard, Recording
from ..providers.base import Providers
from ..services.report_view import evidence_dicts, sentence_view
from . import llm
from .text import _norm

log = logging.getLogger("audition.pipeline")
MAX_SENTENCES = 30
# 这些条目的问题不在话术本身（画面里的穿着、小动作，笑场），改写句子没有意义
NOT_ABOUT_WORDING = {"P1", "P8", "P10"}
MIN_CHARS = 6  # “对不对？”这类短句没有可改写的内容，硬改只会改出不相干的话


def generate(db: Session, rec: Recording, run_id, result: dict, providers: Providers) -> list[dict]:
    sheet = db.get(AuditionSheet, rec.sheet_id)
    card = db.get(ProductCard, sheet.product_card_id).content
    evidence = evidence_dicts(db, run_id, result)
    out = []
    for seg in sentence_view(db, rec, run_id, evidence, []):
        for s in seg["sentences"]:
            if not s["issue"] or len(out) >= MAX_SENTENCES:
                continue
            issues = [{"item": h["item_id"], "item_name": h["item_name"], "label": h["label"], "reason": h["reason"]}
                      for h in s["hits"] if h["issue"] and h["item_id"] not in NOT_ABOUT_WORDING]
            if not issues or len(_norm(s["text"])) < MIN_CHARS:
                continue
            try:
                r = llm.ask(providers.llm, "rewrite", {"sentence": s["text"], "issues": issues, "glossary": card.get("glossary", []),
                                                       "key_numbers": card.get("key_numbers", [])})
            except Exception as exc:  # noqa: BLE001
                log.warning("示范说法生成失败：%s", str(exc)[:200])
                continue
            if not r["suggestion"].strip() or _norm(r["suggestion"]) == _norm(s["text"]):
                continue  # 模型认为不需要改
            out.append({"segment": s["segment"], "start_ms": s["start_ms"], "end_ms": s["end_ms"], "sentence": s["text"],
                        "suggestion": r["suggestion"], "source": "llm"})
    return out
