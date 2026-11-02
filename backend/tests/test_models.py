"""数据模型：迁移可升降级、整条链路可写入、证据可无损还原给计分引擎、关键约束生效。

需要 PostgreSQL：设置 TEST_DATABASE_URL（库会被清空重建），未设置则跳过。
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import entities as m
from app.models.convert import evidence_to_row, row_to_evidence
from scoring import config_hash, finalize, load_config, score_round
from tests.scoring.helpers import CONFIG_PATH, context, full_marks

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="未设置 TEST_DATABASE_URL")
BACKEND = Path(__file__).resolve().parents[1]


def _alembic(*args: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND / "alembic.ini"))
    os.environ["DATABASE_URL"] = URL  # type: ignore[assignment]
    getattr(command, args[0])(cfg, *args[1:])


@pytest.fixture(scope="module")
def engine():
    _alembic("downgrade", "base")
    _alembic("upgrade", "head")
    eng = create_engine(URL)  # type: ignore[arg-type]
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    with Session(engine) as s:
        yield s
        s.rollback()


def _chain(db: Session):
    now = datetime.now(timezone.utc)
    cfg = load_config(CONFIG_PATH)
    admin = m.User(username=f"admin-{uuid.uuid4().hex[:6]}", display_name="管理员", role="admin", password_hash="x")
    rv = m.RubricVersion(version=f"rubric-v0.1-{uuid.uuid4().hex[:6]}", yaml_text=CONFIG_PATH.read_text("utf-8"), config_hash=config_hash(cfg))
    dv = m.DetectorConfigVersion(version=f"det-{uuid.uuid4().hex[:6]}", content={"p2_lexicon": ["那么"]}, content_hash="h")
    lex = m.RedlineLexiconVersion(version=f"lex-{uuid.uuid4().hex[:6]}", content={"R1": {"keywords": ["稳赚不赔"]}})
    prod = m.Product(code=f"kid-{uuid.uuid4().hex[:6]}", name="少儿医疗险")
    db.add_all([admin, rv, dv, lex, prod])
    db.flush()
    card = m.ProductCard(product_id=prod.id, version=1, content={"checklist": [{"id": "coverage", "points": 5}]})
    rule = m.DrawRule(product_id=prod.id, objection_times_ms=[240000, 330000, 420000, 480000])
    db.add_all([card, rule])
    db.flush()
    batch = m.Batch(
        name="11 月第 1 批", product_id=prod.id, product_card_id=card.id, rubric_version_id=rv.id,
        detector_config_version_id=dv.id, redline_lexicon_version_id=lex.id, draw_rule_id=rule.id,
        audience="new_trial", expires_at=now + timedelta(days=7), created_by=admin.id,
    )
    cand = m.Candidate(name_enc=b"\x00enc", phone_hash="sha256:abc")
    db.add_all([batch, cand])
    db.flush()
    inv = m.Invitation(batch_id=batch.id, candidate_id=cand.id, token_hash=f"sha256:{uuid.uuid4().hex}", location="studio", expires_at=now + timedelta(days=7))
    db.add(inv)
    db.flush()
    consent = m.Consent(invitation_id=inv.id, consent_text_version="consent-v1", granted=True)
    db.add(consent)
    db.flush()
    att = m.Attempt(invitation_id=inv.id, attempt_no=1, location="studio", consent_id=consent.id, main_duration_ms=600000)
    db.add(att)
    db.flush()
    return cfg, rv, dv, att


def test_tables_exist(engine):
    names = set(inspect(engine).get_table_names())
    for t in ("users", "audit_logs", "rubric_versions", "product_cards", "batches", "invitations", "consents", "attempts",
              "media_assets", "pipeline_runs", "detector_runs", "evidence", "score_results", "reports", "gold_sets",
              "calibration_assignments", "notifications", "video_access_requests"):
        assert t in names, t


def test_full_chain_and_evidence_round_trip(db):
    cfg, rv, dv, att = _chain(db)
    run = m.PipelineRun(attempt_id=att.id, round_no=1, status="completed", model_manifest={"asr": "mock-asr@1"})
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
    assert restored == b.items  # 无损还原
    done = set(db.scalars(select(m.DetectorRun.detector_id).where(m.DetectorRun.run_id == run.id, m.DetectorRun.status == "completed")))
    result = score_round(restored, cfg, context(completed=done))
    assert result.status == "complete"
    verdict = finalize([result], cfg)
    db.add(m.ScoreResultRow(run_id=run.id, rubric_version_id=rv.id, config_hash=result.config_hash, result=result.model_dump(mode="json")))
    rep = m.Report(
        attempt_id=att.id, rubric_version_id=rv.id, config_hash=result.config_hash, detector_config_version_id=dv.id,
        model_manifest=result.model_manifest, verdict=verdict.model_dump(mode="json"), label=verdict.label,
        conclusion=verdict.conclusion, critical=verdict.critical, redline_hit=verdict.redline_hit, display_run_id=run.id,
    )
    db.add(rep)
    db.flush()
    got = db.get(m.Report, rep.id)
    assert got.label == "not_recommend" and got.redline_hit
    assert got.verdict["redline_hits"][0][1]["quote"] == "稳赚不赔"
    assert got.config_hash == config_hash(cfg) and got.model_manifest == context().model_manifest


def test_round_no_unique_per_attempt(db):
    _, _, _, att = _chain(db)
    db.add(m.PipelineRun(attempt_id=att.id, round_no=1))
    db.flush()
    db.add(m.PipelineRun(attempt_id=att.id, round_no=1))
    with pytest.raises(IntegrityError):
        db.flush()


def test_transcript_must_disable_disfluency_removal(db):
    _, _, _, att = _chain(db)
    run = m.PipelineRun(attempt_id=att.id, round_no=1)
    db.add(run)
    db.flush()
    db.add(m.Transcript(run_id=run.id, segment="main", text="那么那么", words=[], provider="mock", model_version="1", disfluency_removal=True))
    with pytest.raises(IntegrityError):
        db.flush()


def test_evidence_confidence_range(db):
    _, _, _, att = _chain(db)
    run = m.PipelineRun(attempt_id=att.id, round_no=1)
    db.add(run)
    db.flush()
    db.add(m.EvidenceRow(run_id=run.id, evidence_id="e-1", item_id="P2", kind="occurrence", judgment="count", confidence=1.5, source="llm"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_published_rubric_needs_published_at(db):
    db.add(m.RubricVersion(version=f"v-{uuid.uuid4().hex[:6]}", status="published", yaml_text="x", config_hash="h"))
    with pytest.raises(IntegrityError):
        db.flush()
