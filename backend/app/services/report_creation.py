"""首次评分与重算共用的报告构造，数据库事务由调用方管理。"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from scoring import FinalVerdict, RoundResult

from ..models.entities import DetectorConfigVersion, RedlineLexiconVersion, Report, RubricVersion


MODEL_KEYS = ("asr", "speech_eval", "llm", "vision", "laugh", "voice")


def uses_mock(manifest: dict) -> bool:
    return any(str(manifest.get(k, "")).startswith("mock") for k in MODEL_KEYS)


def build_report(
    *,
    recording_id: UUID,
    revision: int,
    rubric: RubricVersion,
    detector_config: DetectorConfigVersion,
    lexicon: RedlineLexiconVersion | None,
    verdict: FinalVerdict,
    results: Sequence[RoundResult],
    display_run_id: UUID,
    suggestions: list[dict[str, Any]],
) -> Report:
    """索引字段统一从最终结论派生，追溯信息保留首轮与展示轮各自的来源。"""
    display_result = results[verdict.display_round - 1]
    return Report(
        recording_id=recording_id,
        revision=revision,
        rubric_version_id=rubric.id,
        config_hash=results[0].config_hash,
        detector_config_version_id=detector_config.id,
        model_manifest=display_result.model_manifest,
        verdict=verdict.model_dump(mode="json"),
        label=verdict.label,
        conclusion=verdict.conclusion,
        critical=verdict.critical,
        redline_hit=verdict.redline_hit,
        display_run_id=display_run_id,
        informal=(rubric.status != "published" or detector_config.status != "published"
                  or (lexicon is not None and lexicon.status != "published")
                  # S2 校准记录未经验证（CAL-S2-PRODUCT）
                  or display_result.model_manifest.get("s2_calibration_status", "validated") != "validated"
                  # 用了 Mock 模型（开发测试），分数不是真实模型给的
                  or uses_mock(display_result.model_manifest)),
        suggestions=suggestions,
    )
