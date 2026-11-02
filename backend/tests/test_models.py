"""数据模型：整条链路可写入、证据可无损还原给计分引擎、关键约束生效。"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.cli import create_user, seed_demo
from app.models import entities as m
from app.models.convert import evidence_to_row, row_to_evidence
from app.security.crypto import encrypt
from scoring import config_hash, finalize, load_config, score_round
from tests.scoring.helpers import CONFIG_PATH, context, full_marks


def _recording(db):
    seed_demo(db)
    admin = create_user(db, "admin1", "admin", "管理员", "correct-horse-battery")
    p = db.scalar(select(m.Product))
    sheet = m.AuditionSheet(
        code="TS20261102-ABCDEF", product_id=p.id, product_card_id=db.scalar(select(m.ProductCard.id)),
        rubric_version_id=db.scalar(select(m.RubricVersion.id)), redline_lexicon_version_id=db.scalar(select(m.RedlineLexiconVersion.id)),
        draw_rule_snapshot={}, objections=[], questions=[], reading_script_id=db.scalar(select(m.ReadingScript.id)),
        reading_text="x", recording_rules_version="rules-v1", uses_draft_config=True,
    )
    cand = m.Candidate(name_enc=encrypt("张三", b"k" * 32))
    db.add_all([sheet, cand])
    db.flush()
    consent = m.ConsentRecord(candidate_id=cand.id, consent_text_version="consent-v1", signed_on=date(2026, 11, 2), registered_by=admin.id)
    db.add(consent)
    db.flush()
    rec = m.Recording(candidate_id=cand.id, sheet_id=sheet.id, consent_record_id=consent.id, audience="new_trial",
                      props_available=True, uploaded_by=admin.id, main_duration_ms=600_000)
    db.add(rec)
    db.flush()
    return rec, sheet


def test_tables_exist(engine):
    names = set(inspect(engine).get_table_names())
    for t in ("users", "audit_logs", "rubric_versions", "product_cards", "audition_sheets", "candidates", "consent_records",
              "recordings", "media_assets", "pipeline_runs", "detector_runs", "evidence", "score_results", "reports",
              "gold_sets", "calibration_assignments", "notifications"):
        assert t in names, t
    for gone in ("batches", "invitations", "attempts", "video_access_requests"):
        assert gone not in names


def test_full_chain_and_evidence_round_trip(db):
    rec, sheet = _recording(db)
    cfg = load_config(CONFIG_PATH)
    run = m.PipelineRun(recording_id=rec.id, round_no=1, status="completed")
    db.add(run)
    db.flush()
    b = full_marks()
    for _ in range(23):
        b.occ("P2", "那么", quote="那么我们来看一下这个产品", reason="句首过渡，删掉后意思不变")
    b.add("R1", "redline", judgment="count", confidence=0.9, quote="稳赚不赔", segment="main")
    db.add_all([evidence_to_row(e, run.id) for e in b.items])
    db.add_all([m.DetectorRun(run_id=run.id, detector_id=d, status="completed") for d in context().completed_detectors])
    db.flush()
    rows = db.scalars(select(m.EvidenceRow).where(m.EvidenceRow.run_id == run.id).order_by(m.EvidenceRow.id)).all()
    restored = [row_to_evidence(r) for r in rows]
    assert restored == b.items
    done = set(db.scalars(select(m.DetectorRun.detector_id).where(m.DetectorRun.run_id == run.id)))
    result = score_round(restored, cfg, context(props=rec.props_available, audience=rec.audience, completed=done))
    verdict = finalize([result], cfg)
    rep = m.Report(
        recording_id=rec.id, rubric_version_id=sheet.rubric_version_id, config_hash=result.config_hash,
        detector_config_version_id=db.scalar(select(m.DetectorConfigVersion.id)) or _detector(db).id,
        model_manifest=result.model_manifest, verdict=verdict.model_dump(mode="json"), label=verdict.label,
        conclusion=verdict.conclusion, critical=verdict.critical, redline_hit=verdict.redline_hit, display_run_id=run.id,
    )
    db.add(rep)
    db.commit()
    got = db.get(m.Report, rep.id)
    assert got.label == "not_recommend" and got.redline_hit
    assert got.verdict["redline_hits"][0][1]["quote"] == "稳赚不赔"
    assert got.config_hash == config_hash(cfg) and got.model_manifest == context().model_manifest


def _detector(db):
    d = m.DetectorConfigVersion(version="det-1", content={}, content_hash="h")
    db.add(d)
    db.flush()
    return d


def test_one_recording_per_sheet(db):
    rec, sheet = _recording(db)
    db.add(m.Recording(candidate_id=rec.candidate_id, sheet_id=sheet.id, consent_record_id=rec.consent_record_id,
                       audience="new_trial", props_available=False, uploaded_by=rec.uploaded_by))
    with pytest.raises(IntegrityError):
        db.flush()


def test_round_no_unique(db):
    rec, _ = _recording(db)
    db.add_all([m.PipelineRun(recording_id=rec.id, round_no=1), m.PipelineRun(recording_id=rec.id, round_no=1)])
    with pytest.raises(IntegrityError):
        db.flush()


def test_transcript_must_disable_disfluency_removal(db):
    rec, _ = _recording(db)
    run = m.PipelineRun(recording_id=rec.id, round_no=1)
    db.add(run)
    db.flush()
    db.add(m.Transcript(run_id=run.id, segment="main", text="那么那么", words=[], provider="mock", model_version="1", disfluency_removal=True))
    with pytest.raises(IntegrityError):
        db.flush()


def test_evidence_confidence_range(db):
    rec, _ = _recording(db)
    run = m.PipelineRun(recording_id=rec.id, round_no=1)
    db.add(run)
    db.flush()
    db.add(m.EvidenceRow(run_id=run.id, evidence_id="e-1", item_id="P2", kind="occurrence", judgment="count", confidence=1.5, source="llm"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_published_rubric_needs_published_at(db):
    db.add(m.RubricVersion(version="v-x", status="published", yaml_text="x", config_hash="h"))
    with pytest.raises(IntegrityError):
        db.flush()
