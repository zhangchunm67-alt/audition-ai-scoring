"""候选人、授权登记、录像上传（分片与断点续传）、分段标注、提交、媒体读取与审计（里程碑 3）。"""
import hashlib
import math
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.models.entities import (
    AuditLog, AuditionSheet, Candidate, MediaAsset, Objection, Product, ProductCard, Question, ReadingScript, Recording,
    RedlineLexiconVersion, RubricVersion,
)


# ───────────── 工具 ─────────────


def _sheet(_api, db) -> dict:
    """直接在库里建一张题单（HR 无权生成题单；抽题逻辑在 test_sheets_api.py 里测）。"""
    import uuid

    objs = db.scalars(select(Objection).limit(4)).all()
    qs = db.scalars(select(Question).limit(6)).all()
    s = AuditionSheet(
        code=f"TS-TEST-{uuid.uuid4().hex[:6]}", product_id=db.scalar(select(Product.id)), product_card_id=db.scalar(select(ProductCard.id)),
        rubric_version_id=db.scalar(select(RubricVersion.id)), redline_lexicon_version_id=db.scalar(select(RedlineLexiconVersion.id)),
        draw_rule_snapshot={"main_seconds": 600, "question_seconds": 60, "prep_seconds": 900},
        objections=[{"objection_id": str(o.id), "text": o.text, "at_ms": t} for o, t in zip(objs, [240000, 330000, 420000, 480000])],
        questions=[{"question_id": str(q.id), "text": q.text} for q in qs],
        reading_script_id=db.scalar(select(ReadingScript.id)), reading_text="x", recording_rules_version="rules-v1", uses_draft_config=True,
    )
    db.add(s)
    db.commit()
    return {"id": str(s.id), "code": s.code}


def _candidate(api, name="张三", phone="13800001234") -> dict:
    r = api.post("/api/candidates", json={"name": name, "phone": phone})
    assert r.status_code == 201, r.text
    return r.json()


def _consent(api, cid, **kw) -> dict:
    data = {"consent_text_version": "consent-v1", "signed_on": date.today().isoformat(), **kw}
    r = api.post(f"/api/candidates/{cid}/consents", data=data)
    assert r.status_code == 201, r.text
    return r.json()


def _create(api, db, video, *, audience="new_trial", props=True, cand=None, consent=None, sheet=None):
    cand = cand or _candidate(api)
    consent = consent or _consent(api, cand["id"])
    sheet = sheet or _sheet(api, db)
    body = {"candidate_id": cand["id"], "sheet_id": sheet["id"], "consent_record_id": consent["id"], "audience": audience,
            "props_available": props, "filename": video.name, "content_type": "video/mp4", "size_bytes": video.stat().st_size}
    return api.post("/api/recordings", json=body)


def _send_parts(api, up, data: bytes, only=None):
    for n in range(1, up["part_count"] + 1):
        if only is not None and n not in only:
            continue
        chunk = data[(n - 1) * up["part_size"]: n * up["part_size"]]
        r = api.put(f"/api/uploads/{up['id']}/parts/{n}", content=chunk,
                    headers={"Content-Type": "application/octet-stream", "X-Content-SHA256": hashlib.sha256(chunk).hexdigest()})
        assert r.status_code == 200, r.text
    return api.get(f"/api/uploads/{up['id']}").json()


def _uploaded(api, db, video, **kw):
    rec = _create(api, db, video, **kw).json()
    _send_parts(api, rec["upload"], video.read_bytes())
    r = api.post(f"/api/uploads/{rec['upload']['id']}/complete")
    assert r.status_code == 200, r.text
    return r.json()


SEG = {"main_start_ms": 1000, "question_starts_ms": [9000, 10000, 11000, 12000, 13000, 14000], "reading_start_ms": 16000,
       "objection_offsets_ms": [2000, 3500, 5000, 6000]}


# ───────────── 候选人与授权 ─────────────


def test_candidate_pii_encrypted_at_rest(login, db):
    api = login("hr")
    c = _candidate(api, "李四", "13912345678")
    assert c["name"] == "李四" and c["phone_masked"] == "139****5678"
    row = db.get(Candidate, c["id"])
    assert "李四".encode() not in row.name_enc and b"13912345678" not in row.phone_enc
    assert api.get("/api/candidates?phone=139 1234 5678").json()[0]["id"] == c["id"]
    detail = api.get(f"/api/candidates/{c['id']}").json()
    assert detail["phone"] == "13912345678"
    assert db.scalar(select(AuditLog).where(AuditLog.action == "candidate_view", AuditLog.target_id == c["id"]))


