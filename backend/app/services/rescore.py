"""按新版评分标准重算（P-B14 推荐做法）：用已存的证据重新计分，不重跑模型；生成新的报告修订，旧修订保留。
新版本需要更多轮次（例如临界范围变宽）时无法只重算，须重新处理。"""
from __future__ import annotations

from datetime import datetime, timezone

import yaml
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from scoring import EvidenceError, finalize, parse_config, rounds_required, score_round

from ..models.convert import row_to_evidence
from ..models.entities import AuditionSheet, DetectorConfigVersion, DetectorRun, EvidenceRow, PipelineRun, ProductCard, Recording, RedlineLexiconVersion, Report, RubricVersion, ScoreResultRow
from ..pipeline.runner import scoring_context


def round_results(db: Session, rec: Recording, rv: RubricVersion, *, save: bool) -> tuple[list[PipelineRun], list]:
    """用已存证据按指定评分标准重算各轮（不重跑模型）。save=True 时把结果存进 score_results。"""
    cfg = parse_config(yaml.safe_load(rv.yaml_text))
    sheet = db.get(AuditionSheet, rec.sheet_id)
    card = db.get(ProductCard, sheet.product_card_id).content
    runs = db.scalars(select(PipelineRun).where(PipelineRun.recording_id == rec.id, PipelineRun.status == "completed")
                      .order_by(PipelineRun.round_no)).all()
    if not runs:
        raise HTTPException(422, "这条录像还没有完成的处理结果")
    results = []
    for run in runs:
        evs = [row_to_evidence(r) for r in db.scalars(select(EvidenceRow).where(EvidenceRow.run_id == run.id).order_by(EvidenceRow.id))]
        done = set(db.scalars(select(DetectorRun.detector_id).where(DetectorRun.run_id == run.id, DetectorRun.status == "completed")))
        try:
            r = score_round(evs, cfg, scoring_context(rec, sheet, card, done, run.model_manifest))
        except EvidenceError as exc:
            raise HTTPException(422, f"已有证据与该版本的条目不兼容，需重新处理：{exc}") from exc
        if r.status != "complete":
            raise HTTPException(422, f"按该版本缺少必需证据（{'、'.join(r.missing_items)}），需重新处理")
        if save:
            row = db.scalar(select(ScoreResultRow).where(ScoreResultRow.run_id == run.id, ScoreResultRow.rubric_version_id == rv.id))
            if row is None:
                db.add(ScoreResultRow(run_id=run.id, rubric_version_id=rv.id, config_hash=r.config_hash, result=r.model_dump(mode="json")))
            else:
                row.config_hash, row.result = r.config_hash, r.model_dump(mode="json")
        results.append(r)
    return list(runs), results


def ai_outcome(db: Session, rec: Recording, rv: RubricVersion):
    """按指定版本得出 AI 的最终结论和展示轮结果（不保存、不生成报告）。轮次不够时返回 None。"""
    cfg = parse_config(yaml.safe_load(rv.yaml_text))
    _, results = round_results(db, rec, rv, save=False)
    need = rounds_required(results[0], cfg)
    if need > len(results):
        return None
    v = finalize(results[:need], cfg)
    return v, results[v.display_round - 1]


def rescore(db: Session, rep: Report, rv: RubricVersion) -> Report:
    if rv.status == "retired":
        raise HTTPException(422, "该评分标准版本已停用")
    cfg = parse_config(yaml.safe_load(rv.yaml_text))
    rec = db.get(Recording, rep.recording_id)
    sheet = db.get(AuditionSheet, rec.sheet_id)
    runs, results = round_results(db, rec, rv, save=True)
    need = rounds_required(results[0], cfg)
    if need > len(results):
        raise HTTPException(409, f"按新版本这是临界样本，需要 {need} 轮，现有 {len(results)} 轮；请重新处理该录像")
    results = results[:need]
    v = finalize(results, cfg)
    display = runs[v.display_round - 1]
    now = datetime.now(timezone.utc)
    rep.superseded_at = now
    dv = db.get(DetectorConfigVersion, rep.detector_config_version_id)
    lex = db.get(RedlineLexiconVersion, sheet.redline_lexicon_version_id) if (cfg.redlines.enabled and sheet.redline_lexicon_version_id) else None
    nxt = (db.scalar(select(func.max(Report.revision)).where(Report.recording_id == rec.id)) or 0) + 1
    new = Report(
        recording_id=rec.id, revision=nxt, rubric_version_id=rv.id, config_hash=results[0].config_hash, detector_config_version_id=dv.id,
        model_manifest=results[v.display_round - 1].model_manifest, verdict=v.model_dump(mode="json"), label=v.label, conclusion=v.conclusion,
        critical=v.critical, redline_hit=v.redline_hit, display_run_id=display.id,
        informal=rv.status != "published" or dv.status != "published" or (lex is not None and lex.status != "published"),
        suggestions=rep.suggestions if display.id == rep.display_run_id else [],  # 示范说法按展示轮的逐字稿生成
    )
    db.add(new)
    db.flush()
    return new
