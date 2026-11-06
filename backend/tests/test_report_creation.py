"""报告构造回归，不连接数据库，核对首次创建和重算的历史字段语义。"""
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
import yaml

from app.models.entities import AuditionSheet, DetectorConfigVersion, Recording, RedlineLexiconVersion, Report, RubricVersion
from app.pipeline import orchestrator, suggest
from app.providers import resilient
from app.services import rescore as rescore_service
from scoring import finalize, parse_config, score_round
from tests.scoring.helpers import builder_for_total, context, raw_config


@pytest.fixture
def _clean():
    """本文件只使用内存中的模型对象，覆盖后端测试的自动清库 fixture。"""


def report_inputs(totals):
    raw = raw_config()
    cfg = parse_config(raw)
    results = [score_round(builder_for_total(total).items, cfg, context(model_manifest={"llm": f"model-round-{n}"}))
               for n, total in enumerate(totals, start=1)]
    runs = [SimpleNamespace(id=uuid4(), round_no=n) for n in range(1, len(results) + 1)]
    rec = Recording(id=uuid4(), sheet_id=uuid4(), status="processing")
    rv = RubricVersion(id=uuid4(), status="published", yaml_text=yaml.safe_dump(raw))
    dv = DetectorConfigVersion(id=uuid4(), status="published")
    lex = RedlineLexiconVersion(id=uuid4(), status="draft")
    sheet = AuditionSheet(id=rec.sheet_id, redline_lexicon_version_id=lex.id)
    objects = {Recording: rec, AuditionSheet: sheet, DetectorConfigVersion: dv, RedlineLexiconVersion: lex}
    db = SimpleNamespace(scalar=Mock(return_value=None), get=Mock(side_effect=lambda model, key: objects[model]), add=Mock(), flush=Mock())
    return db, rec, rv, dv, sheet, cfg, results, runs


def assert_verdict_fields(report, verdict):
    assert report.verdict == verdict.model_dump(mode="json")
    assert (report.label, report.conclusion, report.critical, report.redline_hit) == (
        verdict.label, verdict.conclusion, verdict.critical, verdict.redline_hit,
    )


@pytest.mark.parametrize("totals", [(4,), (17,), (13, 15, 14)])
def test_first_report_keeps_display_provenance_and_legacy_lexicon_status(monkeypatch, totals):
    db, rec, rv, dv, sheet, cfg, results, runs = report_inputs(totals)
    verdict = finalize(results, cfg)
    suggestions = [{"sentence": "原句", "suggestion": "示范说法", "source": "llm"}]
    generate = Mock(return_value=suggestions)
    monkeypatch.setattr(orchestrator, "detector_config", lambda db: (dv, None))
    monkeypatch.setattr(orchestrator, "get_settings", lambda: SimpleNamespace(limit_llm=8, call_retry_backoff_s=()))
    monkeypatch.setattr(orchestrator, "get_providers", lambda: None)
    monkeypatch.setattr(orchestrator, "_redis", lambda: None)
    monkeypatch.setattr(resilient, "resilient", lambda *args, **kwargs: None)
    monkeypatch.setattr(suggest, "generate", generate)
    audit = Mock()
    monkeypatch.setattr(orchestrator.audit, "record", audit)

    orchestrator._make_report(db, rec, sheet, rv, cfg, results, {r.round_no: r for r in runs})

    report = db.add.call_args.args[0]
    assert_verdict_fields(report, verdict)
    assert report.revision == 1 and report.recording_id == rec.id
    assert report.rubric_version_id == rv.id and report.detector_config_version_id == dv.id
    assert report.config_hash == results[0].config_hash
    assert report.display_run_id == runs[verdict.display_round - 1].id
    assert report.model_manifest == results[verdict.display_round - 1].model_manifest
    assert report.suggestions == suggestions
    # 历史题单带草稿红线词表时，首次创建沿用旧逻辑标记非正式，即使当前红线关闭。
    assert report.informal is True and audit.call_args.kwargs["informal"] is True
    assert rec.status == "done" and rec.finished_at is not None
    assert generate.call_args.args[2] == report.display_run_id
    assert generate.call_args.args[3] == results[verdict.display_round - 1].model_dump(mode="json")


def test_first_report_does_not_duplicate_existing_revision(monkeypatch):
    db, rec, rv, dv, sheet, cfg, results, runs = report_inputs((4,))
    db.scalar.return_value = Report(id=uuid4())
    build = Mock()
    monkeypatch.setattr(orchestrator, "build_report", build)

    orchestrator._make_report(db, rec, sheet, rv, cfg, results, {r.round_no: r for r in runs})

    build.assert_not_called()
    db.add.assert_not_called()
    assert rec.status == "processing" and rec.finished_at is None


@pytest.mark.parametrize("same_display", [True, False])
@pytest.mark.parametrize("draft_detector", [True, False])
def test_rescore_preserves_history_and_only_reuses_matching_suggestions(monkeypatch, same_display, draft_detector):
    db, rec, rv, dv, sheet, cfg, results, runs = report_inputs((13, 15, 14))
    verdict = finalize(results, cfg)
    display = runs[verdict.display_round - 1]
    dv.status = "draft" if draft_detector else "published"
    old_verdict = {"label": "not_recommend", "reason": "历史结论"}
    suggestions = [{"sentence": "原句", "suggestion": "历史建议"}]
    old = Report(
        id=uuid4(), recording_id=rec.id, revision=7, rubric_version_id=uuid4(),
        detector_config_version_id=dv.id, display_run_id=display.id if same_display else runs[0].id,
        config_hash="historical-hash", model_manifest={"llm": "historical-model"}, verdict=old_verdict,
        label="not_recommend", conclusion="fail", critical=False, redline_hit=False, suggestions=suggestions,
    )
    db.scalar.return_value = 7
    round_results = Mock(return_value=(runs, results))
    monkeypatch.setattr(rescore_service, "round_results", round_results)

    report = rescore_service.rescore(db, old, rv)

    assert_verdict_fields(report, verdict)
    assert report.revision == 8 and report.recording_id == rec.id
    assert report.rubric_version_id == rv.id and report.detector_config_version_id == dv.id
    assert report.config_hash == results[0].config_hash
    assert report.display_run_id == display.id
    assert report.model_manifest == results[verdict.display_round - 1].model_manifest
    assert report.suggestions == (suggestions if same_display else [])
    # 重算在红线关闭时忽略旧题单词表状态，保留与首次创建不同的历史口径。
    assert report.informal is draft_detector
    assert old.superseded_at is not None and old.revision == 7
    assert old.verdict == old_verdict and old.config_hash == "historical-hash"
    assert old.model_manifest == {"llm": "historical-model"} and old.suggestions == suggestions
    assert old.label == "not_recommend" and old.conclusion == "fail"
    round_results.assert_called_once_with(db, rec, rv, save=True)
    db.add.assert_called_once_with(report)
    db.flush.assert_called_once_with()
