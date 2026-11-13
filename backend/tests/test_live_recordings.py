"""录播评估（C37）：老主播、上播 1 个月的主播没有题单，上传直播录播，整段视频评分。
不截取 10 分钟（C36）；观众异议从逐字稿自动识别（也可以由员工标出）、按实际条数折算；副播插话等时段排除后不参与评分。"""
import pytest
from sqlalchemy import select

from app.models.entities import AuditionSheet, EvidenceRow, Objection, PipelineRun, Product, ProductCard, Recording, Report, RubricVersion, ScoreResultRow
from app.providers import mock
from app.providers.base import Providers
from app.providers.registry import set_providers
from test_recordings_api import SEG, _candidate, _consent, _send_parts


@pytest.fixture(autouse=True)
def _reset_providers():
    yield
    set_providers(None)


def _create_live(api, db, video, *, audience="veteran", props=False, **extra):
    cand = _candidate(api)
    consent = _consent(api, cand["id"])
    body = {"mode": "live", "candidate_id": cand["id"], "product_id": str(db.scalar(select(Product.id))), "consent_record_id": consent["id"], "audience": audience,
            "props_available": props, "filename": video.name, "content_type": "video/mp4", "size_bytes": video.stat().st_size, **extra}
    return api.post("/api/recordings", json=body)


def _uploaded_live(api, db, video, **kw) -> dict:
    r = _create_live(api, db, video, **kw)
    assert r.status_code == 201, r.text
    rec = r.json()
    _send_parts(api, rec["upload"], video.read_bytes())
    r = api.post(f"/api/uploads/{rec['upload']['id']}/complete")
    assert r.status_code == 200, r.text
    return r.json()


def _texts(db, n):
    return [o.text for o in db.scalars(select(Objection).limit(n))]


def _result(db, rec_id) -> dict:
    run = db.scalar(select(PipelineRun).where(PipelineRun.recording_id == rec_id, PipelineRun.round_no == 1))
    return db.scalar(select(ScoreResultRow).where(ScoreResultRow.run_id == run.id)).result


def _item(result, item_id):
    return next(i for i in result["items"] if i["item_id"] == item_id)


def _finish(api, db, rec_id):
    """评委把等待中的条目都打满分，直到出报告。"""
    for _ in range(4):
        db.expire_all()
        rec = db.get(Recording, rec_id)
        if rec.status != "awaiting_human":
            return rec
        items = api.get(f"/api/recordings/{rec_id}/human-review").json()["items"]
        r = api.put(f"/api/recordings/{rec_id}/human-scores", json={"scores": {i["item_id"]: {"score": i["max"]} for i in items}})
        assert r.status_code == 200, r.text
    db.expire_all()
    return db.get(Recording, rec_id)


# ───────────── 登记 ─────────────


def test_live_recording_needs_no_sheet(login, seeded, video_file, db):
    api = login("hr")
    r = _create_live(api, seeded, video_file)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["mode"] == "live" and out["sheet_code"].startswith("LB") and out["audience"] == "veteran"
    assert out["sheet_objections"] == [] and out["exclusions"] == []
    internal = db.get(AuditionSheet, out["sheet_id"])
    assert internal.kind == "live" and internal.reading_script_id is None and internal.status == "used"
    # 内部记录不是题单：不出现在题单列表，也不能按题单打开或作废
    admin = login("admin")
    assert all(s["id"] != out["sheet_id"] for s in admin.get("/api/sheets").json())
    assert admin.get(f"/api/sheets/{out['sheet_id']}").status_code == 404
    assert admin.post(f"/api/sheets/{out['sheet_id']}/void").status_code == 404
    # 取消后内部记录作废
    assert api.post(f"/api/recordings/{out['id']}/cancel").status_code == 200
    db.expire_all()
    assert db.get(AuditionSheet, out["sheet_id"]).status == "void"


def test_mode_decides_required_fields(login, seeded, video_file, db):
    api = login("hr")
    r = _create_live(api, seeded, video_file, product_id=None)
    assert r.status_code == 422 and "须选择产品" in r.text
    r = _create_live(api, seeded, video_file, sheet_id=str(db.scalar(select(RubricVersion.id))))
    assert r.status_code == 422
    r = _create_live(api, seeded, video_file, mode="audition")  # 试镜必须有题单
    assert r.status_code == 422 and "题单" in r.text
    r = _create_live(api, seeded, video_file, audience="nobody")
    assert r.status_code == 422 and "达标线" in r.text
    assert db.scalar(select(AuditionSheet).where(AuditionSheet.kind == "live")) is None  # 失败的登记不留内部记录


