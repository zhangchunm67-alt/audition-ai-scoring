"""评委人工打分（T39）：处理停在“等待评委打分”，评委补分后出报告；能力未配置时条目自动转人工；生产环境不用 Mock。"""
import pytest
from sqlalchemy import select

from app.models.entities import PipelineRun, Recording, Report
from app.providers.base import Providers
from app.providers.mock import MockASR, MockLaugh, MockLLM, MockSpeechEval, MockVision, MockVoice
from app.providers.registry import Unavailable, production_guard, set_providers
from test_pipeline import _submit


@pytest.fixture(autouse=True)
def _reset_providers():
    yield
    set_providers(None)


def _providers(**kw) -> Providers:
    base = dict(asr=MockASR(), speech_eval=MockSpeechEval(), llm=MockLLM(), vision=MockVision(), laugh=MockLaugh(), voice=MockVoice())
    base.update(kw)
    return Providers(**base)


@pytest.mark.human_review
def test_awaiting_human_then_report(login, seeded, video_file, db):
    api = login("hr")
    rec = _submit(api, db, video_file)
    assert rec.status == "awaiting_human", rec.failure_reason
    run = db.scalar(select(PipelineRun).where(PipelineRun.recording_id == rec.id))
    assert run.status == "awaiting_human"
    assert run.model_manifest["human_review"]["manual"] == ["P3"]
    r = api.get(f"/api/recordings/{rec.id}/human-review")
    assert r.status_code == 200
    items = {i["item_id"]: i for i in r.json()["items"]}
    assert {"P3", "P5", "P6", "P7", "S1", "S2", "L1", "O4"} <= set(items)
    assert items["P3"]["suggested"] == {"1": None} and items["S2"]["suggested"]["1"] is not None
    # 分数超范围、不需要打分的条目都拒绝
    assert api.put(f"/api/recordings/{rec.id}/human-scores", json={"scores": {"P3": {"score": 99}}}).status_code == 422
    assert api.put(f"/api/recordings/{rec.id}/human-scores", json={"scores": {"L2": {"score": 5}}}).status_code == 422
    # 分两次录入：第一次只录一部分，仍在等待
    r = api.put(f"/api/recordings/{rec.id}/human-scores", json={"scores": {"P3": {"score": 9, "note": "朗读有一处方言"}}})
    assert r.status_code == 200 and r.json()["status"] == "awaiting_human"
    rest = {k: {"score": v["suggested"]["1"]} for k, v in items.items() if k != "P3"}
    r = api.put(f"/api/recordings/{rec.id}/human-scores", json={"scores": rest})
    assert r.status_code == 200, r.text
    db.expire_all()
    rec = db.get(Recording, rec.id)
    assert rec.status in ("done", "processing"), rec.failure_reason
    if rec.status == "done":
        rep = db.scalar(select(Report).where(Report.recording_id == rec.id))
        assert rep.informal  # Mock 模型出的报告一律非正式
        rep_json = api.get(f"/api/reports/{rep.id}").json()
        assert rep_json


def test_unconfigured_capability_becomes_human(login, seeded, video_file, db):
    set_providers(_providers(speech_eval=Unavailable("speech_eval")))
    api = login("hr")
    rec = _submit(api, db, video_file)
    assert rec.status == "awaiting_human", rec.failure_reason
    items = [i["item_id"] for i in api.get(f"/api/recordings/{rec.id}/human-review").json()["items"]]
    assert items == ["P3"]
    assert api.put(f"/api/recordings/{rec.id}/human-scores", json={"scores": {"P3": {"score": 10}}}).status_code == 200
    db.expire_all()
    assert db.get(Recording, rec.id).status == "done"


def test_asr_unconfigured_blocks_submit(login, seeded, video_file, db):
    set_providers(_providers(asr=Unavailable("asr")))
    api = login("hr")
    from test_recordings_api import SEG, _uploaded

    rec = _uploaded(api, db, video_file)
    assert api.put(f"/api/recordings/{rec['id']}/segments", json=SEG).status_code == 200
    r = api.post(f"/api/recordings/{rec['id']}/submit")
    assert r.status_code == 422 and "语音识别" in r.json()["detail"]


def test_production_never_uses_mock():
    p = production_guard(_providers(), {"APP_ENV": "production"})
    assert all(isinstance(getattr(p, c), Unavailable) for c in ("asr", "speech_eval", "llm", "vision", "laugh", "voice"))
    assert production_guard(_providers(), {"APP_ENV": "development"}).asr.name == "mock-asr"


def test_only_reviewers_can_score(login, seeded, video_file, db):
    api = login("hr")
    rec = _submit(api, db, video_file)
    assert login("calibrator", "cal9").get(f"/api/recordings/{rec.id}/human-review").status_code == 403
    assert api.put(f"/api/recordings/{rec.id}/human-scores", json={"scores": {"P3": {"score": 1}}}).status_code == 409  # 已出报告
