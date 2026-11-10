"""报告（M5）：列表与排名、日期筛选、详情与逐句评分、新主播只看本人、Excel、PDF、按新版重算、审计。"""
import io
import os
from datetime import datetime, timedelta, timezone

import pytest
import yaml
from openpyxl import load_workbook
from sqlalchemy import select

from app.models.entities import AuditLog, Recording, Report
from app.services.export import PdfError, chromium_path
from conftest import PASSWORD
from test_pipeline import _submit
from tests.scoring.helpers import raw_config


def _done(api, db, video):
    rec = _submit(api, db, video)
    assert rec.status == "done", rec.failure_reason
    return rec, db.scalar(select(Report).where(Report.recording_id == rec.id))


def _actions(db, action):
    return db.scalars(select(AuditLog).where(AuditLog.action == action)).all()


def test_list_and_detail(login, seeded, video_file, db):
    hr = login("hr")
    rec, rep = _done(hr, seeded, video_file)
    rows = hr.get("/api/reports").json()
    assert len(rows) == 1 and rows[0]["id"] == str(rep.id) and rows[0]["rank"] == 1
    r = rows[0]
    assert r["label"] == rep.label and r["reason"] and set(r["dimension_scores"]) == {"P", "S", "L", "O"} and r["informal"] is True
    d = hr.get(f"/api/reports/{rep.id}").json()
    assert d["candidate_name"] == "张三" and d["label"] == rep.label and d["verdict"]["reason"]
    assert len(d["result"]["items"]) == 23 and len(d["result"]["dimensions"]) == 4 and d["result"]["redlines_enabled"] is False
    assert d["trace"]["rubric_version"] == "rubric-v0.2" and d["trace"]["detector_config_version"] == "detectors-v3"
    assert d["trace"]["model_manifest"]["llm"] == "mock-llm@1" and d["media"]["video_asset_id"]
    assert _actions(db, "report_view") and _actions(db, "report_list")


def test_sentence_view_accounts_for_every_contribution(login, seeded, video_file, db):
    """逐句评分（M5-6）：条目计分里的每条证据贡献，都能在某一句（或该分段整体）里找到，且加扣分一致。"""
    hr = login("hr")
    _, rep = _done(hr, seeded, video_file)
    d = hr.get(f"/api/reports/{rep.id}").json()
    shown = {}
    for seg in d["sentences"]:
        for s in seg["sentences"]:
            assert s["text"] and s["start_ms"] <= s["end_ms"]
            for h in s["hits"]:
                shown[h["evidence_id"]] = h["delta"]
        for h in seg["segment_hits"]:
            shown[h["evidence_id"]] = h["delta"]
    for it in d["result"]["items"]:
        for c in it["contributions"]:
            ev = next(e for e in d["evidence"] if e["evidence_id"] == c["evidence_id"])
            if ev["segment"] in {s["segment"] for s in d["sentences"]}:
                assert shown.get(c["evidence_id"]) == c["delta"], c
    p2 = [h for seg in d["sentences"] for s in seg["sentences"] for h in s["hits"] if h["item_id"] == "P2"]
    assert p2 and all(h["issue"] for h in p2 if h["judgment"] == "count")


def test_suggestions_generated_for_problem_sentences(login, seeded, video_file, db):
    hr = login("hr")
    _, rep = _done(hr, seeded, video_file)
    assert rep.suggestions and all(x["source"] == "llm" and x["suggestion"] for x in rep.suggestions)
    filler = next(x for x in rep.suggestions if "那么" in x["sentence"])
    assert "那么" not in filler["suggestion"]
    d = hr.get(f"/api/reports/{rep.id}").json()
    assert any(s["suggestion"] for seg in d["sentences"] for s in seg["sentences"] if s["issue"])


def test_ranking_date_and_label_filters(login, seeded, video_file, db):
    hr = login("hr")
    rec1, rep1 = _done(hr, seeded, video_file)
    rec2, rep2 = _done(hr, seeded, video_file)
    old = datetime.now(timezone.utc) - timedelta(days=10)
    db.get(Recording, rec1.id).submitted_at = old
    db.get(Report, rep1.id).label = "recommend"
    db.get(Report, rep2.id).label = "not_recommend"
    db.commit()
    rows = hr.get("/api/reports").json()
    assert [x["id"] for x in rows] == [str(rep1.id), str(rep2.id)]  # 推荐排在不推荐前
    today = datetime.now(timezone(timedelta(hours=8))).date()
    rows = hr.get(f"/api/reports?date_from={today - timedelta(days=3)}&date_to={today}").json()
    assert [x["id"] for x in rows] == [str(rep2.id)]  # C32：按日期范围划分
    rows = hr.get("/api/reports?label=not_recommend").json()
    assert [(x["id"], x["rank"]) for x in rows] == [(str(rep2.id), 2)]  # 筛选不改变名次
    assert hr.get("/api/reports?sort=S").status_code == 200
    assert hr.get("/api/reports?sort=X").status_code == 422


