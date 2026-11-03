"""处理流水线（M3）与自动判定（M4）：Mock 供应商端到端。"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.entities import (
    AuditLog, Candidate, DetectorRun, EvidenceRow, MediaAsset, Notification, PipelineRun, Recording, Report, ScoreResultRow, Transcript,
    UploadSession,
)
from app.providers.base import Providers, ProviderError
from app.providers.mock import Faults, MockASR, MockLaugh, MockLLM, MockSpeechEval, MockVision
from app.providers.registry import set_providers
from conftest import FULL_SEG
from test_recordings_api import SEG, _uploaded


@pytest.fixture(autouse=True)
def _reset_providers():
    yield
    set_providers(None)


def _providers(**kw) -> Providers:
    base = dict(asr=MockASR(), speech_eval=MockSpeechEval(), llm=MockLLM(), vision=MockVision(), laugh=MockLaugh())
    base.update(kw)
    return Providers(**base)


def _submit(api, db, video, seg=SEG, **kw):
    rec = _uploaded(api, db, video, **kw)
    assert api.put(f"/api/recordings/{rec['id']}/segments", json=seg).status_code == 200
    r = api.post(f"/api/recordings/{rec['id']}/submit")
    assert r.status_code == 200, r.text
    db.expire_all()
    return db.get(Recording, rec["id"])


def _runs(db, rec):
    return db.scalars(select(PipelineRun).where(PipelineRun.recording_id == rec.id).order_by(PipelineRun.round_no)).all()


def _report(db, rec) -> Report:
    return db.scalar(select(Report).where(Report.recording_id == rec.id))


def _result(db, run) -> dict:
    return db.scalar(select(ScoreResultRow).where(ScoreResultRow.run_id == run.id)).result


# ───────────── 端到端 ─────────────


def test_end_to_end_short_video(login, seeded, video_file, db):
    rec = _submit(login("hr"), seeded, video_file)
    assert rec.status == "done", rec.failure_reason
    runs = _runs(db, rec)
    assert all(r.status == "completed" and r.retry_count == 0 for r in runs)
    dets = db.scalars(select(DetectorRun).where(DetectorRun.run_id == runs[0].id)).all()
    assert {d.detector_id for d in dets} >= {"P1", "P2", "S2", "S3", "O5", "redlines"} and all(d.status == "completed" for d in dets)
    rep = _report(db, rec)
    assert rep.informal is True  # 演示用的评分标准、红线词表、检测配置都是草稿
    assert rep.label in ("recommend", "pending", "not_recommend") and rep.verdict["reason"]
    assert rec.processing_started_at and rec.finished_at
    assert db.scalar(select(AuditLog).where(AuditLog.action == "report_create", AuditLog.target_id == str(rec.id)))


def test_full_length_critical_three_rounds_and_traceability(login, seeded, full_video, db):
    """P0：临界样本自动重跑 3 次、报告标“临界”；报告的标准版本、模型版本完整；转写保留口头禅（关闭顺滑）。"""
    rec = _submit(login("hr"), seeded, full_video, seg=FULL_SEG)
    assert rec.status == "done", rec.failure_reason
    runs = _runs(db, rec)
    first = _result(db, runs[0])
    assert first["critical"] is True  # 标准剧本总档位 13，落在新主播试播的临界区间 13–16
    assert [r.round_no for r in runs] == [1, 2, 3]
    rep = _report(db, rec)
    assert rep.critical is True and rep.label == "pending" and len(rep.verdict["rounds"]) == 3
    assert db.scalar(select(AuditLog).where(AuditLog.action == "critical_rerun", AuditLog.target_id == str(rec.id)))
    # 可追溯
    m = rep.model_manifest
    assert m["asr"] == "mock-asr@1" and m["llm"] == "mock-llm@1" and m["temperature"] == "0" and m["asr_disfluency_removal"] == "false"
    assert m["prompts"].startswith("prompts-v1:") and m["detector_config"] == "detectors-v1"
    assert rep.config_hash.startswith("sha256:") and rep.rubric_version_id and rep.detector_config_version_id
    # 口头禅保留：转写里有“那么”“一个”，P2 证据逐条记了原句和时间
    tr = db.scalar(select(Transcript).where(Transcript.run_id == runs[0].id, Transcript.segment == "main"))
    assert tr.disfluency_removal is False and "那么" in tr.text and "一个" in tr.text
    p2 = db.scalars(select(EvidenceRow).where(EvidenceRow.run_id == runs[0].id, EvidenceRow.item_id == "P2")).all()
    assert any(e.label == "那么" and e.judgment == "count" for e in p2)
    assert all(e.start_ms is not None and e.quote for e in p2)


def test_objection_times_align_with_evidence(login, seeded, full_video, db):
    """P0（按 C29 改写）：题单异议时间点 → 视频时间；S3 证据时间戳都在对应异议弹出之后、主体段之内。"""
    rec = _submit(login("hr"), seeded, full_video, seg=FULL_SEG)
    run = _runs(db, rec)[0]
    main = next(s for s in rec.segments if s["segment"] == "main")
    at = {o["objection_id"]: o["video_ms"] for o in rec.objection_times}
    assert sorted(at.values()) == [5000 + x for x in FULL_SEG["objection_offsets_ms"]]
    s3 = db.scalars(select(EvidenceRow).where(EvidenceRow.run_id == run.id, EvidenceRow.item_id == "S3")).all()
    assert {e.ref for e in s3} == set(at)
    for e in s3:
        assert e.start_ms is not None and at[e.ref] <= e.start_ms < main["end_ms"], (e.ref, e.start_ms, at[e.ref])
    o4 = {e.label: e.value for e in db.scalars(select(EvidenceRow).where(EvidenceRow.run_id == run.id, EvidenceRow.item_id == "O4"))}
    assert 0 < o4["max_response_latency_s"] < 5  # Mock 在弹出后 1.5 秒开始回应


def test_rounds_can_disagree_majority_decides(login, seeded, full_video, db):
    """第 2 轮大模型给出不同判断（模拟识别或判断的随机误差）：三轮取多数，展示中位数所在轮。"""
    llm = MockLLM(round_overrides={(2, "s1_need"): {"level": 0, "quote": "", "reason": "（模拟）未识别到激发需求", "confidence": 0.6}})
    set_providers(_providers(llm=llm))
    rec = _submit(login("hr"), seeded, full_video, seg=FULL_SEG)
    rep = _report(db, rec)
    totals = [r["total_grade"] for r in rep.verdict["rounds"]]
    assert totals[0] == totals[2] == 13 and totals[1] > 13
    assert rep.verdict["majority_grade_pass"] is True and rep.label == "pending"
    assert rep.display_run_id == _runs(db, rec)[0].id


def test_first_round_redline_no_extra_rounds(login, seeded, full_video, db):
    """C17：首轮命中红线的临界样本不追加轮次；红线原句写进报告。"""
    set_providers(_providers(asr=MockASR("redline")))
    rec = _submit(login("hr"), seeded, full_video, seg=FULL_SEG)
    runs = _runs(db, rec)
    rep = _report(db, rec)
    assert len(runs) == 1 and rep.redline_hit and rep.label == "not_recommend" and rep.conclusion == "fail"
    quotes = [h[1]["quote"] for h in rep.verdict["redline_hits"]]
    assert any("稳赚不赔" in q for q in quotes) and any("加我微信" in q for q in quotes)


# ───────────── 重试与失败（M4-4） ─────────────


def test_transient_call_failures_retried_in_place(login, seeded, video_file, db):
    """单次调用失败先就地重试（再试 2 次），不需要整轮重来。"""
    set_providers(_providers(speech_eval=MockSpeechEval(faults=Faults(fail_times=2))))
    rec = _submit(login("hr"), seeded, video_file)
    assert rec.status == "done" and _runs(db, rec)[0].retry_count == 0


def test_round_retried_not_new_round(login, seeded, video_file, db):
    """一次尝试里同一调用连续失败 3 次 → 整轮重试；重试不算新的投票轮次（C5）。"""
    set_providers(_providers(speech_eval=MockSpeechEval(faults=Faults(fail_times=4))))
    rec = _submit(login("hr"), seeded, video_file)
    runs = _runs(db, rec)
    assert rec.status == "done" and runs[0].retry_count == 1 and runs[0].status == "completed"
    assert [r.round_no for r in runs] == sorted({r.round_no for r in runs})
    assert db.scalars(select(Notification)).all() == []


def test_final_failure_notifies_and_can_reprocess(login, seeded, video_file, db):
    set_providers(_providers(speech_eval=MockSpeechEval(faults=Faults(fail_times=99))))
    hr = login("hr")
    rec = _submit(hr, seeded, video_file)
    assert rec.status == "failed" and "已自动重试 2 次" in rec.failure_reason
    notes = {n.template: n for n in db.scalars(select(Notification))}
    assert notes["processing_failed_rerecord"].audience == "candidate" and notes["processing_failed_rerecord"].channel == "mock"
    assert notes["processing_failed_alert"].audience == "admin" and notes["processing_failed_alert"].status == "sent"
    assert db.scalar(select(AuditLog).where(AuditLog.action == "processing_failed"))
    det = {d.detector_id: d for d in db.scalars(select(DetectorRun).where(DetectorRun.run_id == _runs(db, rec)[0].id))}
    assert det["P3"].status == "failed" and "模拟供应商错误" in det["P3"].error
    set_providers(_providers())
    r = hr.post(f"/api/recordings/{rec.id}/reprocess")
    assert r.status_code == 200 and r.json()["status"] == "done"


def test_detector_failure_is_missing_evidence_not_zero(login, seeded, video_file, db):
    """C16：检测失败不能当作“没有扣分事件”。小动作检测一直失败 → P8 缺失证据、不出分，整条处理失败。"""

    class FlakyVision(MockVision):
        def analyze(self, task, frames, context):
            if task == "fidget":
                raise ProviderError("视觉服务不可用")
            return super().analyze(task, frames, context)

    set_providers(_providers(vision=FlakyVision()))
    rec = _submit(login("hr"), seeded, video_file)
    assert rec.status == "failed" and "P8" in rec.failure_reason
    res = _result(db, _runs(db, rec)[0])
    p8 = next(i for i in res["items"] if i["item_id"] == "P8")
    assert p8["status"] == "missing_evidence" and p8["score"] is None
    assert res["status"] == "incomplete" and res["total_grade"] is None
    assert _report(db, rec) is None


def test_asr_must_keep_disfluencies(login, seeded, video_file, db):
    class SmoothingASR(MockASR):
        def transcribe(self, audio_path, *, disfluency_removal, word_timestamps, hint):
            r = super().transcribe(audio_path, disfluency_removal=disfluency_removal, word_timestamps=word_timestamps, hint=hint)
            r.params = {"disfluency_removal": True}  # 供应商擅自开了顺滑
            return r

    set_providers(_providers(asr=SmoothingASR()))
    rec = _submit(login("hr"), seeded, video_file)
    assert rec.status == "failed" and "顺滑" in rec.failure_reason
    with pytest.raises(ProviderError):
        MockASR().transcribe("x.wav", disfluency_removal=True, word_timestamps=True, hint=None)


def test_llm_called_with_temperature_zero():
    from app.pipeline import llm

    seen = []

    class Spy(MockLLM):
        def complete_json(self, task, system, user, schema, *, temperature, payload):
            seen.append(temperature)
            return super().complete_json(task, system, user, schema, temperature=temperature, payload=payload)

    out = llm.ask(Spy(), "o5_answer", {"question": "什么是等待期？", "full_points": ["合同生效后"], "answer": "合同生效后的一段时间"})
    assert seen == [0.0] and out["level"] in ("full", "partial", "zero")
    with pytest.raises(ProviderError):
        MockLLM().complete_json("o5_answer", "", "", {}, temperature=0.3, payload={})


# ───────────── 到期删除（P0：到期视频自动删除，报告保留） ─────────────


def test_retention_purge_keeps_reports(login, seeded, video_file, db):
    from app.services.retention import purge_expired
    from app.services.storage import get_storage

    hr = login("hr")
    rec = _submit(hr, seeded, video_file)
    assert rec.status == "done"
    hr.post(f"/api/candidates/{rec.candidate_id}/consents", data={"consent_text_version": "v2", "signed_on": "2026-11-01"},
            files={"attachment": ("c.pdf", b"%PDF", "application/pdf")})
    media = db.scalars(select(MediaAsset).where(MediaAsset.recording_id == rec.id)).all()
    assert {m.kind for m in media} == {"raw_video", "audio", "frame"}
    later = datetime.now(timezone.utc) + timedelta(days=31)
    out = purge_expired(db, get_storage(), now=later)
    assert out["deleted"] == len(media)
    db.expire_all()
    assert all(m.deleted_at is not None for m in db.scalars(select(MediaAsset).where(MediaAsset.recording_id == rec.id)))
    assert hr.get(f"/api/media/{media[0].id}").status_code == 410
    assert _report(db, rec) is not None  # 报告保留
    assert db.scalars(select(EvidenceRow)).first() is not None  # 文字证据保留
    scan = db.scalar(select(MediaAsset).where(MediaAsset.kind == "consent_scan"))
    assert scan.deleted_at is None  # 授权书扫描件不随视频删除（P-CONSENT-KEEP）
    assert db.scalar(select(AuditLog).where(AuditLog.action == "media_purge"))


def test_retention_keeps_hired_and_unexpired(login, seeded, video_file, db):
    from app.services.retention import purge_expired
    from app.services.storage import get_storage

    hr = login("hr")
    rec = _submit(hr, seeded, video_file)
    assert purge_expired(db, get_storage())["deleted"] == 0  # 未到期
    db.get(Candidate, rec.candidate_id).hiring_status = "hired"
    db.commit()
    out = purge_expired(db, get_storage(), now=datetime.now(timezone.utc) + timedelta(days=31))
    assert out["deleted"] == 0 and out["kept_hired"] > 0


def test_stale_uploads_aborted(login, seeded, video_file, db):
    from app.services.retention import purge_expired
    from app.services.storage import get_storage
    from test_recordings_api import _create

    rec = _create(login("hr"), seeded, video_file).json()
    out = purge_expired(db, get_storage(), now=datetime.now(timezone.utc) + timedelta(days=8))
    assert out["aborted_uploads"] == 1
    db.expire_all()
    assert db.get(UploadSession, rec["upload"]["id"]).status == "aborted"


def test_rq_queue_mode(login, seeded, video_file, db, monkeypatch):
    """队列模式：提交只入队立即返回，由 worker 处理（这里用不 fork 的 SimpleWorker 在本进程跑完）。"""
    import dataclasses

    from redis import Redis
    from redis.exceptions import ConnectionError as RedisDown
    from rq import Queue, SimpleWorker

    from app.pipeline import orchestrator
    from app.settings import get_settings

    url = "redis://localhost:6379/6"
    try:
        Redis.from_url(url).flushdb()
    except RedisDown:
        pytest.skip("本机没有 Redis")
    s = dataclasses.replace(get_settings(), queue="rq", redis_url=url)
    monkeypatch.setattr(orchestrator, "get_settings", lambda: s)
    hr = login("hr")
    rec = _uploaded(hr, seeded, video_file)
    hr.put(f"/api/recordings/{rec['id']}/segments", json=SEG)
    r = hr.post(f"/api/recordings/{rec['id']}/submit")
    assert r.status_code == 200 and r.json()["status"] == "submitted"  # 还没处理
    conn = Redis.from_url(url)
    assert Queue(orchestrator.QUEUE_NAME, connection=conn).count == 1
    SimpleWorker([Queue(orchestrator.QUEUE_NAME, connection=conn)], connection=conn).work(burst=True)
    db.expire_all()
    assert db.get(Recording, rec["id"]).status == "done"