def test_consent_registration_and_scan(login, db):
    api = login("hr")
    c = _candidate(api)
    r = api.post(f"/api/candidates/{c['id']}/consents", data={"consent_text_version": "consent-v1", "signed_on": date.today().isoformat()},
                 files={"attachment": ("同意书.pdf", b"%PDF-1.4 fake", "application/pdf")})
    assert r.status_code == 201 and r.json()["attachment_asset_id"]
    asset = db.get(MediaAsset, r.json()["attachment_asset_id"])
    assert asset.kind == "consent_scan" and asset.candidate_id is not None and asset.recording_id is None
    got = api.get(f"/api/media/{asset.id}")
    assert got.status_code == 200 and got.content == b"%PDF-1.4 fake"
    bad = api.post(f"/api/candidates/{c['id']}/consents", data={"consent_text_version": "v", "signed_on": date.today().isoformat()},
                   files={"attachment": ("a.exe", b"MZ", "application/octet-stream")})
    assert bad.status_code == 422
    future = (date.today() + timedelta(days=1)).isoformat()
    assert api.post(f"/api/candidates/{c['id']}/consents", data={"consent_text_version": "v", "signed_on": future}).status_code == 422


def test_hiring_status(login):
    api = login("hr")
    c = _candidate(api)
    assert api.patch(f"/api/candidates/{c['id']}/hiring", json={"hiring_status": "hired"}).json()["hiring_status"] == "hired"
    assert api.patch(f"/api/candidates/{c['id']}/hiring", json={"hiring_status": "maybe"}).status_code == 422


# ───────────── 上传前置条件（C26、C27、C30） ─────────────


def test_no_consent_no_upload(login, seeded, video_file):
    """P0 验收（按 C30 改写）：未登记候选人书面同意，不能上传和处理。"""
    api = login("hr")
    a, b = _candidate(api, "甲"), _candidate(api, "乙", "13800009999")
    consent_b = _consent(api, b["id"])
    r = _create(api, seeded, video_file, cand=a, consent=consent_b)  # 拿别人的授权也不行
    assert r.status_code == 422 and "书面同意" in r.json()["detail"]
    body = {"candidate_id": a["id"], "sheet_id": _sheet(None, seeded)["id"], "audience": "new_trial",
            "props_available": True, "filename": "x.mp4", "content_type": "video/mp4", "size_bytes": 10}
    assert api.post("/api/recordings", json=body).status_code == 422  # 缺授权字段


def test_audience_and_props_required(login, seeded, video_file):
    hr = login("hr")
    sheet = _sheet(None, seeded)
    cand = _candidate(hr)
    consent = _consent(hr, cand["id"])
    base = {"candidate_id": cand["id"], "sheet_id": sheet["id"], "consent_record_id": consent["id"],
            "filename": "a.mp4", "content_type": "video/mp4", "size_bytes": 100}
    assert hr.post("/api/recordings", json={**base, "props_available": True}).status_code == 422  # 没选达标线
    assert hr.post("/api/recordings", json={**base, "audience": "new_trial"}).status_code == 422  # 没选有无道具
    r = hr.post("/api/recordings", json={**base, "audience": "intern", "props_available": True})
    assert r.status_code == 422 and "达标线" in r.json()["detail"]
    r = hr.post("/api/recordings", json={**base, "audience": "veteran", "props_available": False})
    assert r.status_code == 201 and (r.json()["audience"], r.json()["props_available"]) == ("veteran", False)


def test_sheet_used_once_and_released_on_cancel(login, seeded, video_file):
    hr = login("hr")
    sheet = _sheet(None, seeded)
    rec = _create(hr, seeded, video_file, sheet=sheet).json()
    assert seeded.get(AuditionSheet, sheet["id"]).status == "used"
    assert _create(hr, seeded, video_file, sheet=sheet).status_code == 409
    assert hr.post(f"/api/recordings/{rec['id']}/cancel").json()["status"] == "cancelled"
    seeded.expire_all()
    assert seeded.get(AuditionSheet, sheet["id"]).status == "issued"
    assert _create(hr, seeded, video_file, sheet=sheet).status_code == 201


def test_rejects_non_video_extension(login, seeded, video_file):
    hr = login("hr")
    cand = _candidate(hr)
    body = {"candidate_id": cand["id"], "sheet_id": _sheet(None, seeded)["id"], "consent_record_id": _consent(hr, cand["id"])["id"],
            "audience": "new_trial", "props_available": True, "filename": "a.exe", "content_type": "video/mp4", "size_bytes": 100}
    assert hr.post("/api/recordings", json=body).status_code == 422


# ───────────── 分片上传与断点续传 ─────────────