def test_anchor_sees_only_own_records(login, seeded, video_file, db, make_user, app):
    from conftest import Api

    hr = login("hr")
    rec_a, rep_a = _done(hr, seeded, video_file)
    rec_b, rep_b = _done(hr, seeded, video_file)
    anchor = make_user("anchor", "anchor-a")
    assert hr.put(f"/api/candidates/{rec_b.candidate_id}/linked-user", json={"user_id": str(hr.get("/api/auth/me").json()["id"])}).status_code == 422
    r = hr.put(f"/api/candidates/{rec_a.candidate_id}/linked-user", json={"user_id": str(anchor.id)})
    assert r.status_code == 200 and r.json()["linked_user_id"] == str(anchor.id)
    assert [u["username"] for u in hr.get("/api/users/anchors").json()] == ["anchor-a"]
    me = Api(app)
    assert me.post("/api/auth/login", json={"username": "anchor-a", "password": PASSWORD}).status_code == 200
    assert [x["id"] for x in me.get("/api/reports").json()] == [str(rep_a.id)]
    assert me.get(f"/api/reports/{rep_a.id}").status_code == 200
    assert me.get(f"/api/reports/{rep_b.id}").status_code == 404
    va = me.get(f"/api/reports/{rep_a.id}").json()["media"]["video_asset_id"]
    vb = hr.get(f"/api/reports/{rep_b.id}").json()["media"]["video_asset_id"]
    assert me.get(f"/api/media/{va}", headers={"Range": "bytes=0-9"}).status_code == 206
    assert me.get(f"/api/media/{vb}", headers={"Range": "bytes=0-9"}).status_code == 404
    assert me.get("/api/reports/export.xlsx").status_code == 403
    assert _actions(db, "candidate_link_user")


def test_excel_export(login, seeded, video_file, db):
    hr = login("hr")
    _done(hr, seeded, video_file)
    r = hr.get("/api/reports/export.xlsx")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/vnd.openxmlformats")
    wb = load_workbook(io.BytesIO(r.content))
    ws = wb["排名"]
    assert ws["A2"].value == "排名" and ws["B3"].value == "张三" and ws["E3"].value in ("推荐", "待定", "不推荐")
    detail = wb["条目明细"]
    heads = [c.value for c in detail[1]][2:]
    assert len(heads) == 23 and heads[0] == "人设塑造·形象" and heads[2] == "人设塑造·普通话标准" and heads[-1] == "其他·节奏与气氛"
    assert _actions(db, "report_export_excel")[0].detail["count"] == 1


def test_pdf_export(login, seeded, video_file, db):
    try:
        chromium_path()
    except PdfError:
        pytest.skip("没有 Chromium")
    hr = login("hr")
    _, rep = _done(hr, seeded, video_file)
    r = hr.get(f"/api/reports/{rep.id}/pdf")
    assert r.status_code == 200, r.text
    assert r.content[:5] == b"%PDF-" and len(r.content) > 10_000
    if os.environ.get("SAVE_REPORT_PDF"):  # 人工查看排版用
        open(os.environ["SAVE_REPORT_PDF"], "wb").write(r.content)
    assert _actions(db, "report_export_pdf")


def test_report_html_contents(login, seeded, video_file, db):
    from app.services.export import report_html
    from app.services.report_view import detail

    hr = login("hr")
    _, rep = _done(hr, seeded, video_file)
    h = report_html(detail(db, rep))
    for text in ("主播试镜评分报告", "非正式报告", "人设塑造", "需要改进的句子", "示范说法由 AI 生成", "rubric-v0.2", "mock-llm@1"):
        assert text in h, text


def test_rescore_with_new_rubric_creates_revision(login, seeded, video_file, db):
    """P-B14：按新版重算只用已存证据，不重跑模型；生成新修订，旧修订保留。"""
    hr = login("hr")
    admin = login("admin")
    rec, rep = _done(hr, seeded, video_file)
    d = raw_config()
    d["version"] = "rubric-v0.2-strict-p2"
    d["dimensions"][0]["items"][1]["free"] = 0  # P2 不再免扣
    rid = admin.post("/api/rubrics", json={"yaml_text": yaml.safe_dump(d, allow_unicode=True)}).json()["id"]
    assert hr.post(f"/api/reports/{rep.id}/rescore", json={"rubric_version_id": rid}).status_code == 403
    r = admin.post(f"/api/reports/{rep.id}/rescore", json={"rubric_version_id": rid})
    assert r.status_code == 200, r.text
    new = r.json()
    assert new["revision"] == 2 and new["trace"]["rubric_version"] == "rubric-v0.2-strict-p2"
    p2_old = next(i for i in hr.get(f"/api/reports/{rep.id}").json()["result"]["items"] if i["item_id"] == "P2")
    p2_new = next(i for i in new["result"]["items"] if i["item_id"] == "P2")
    assert p2_new["score"] <= p2_old["score"]
    assert [x["id"] for x in hr.get("/api/reports").json()] == [new["id"]]  # 列表只显示最新修订
    revs = hr.get(f"/api/reports/{new['id']}/revisions").json()
    assert [x["revision"] for x in revs] == [2, 1] and revs[1]["superseded_at"]
    assert admin.post(f"/api/reports/{rep.id}/rescore", json={"rubric_version_id": rid}).status_code == 409  # 旧修订不能再重算
    assert _actions(db, "report_rescore")