def test_live_marks_validation(login, seeded, full_video, db):
    api = login("hr")
    rec = _uploaded_live(api, seeded, full_video)
    rid, total = rec["id"], rec["video_duration_ms"]
    assert api.put(f"/api/recordings/{rid}/segments", json=SEG).status_code == 409  # 录播没有分段
    # 上传完整段视频就是主体段，不标注也能提交；标注是可选的
    assert rec["segments"] == [{"segment": "main", "start_ms": 0, "end_ms": total}] and rec["main_duration_ms"] == total
    assert rec["objection_times"] == [] and rec["exclusions"] == []

    def put(objections=(), exclusions=()):
        return api.put(f"/api/recordings/{rid}/live-marks", json={"objections": list(objections), "exclusions": list(exclusions)})

    assert put([{"text": "能报销吗", "video_ms": total + 1}]).status_code == 422
    assert put([{"text": "a", "video_ms": 5000}, {"text": "b", "video_ms": 5000}]).status_code == 422
    assert put([{"text": "", "video_ms": 5000}]).status_code == 422
    assert put(exclusions=[{"start_ms": 9000, "end_ms": 4000}]).status_code == 422
    assert put(exclusions=[{"start_ms": 1000, "end_ms": 5000}, {"start_ms": 4000, "end_ms": 8000}]).status_code == 422
    assert put(exclusions=[{"start_ms": 0, "end_ms": total + 1}]).status_code == 422
    assert put(exclusions=[{"start_ms": 0, "end_ms": total - 1000}]).status_code == 422  # 排除后不足 1 分钟
    r = put([{"text": "后说的", "video_ms": 400000}, {"text": "先说的", "video_ms": 120000}],
            [{"start_ms": 200000, "end_ms": 260000}])
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["segments"] == [{"segment": "main", "start_ms": 0, "end_ms": total}]  # 整段视频，不截取
    assert out["main_duration_ms"] == total - 60000
    assert [o["text"] for o in out["sheet_objections"]] == ["先说的", "后说的"]
    assert [o["video_ms"] for o in out["objection_times"]] == [120000, 400000]
    assert out["exclusions"] == [{"start_ms": 200000, "end_ms": 260000}]
    assert put().status_code == 200  # 可以改，也可以都为空


def test_audition_recording_cannot_use_live_marks(login, seeded, video_file, db):
    from test_recordings_api import _uploaded

    api = login("hr")
    rec = _uploaded(api, seeded, video_file)
    assert rec["mode"] == "audition"
    assert api.put(f"/api/recordings/{rec['id']}/live-marks", json={"objections": []}).status_code == 409


# ───────────── 处理 ─────────────