def test_multipart_upload_with_resume(login, seeded, video_file):
    hr = login("hr")
    data = video_file.read_bytes()
    rec = _create(hr, seeded, video_file).json()
    up = rec["upload"]
    assert up["part_count"] == math.ceil(len(data) / up["part_size"]) and up["part_count"] > 2
    # 先传奇数片，模拟中途断网
    st = _send_parts(hr, up, data, only=set(range(1, up["part_count"] + 1, 2)))
    assert st["received_parts"] == list(range(1, up["part_count"] + 1, 2))
    r = hr.post(f"/api/uploads/{up['id']}/complete")
    assert r.status_code == 422 and "还缺" in r.json()["detail"]
    # 续传：只补缺的
    missing = set(range(1, up["part_count"] + 1)) - set(st["received_parts"])
    st = _send_parts(hr, up, data, only=missing)
    assert st["received_bytes"] == len(data)
    _send_parts(hr, up, data, only={1})  # 重复上传同一片是幂等的
    done = hr.post(f"/api/uploads/{up['id']}/complete").json()
    assert done["status"] == "uploaded" and 19000 <= done["video_duration_ms"] <= 21000
    asset = seeded.get(MediaAsset, done["video_asset_id"])
    assert asset.kind == "raw_video" and asset.retention_until is not None and asset.size_bytes == len(data)
    assert hr.get(f"/api/media/{asset.id}").content == data  # 拼接后与原文件一致


def test_part_validation(login, seeded, video_file):
    hr = login("hr")
    up = _create(hr, seeded, video_file).json()["upload"]
    assert hr.put(f"/api/uploads/{up['id']}/parts/1", content=b"short").status_code == 422
    assert hr.put(f"/api/uploads/{up['id']}/parts/999", content=b"x").status_code == 422
    chunk = video_file.read_bytes()[: up["part_size"]]
    r = hr.put(f"/api/uploads/{up['id']}/parts/1", content=chunk, headers={"X-Content-SHA256": "0" * 64})
    assert r.status_code == 422 and "校验" in r.json()["detail"]


def test_file_without_audio_rejected(login, seeded, silent_video):
    hr = login("hr")
    rec = _create(hr, seeded, silent_video).json()
    _send_parts(hr, rec["upload"], silent_video.read_bytes())
    r = hr.post(f"/api/uploads/{rec['upload']['id']}/complete")
    assert r.status_code == 422 and "声音" in r.json()["detail"]
    assert hr.get(f"/api/recordings/{rec['id']}").json()["status"] == "uploading"


def test_garbage_file_rejected(login, seeded, media_dir):
    fake = media_dir / "fake.mp4"
    fake.write_bytes(b"not a video" * 1000)
    hr = login("hr")
    rec = _create(hr, seeded, fake).json()
    _send_parts(hr, rec["upload"], fake.read_bytes())
    assert hr.post(f"/api/uploads/{rec['upload']['id']}/complete").status_code == 422


def test_replace_video_resets_segments(login, seeded, video_file):
    hr = login("hr")
    rec = _uploaded(hr, seeded, video_file)
    hr.put(f"/api/recordings/{rec['id']}/segments", json=SEG)
    old = rec["video_asset_id"]
    r = hr.post(f"/api/recordings/{rec['id']}/uploads", json={"filename": "b.mp4", "content_type": "video/mp4", "size_bytes": video_file.stat().st_size})
    assert r.status_code == 201 and r.json()["status"] == "uploading" and r.json()["segments"] == []
    assert hr.get(f"/api/media/{old}").status_code == 410


# ───────────── 分段与异议时间（C28、C29） ─────────────


def test_segments_and_objection_alignment(login, seeded, video_file):
    hr = login("hr")
    rec = _uploaded(hr, seeded, video_file)
    r = hr.put(f"/api/recordings/{rec['id']}/segments", json=SEG)
    assert r.status_code == 200, r.text
    out = r.json()
    segs = out["segments"]
    assert [s["segment"] for s in segs][0] == "main" and segs[-1]["segment"] == "reading"
    assert [s["segment"] for s in segs[1:-1]] == [f"question:{q['question_id']}" for q in out["sheet_questions"]]
    assert all(a["end_ms"] == b["start_ms"] for a, b in zip(segs, segs[1:]))
    assert segs[-1]["end_ms"] == out["video_duration_ms"]
    assert out["main_duration_ms"] == 8000
    # 异议时间：相对主体段 + 主体段起点 = 视频时间（证据时间戳以视频时间为准）
    for o, sheet_o, off in zip(out["objection_times"], out["sheet_objections"], SEG["objection_offsets_ms"]):
        assert o["objection_id"] == sheet_o["objection_id"] and o["at_ms"] == off and o["video_ms"] == 1000 + off
        assert o["sheet_at_ms"] == sheet_o["at_ms"]
    assert any("主体段时长" in w for w in out["warnings"])  # 测试视频远短于 10 分钟


