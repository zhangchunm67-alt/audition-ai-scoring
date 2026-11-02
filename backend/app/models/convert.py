"""证据行与计分引擎类型之间的转换。"""
from __future__ import annotations

import uuid

from scoring.types import Evidence, Review

from .entities import EvidenceRow

_FIELDS = ("evidence_id", "item_id", "kind", "start_ms", "end_ms", "quote", "label", "judgment", "reason",
           "confidence", "source", "ref", "value", "segment")


def evidence_to_row(ev: Evidence, run_id: uuid.UUID) -> EvidenceRow:
    return EvidenceRow(run_id=run_id, review=ev.review.model_dump(), **{f: getattr(ev, f) for f in _FIELDS})


def row_to_evidence(row: EvidenceRow) -> Evidence:
    return Evidence(review=Review(**(row.review or {})), **{f: getattr(row, f) for f in _FIELDS})