def test_live_end_to_end_scores_whole_video(login, seeded, full_video, db):
    """两条真实异议：S3 按 2 条折算到 20 分；整段 17 分钟都评，P2 按每 10 分钟换算；没有朗读段，P3 由评委打分。"""
    api = login("hr")
    rec = _uploaded_live(api, seeded, full_video)
    rid, total = rec["id"], rec["video_duration_ms"]
    t1, t2 = _texts(db, 2)
    marks = {"objections": [{"text": t1, "video_ms": 300000}, {"text": t2, "video_ms": 700000}], "exclusions": []}
    assert api.put(f"/api/recordings/{rid}/live-marks", json=marks).status_code == 200
    r = api.post(f"/api/recordings/{rid}/submit")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "awaiting_human"
    pending = [i["item_id"] for i in api.get(f"/api/recordings/{rid}/human-review").json()["items"]]
    assert pending == ["P3"]
    res = _result(db, rid)
    assert res["model_manifest"]["recording_mode"] == "live" and res["model_manifest"]["human_review"]["manual"] == ["P3"]
    s3 = _item(res, "S3")
    assert s3["status"] == "scored" and any("实际 2 条" in n for n in s3["notes"])
    run = db.scalar(select(PipelineRun).where(PipelineRun.recording_id == rid))
    refs = {e.ref for e in db.scalars(select(EvidenceRow).where(EvidenceRow.run_id == run.id, EvidenceRow.item_id == "S3"))}
    assert len(refs) == 2
    assert any("超过 10 分钟" in n for n in _item(res, "P2")["notes"])
    p4 = db.scalars(select(EvidenceRow).where(EvidenceRow.run_id == run.id, EvidenceRow.item_id == "P4")).all()
    assert len(p4) == -(-total // 60000)  # 每个自然分钟一条，覆盖整段视频
    rec = _finish(api, db, rid)
    assert rec.status == "done", rec.failure_reason
    rep = db.scalar(select(Report).where(Report.recording_id == rec.id))
    d = api.get(f"/api/reports/{rep.id}").json()
    assert d["mode"] == "live" and d["audience"] == "veteran" and d["result"]["threshold"] == 8
    from app.services.export import report_html
    from app.services.report_view import detail

    h = report_html(detail(db, rep))
    assert "主播录播评分报告" in h and "无题单，整段视频评分" in h
    # 排名：录播和试镜分开
    assert [r["mode"] for r in api.get("/api/reports?mode=live").json()] == ["live"]
    assert api.get("/api/reports?mode=audition").json() == []
    assert api.get("/api/reports?mode=other").status_code == 422


def test_live_without_objections_s3_not_applicable(login, seeded, full_video, db):
    api = login("hr")
    rec = _uploaded_live(api, seeded, full_video, audience="month_1")
    rid = rec["id"]
    out = api.put(f"/api/recordings/{rid}/live-marks", json={"objections": [], "exclusions": []}).json()
    assert any("解答异议" in w for w in out["warnings"])
    assert api.post(f"/api/recordings/{rid}/submit").json()["status"] == "awaiting_human"
    pending = sorted(i["item_id"] for i in api.get(f"/api/recordings/{rid}/human-review").json()["items"])
    assert pending == ["O4", "P3"]  # 没有异议：节奏与气氛也由评委打分
    rec = _finish(api, db, rid)
    assert rec.status == "done", rec.failure_reason
    res = _result(db, rid)
    assert _item(res, "S3")["status"] == "not_applicable"
    assert next(d for d in res["dimensions"] if d["id"] == "S")["applicable_max"] == 80
    assert res["threshold"] == 10


def test_exclusions_remove_speech_from_scoring(login, seeded, full_video, db):
    """排除时段里的话不出证据；逐字稿原样保留。"""
    api = login("hr")
    rec = _uploaded_live(api, seeded, full_video)
    rid = rec["id"]
    ex = {"start_ms": 0, "end_ms": 600000}
    assert api.put(f"/api/recordings/{rid}/live-marks", json={"objections": [], "exclusions": [ex]}).status_code == 200
    assert api.post(f"/api/recordings/{rid}/submit").status_code == 200
    run = db.scalar(select(PipelineRun).where(PipelineRun.recording_id == rid))
    text_items = ("P2", "S1", "S4", "L1", "L2", "L3", "L4", "L5", "O1", "O2", "O3")
    rows = db.scalars(select(EvidenceRow).where(EvidenceRow.run_id == run.id, EvidenceRow.item_id.in_(text_items))).all()
    assert all(not (e.start_ms is not None and e.start_ms < 600000 and e.quote) for e in rows)
    from app.models.entities import Transcript

    tr = db.scalar(select(Transcript).where(Transcript.run_id == run.id, Transcript.segment == "main"))
    assert any(w[1] < 600000 for w in tr.words)


def test_live_product_without_s2_calibration_goes_to_judge(login, seeded, full_video, db):
    """试镜缺固定话术或校准记录时在提交前拦下；录播讲的产品不一定有，S2 转评委打分。"""
    card = db.scalar(select(ProductCard))
    card.content = {k: v for k, v in card.content.items() if k != "s2_calibration"}
    db.commit()
    api = login("hr")
    rec = _uploaded_live(api, seeded, full_video)
    rid = rec["id"]
    assert api.put(f"/api/recordings/{rid}/live-marks", json={"objections": [], "exclusions": []}).status_code == 200
    r = api.post(f"/api/recordings/{rid}/submit")
    assert r.status_code == 200, r.text
    pending = sorted(i["item_id"] for i in api.get(f"/api/recordings/{rid}/human-review").json()["items"])
    assert pending == ["O4", "P3", "S2"]
    assert "s2_calibration" not in _result(db, rid)["model_manifest"]


# ───────────── 不标注：观众异议从逐字稿自动识别 ─────────────


def _with_llm(overrides) -> None:
    set_providers(Providers(asr=mock.MockASR(), speech_eval=mock.MockSpeechEval(), llm=mock.MockLLM(round_overrides=overrides),
                            vision=mock.MockVision(), laugh=mock.MockLaugh(), voice=mock.MockVoice()))


def _two_answers(payload):
    """模型在逐字稿里找到两处主播回应观众的话，外加一条引用不在原文里的（要被丢掉）和一条把握不足的。"""
    sents = mock._sents(payload["transcript"])
    a, b = sents[len(sents) // 3], sents[2 * len(sents) // 3]
    return {"items": [
        {"question": "等待期多久", "quote": b, "reason": "主播念出了问题", "confidence": 0.9},
        {"question": "有医保还要买吗", "quote": a, "reason": "主播在回答观众", "confidence": 0.8},
        {"question": "编出来的问题", "quote": "逐字稿里根本没有这句话也没有类似的话", "reason": "", "confidence": 0.9},
        {"question": "拿不准的", "quote": sents[1], "reason": "", "confidence": 0.2},
    ]}


def test_live_submits_without_marks_and_detects_objections_from_transcript(login, seeded, full_video, db):
    _with_llm({(1, "live_objections"): _two_answers})
    api = login("hr")
    rec = _uploaded_live(api, seeded, full_video)
    rid = rec["id"]
    r = api.post(f"/api/recordings/{rid}/submit")  # 没有调用过 live-marks
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "awaiting_human"
    assert [o["text"] for o in out["sheet_objections"]] == ["有医保还要买吗", "等待期多久"]  # 按时间排序，定位不到和把握不足的不要
    assert all(o["source"] == "auto" for o in out["objection_times"]) and len(out["objection_times"]) == 2
    res = _result(db, rid)
    assert res["model_manifest"]["live_objections"] == "auto:2"
    s3 = _item(res, "S3")
    assert s3["status"] == "scored" and any("实际 2 条" in n for n in s3["notes"])
    pending = [i["item_id"] for i in api.get(f"/api/recordings/{rid}/human-review").json()["items"]]
    assert pending == ["P3"]  # 识别到了异议，节奏与气氛由机器评
    run = db.scalar(select(PipelineRun).where(PipelineRun.recording_id == rid))
    o4 = db.scalar(select(EvidenceRow).where(EvidenceRow.run_id == run.id, EvidenceRow.item_id == "O4"))
    assert "自动识别" in o4.reason and "未回应 0 条" not in o4.reason  # 回应时长、未回应条数没有测量，不写成 0
    assert _finish(api, db, rid).status == "done"


def test_live_without_marks_and_nothing_detected_is_like_no_objections(login, seeded, full_video, db):
    api = login("hr")
    rec = _uploaded_live(api, seeded, full_video)
    rid = rec["id"]
    assert any("自动识别" in w for w in rec["warnings"])
    assert api.post(f"/api/recordings/{rid}/submit").json()["status"] == "awaiting_human"
    res = _result(db, rid)
    assert res["model_manifest"]["live_objections"] == "none:0"
    assert _item(res, "S3")["status"] == "not_applicable"
    assert sorted(i["item_id"] for i in api.get(f"/api/recordings/{rid}/human-review").json()["items"]) == ["O4", "P3"]


def test_detection_failure_does_not_fail_the_recording(login, seeded, full_video, db):
    def boom(payload):
        raise mock.ProviderError("模型服务不可用")

    _with_llm({(1, "live_objections"): boom})
    api = login("hr")
    rid = _uploaded_live(api, seeded, full_video)["id"]
    assert api.post(f"/api/recordings/{rid}/submit").json()["status"] == "awaiting_human"
    assert _item(_result(db, rid), "S3")["status"] == "not_applicable"


def test_manual_marks_take_precedence_over_detection(login, seeded, full_video, db):
    _with_llm({(1, "live_objections"): _two_answers})
    api = login("hr")
    rid = _uploaded_live(api, seeded, full_video)["id"]
    (t1,) = _texts(db, 1)
    assert api.put(f"/api/recordings/{rid}/live-marks", json={"objections": [{"text": t1, "video_ms": 300000}], "exclusions": []}).status_code == 200
    out = api.post(f"/api/recordings/{rid}/submit").json()
    assert [o["text"] for o in out["sheet_objections"]] == [t1] and "source" not in out["objection_times"][0]
    assert _result(db, rid)["model_manifest"]["live_objections"] == "manual:1"


def test_reprocess_detects_again(login, seeded, full_video, db):
    _with_llm({(1, "live_objections"): _two_answers})
    api = login("hr")
    rid = _uploaded_live(api, seeded, full_video)["id"]
    assert api.post(f"/api/recordings/{rid}/submit").status_code == 200
    rec = db.get(Recording, rid)
    first = [o["objection_id"] for o in rec.objection_times]
    rec.status = "failed"
    db.commit()
    assert api.post(f"/api/recordings/{rid}/reprocess").status_code == 200
    db.expire_all()
    again = [o["objection_id"] for o in db.get(Recording, rid).objection_times]
    assert len(again) == 2 and set(again).isdisjoint(first)  # 清掉重新识别，不是沿用上次的