@pytest.mark.parametrize("patch,msg", [
    ({"question_starts_ms": [9000, 10000]}, "全部"),
    ({"objection_offsets_ms": [1, 2]}, "全部"),
    ({"question_starts_ms": [9000, 8000, 11000, 12000, 13000, 14000]}, "递增"),
    ({"main_start_ms": 9500}, "递增"),
    ({"reading_start_ms": 60000}, "超出"),
    ({"objection_offsets_ms": [2000, 3500, 5000, 9000]}, "主体段内"),
    ({"objection_offsets_ms": [3500, 2000, 5000, 6000]}, "递增"),
])
def test_segment_validation(login, seeded, video_file, patch, msg):
    hr = login("hr")
    rec = _uploaded(hr, seeded, video_file)
    r = hr.put(f"/api/recordings/{rec['id']}/segments", json={**SEG, **patch})
    assert r.status_code == 422 and msg in r.json()["detail"], r.text


def test_submit_requires_segments_then_locks(login, seeded, video_file):
    hr = login("hr")
    rec = _uploaded(hr, seeded, video_file)
    assert hr.post(f"/api/recordings/{rec['id']}/submit").status_code == 422
    hr.put(f"/api/recordings/{rec['id']}/segments", json=SEG)
    r = hr.post(f"/api/recordings/{rec['id']}/submit")
    assert r.status_code == 200 and r.json()["status"] in ("submitted", "processing", "done") and r.json()["submitted_at"]
    assert hr.put(f"/api/recordings/{rec['id']}/segments", json=SEG).status_code == 409
    assert hr.post(f"/api/recordings/{rec['id']}/cancel").status_code == 409


def test_cannot_mark_segments_before_upload_completes(login, seeded, video_file):
    hr = login("hr")
    rec = _create(hr, seeded, video_file).json()
    assert hr.put(f"/api/recordings/{rec['id']}/segments", json=SEG).status_code == 409


# ───────────── 媒体读取与审计（A1） ─────────────


def test_media_range_requests_each_audited(login, seeded, video_file, db):
    hr = login("hr")
    rec = _uploaded(hr, seeded, video_file)
    aid = rec["video_asset_id"]
    data = video_file.read_bytes()
    r = hr.get(f"/api/media/{aid}", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and r.content == data[:100] and r.headers["content-range"] == f"bytes 0-99/{len(data)}"
    r = hr.get(f"/api/media/{aid}", headers={"Range": "bytes=-50"})
    assert r.status_code == 206 and r.content == data[-50:]
    r = hr.get(f"/api/media/{aid}", headers={"Range": "bytes=100-"})
    assert r.content == data[100:]
    assert hr.get(f"/api/media/{aid}", headers={"Range": f"bytes={len(data)}-"}).status_code == 416
    reads = db.scalars(select(AuditLog).where(AuditLog.action == "media_read", AuditLog.target_id == aid)).all()
    assert [x.detail["range"] for x in reads] == [[0, 99], [len(data) - 50, len(data) - 1], [100, len(data) - 1]]
    assert all(x.actor_id and x.detail["recording_id"] == rec["id"] for x in reads)
    assert r.headers["cache-control"].startswith("no-store")


def test_media_permissions(login, seeded, video_file):
    rec = _uploaded(login("hr"), seeded, video_file)
    for role in ("compliance", "calibrator", "anchor"):
        assert login(role).get(f"/api/media/{rec['video_asset_id']}").status_code == 403, role
    assert login("admin", "adm2").get(f"/api/media/{rec['video_asset_id']}", headers={"Range": "bytes=0-9"}).status_code == 206


def test_cancel_deletes_uploaded_video(login, seeded, video_file):
    hr = login("hr")
    rec = _uploaded(hr, seeded, video_file)
    hr.post(f"/api/recordings/{rec['id']}/cancel")
    assert hr.get(f"/api/media/{rec['video_asset_id']}").status_code == 410
    seeded.expire_all()
    assert seeded.get(MediaAsset, rec["video_asset_id"]).deleted_at is not None


def test_recording_rules_and_views_audited(login, seeded, video_file, db):
    hr = login("hr")
    rec = _create(hr, seeded, video_file).json()
    hr.get(f"/api/recordings/{rec['id']}")
    assert db.scalar(select(AuditLog).where(AuditLog.action == "recording_view", AuditLog.target_id == rec["id"]))
    rules = hr.get("/api/recording-rules/rules-v1").json()
    assert rules["version"] == "rules-v1" and rules["requirements"] and rules["flow"]
    assert hr.get("/api/recording-rules/nope").status_code == 404
    assert db.get(Recording, rec["id"]).uploaded_by
