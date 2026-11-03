"""校准（M6）：金标准集、背对背打分、汇总与裁决、与 AI 对比、一致率口径、月度抽样、告警、看板、权限。"""
from datetime import datetime, timedelta, timezone

import yaml
from sqlalchemy import select

from app.models.entities import AuditLog, CalibrationAssignment, GoldSample, Notification, Recording, RubricVersion
from conftest import PASSWORD, Api
from test_pipeline import _submit


def _done(api, db, video):
    rec = _submit(api, db, video)
    assert rec.status == "done", rec.failure_reason
    return rec


def _human(task: dict, *, p2: int = 9, p3: int = 8, s1: int = 10, skip: str | None = None) -> list[dict]:
    """按打分页的材料构造一位校准员的完整证据（等级类直接给等级，计次类逐次录入）。"""
    ev: list[dict] = []

    def add(item, kind, **kw):
        if item != skip:
            ev.append({"item_id": item, "kind": kind, **kw})

    add("P1", "level", judgment=10)
    for i in range(p2):
        add("P2", "occurrence", label="那么", judgment="count", start_ms=10_000 + i * 1000)
    add("P3", "level", judgment=p3)
    add("P5", "level", judgment=3)
    add("P7", "level", judgment=7)
    if task["props_available"]:
        add("P9", "instance", label="sticker", judgment="count")
    add("S1", "level", judgment=s1)
    for p in task["card"]["checklist"]:
        add("S2", "checklist_hit", ref=p["id"], label=p["name"], judgment="count")
    add("S2", "level", ref="structure", judgment=14)
    for o in task["objections"]:
        for el in ("direct_answer", "advantage", "altruistic_close"):
            add("S3", "question", ref=o["objection_id"], label=el, judgment="count")
    for m in ("herd", "loss_aversion", "price_split"):
        add("S4", "instance", label=m, judgment="count")
    add("L1", "level", judgment=20)
    for it in ("L2", "L4", "L5"):
        add(it, "instance", label="x", judgment="count")
    for t in task["card"]["glossary"][:2]:
        add("O1", "instance", label=t, judgment="count")
    for t in task["card"]["targeted_points"][:2]:
        add("O2", "instance", label=t, judgment="count")
    add("O3", "instance", label="scene", judgment="count")
    add("O4", "level", ref="rhythm", judgment=5)
    add("O4", "level", ref="enthusiasm", judgment=4)
    for q in task["questions"]:
        add("O5", "question", ref=q["question_id"], judgment="partial")
    return ev


def _as(app, username):
    c = Api(app)
    assert c.post("/api/auth/login", json={"username": username, "password": PASSWORD}).status_code == 200
    return c


def _setup(login, seeded, video, make_user, app, n_recordings=1, rv_yaml=None):
    hr, admin = login("hr"), login("admin")
    recs = [_done(hr, seeded, video) for _ in range(n_recordings)]
    u1, u2 = make_user("calibrator", "cal-a"), make_user("calibrator", "cal-b")
    rid = str(seeded.scalar(select(RubricVersion.id)))
    if rv_yaml:
        rid = admin.post("/api/rubrics", json={"yaml_text": rv_yaml}).json()["id"]
    gs = admin.post("/api/calibration/sets", json={"name": "上线前金标准", "purpose": "prelaunch", "rubric_version_id": rid}).json()
    admin.post(f"/api/calibration/sets/{gs['id']}/samples", json={"recording_ids": [str(r.id) for r in recs]})
    r = admin.post(f"/api/calibration/sets/{gs['id']}/assign", json={"calibrator_ids": [str(u1.id), str(u2.id)]})
    assert r.status_code == 200, r.text
    return admin, hr, recs, gs, _as(app, "cal-a"), _as(app, "cal-b")


def _score(cal, **kw):
    task_id = cal.get("/api/calibration/my-tasks").json()[0]["id"]
    task = cal.get(f"/api/calibration/assignments/{task_id}").json()
    assert cal.put(f"/api/calibration/assignments/{task_id}", json={"evidence": _human(task, **kw)}).status_code == 200
    r = cal.post(f"/api/calibration/assignments/{task_id}/submit")
    assert r.status_code == 200, r.text
    return task


def test_blind_scoring_to_gold_and_comparison(login, seeded, video_file, make_user, app, db):
    admin, hr, (rec,), gs, a, b = _setup(login, seeded, video_file, make_user, app)
    tasks = a.get("/api/calibration/my-tasks").json()
    assert len(tasks) == 1 and tasks[0]["status"] == "assigned"
    task = a.get(f"/api/calibration/assignments/{tasks[0]['id']}").json()
    # 背对背、不看 AI：打分材料里没有 AI 的分数、结论或报告
    assert not {"report", "label", "verdict", "ai", "comparison", "result"} & set(task)
    assert b.get(f"/api/calibration/assignments/{tasks[0]['id']}").status_code == 404  # 看不到别人的任务
    assert a.get(f"/api/media/{task['video_asset_id']}", headers={"Range": "bytes=0-9"}).status_code == 206
    assert a.get(f"/api/reports").status_code == 403  # 校准员不看报告
    # 漏打条目不能提交
    a.put(f"/api/calibration/assignments/{task['id']}", json={"evidence": _human(task, skip="S1")})
    r = a.post(f"/api/calibration/assignments/{task['id']}/submit")
    assert r.status_code == 422 and "S1" in r.json()["detail"]
    _score(a, p2=9)
    s = db.scalar(select(GoldSample))
    db.refresh(s)
    assert s.status == "collecting"  # 等另一位
    _score(b, p2=9, p3=6)  # P3 8 与 6 相差 2，未超满分 20%
    db.refresh(s)
    assert s.status == "final" and s.flagged_items == []
    subs = [x.result["items"] for x in db.scalars(select(CalibrationAssignment))]
    assert s.gold["items"]["P3"] == 7.0  # 两人取平均
    assert all(s.gold["items"][k] == (subs[0][k] + subs[1][k]) / 2 for k in subs[0] if subs[0][k] is not None)
    d = admin.get(f"/api/calibration/samples/{s.id}").json()
    assert len(d["calibrators"]) == 2 and d["comparison"]["ai_complete"] is True
    assert {x["id"] for x in d["comparison"]["dimensions"]} == {"P", "S", "L", "O"} and len(d["comparison"]["items"]) == 23
    m = admin.get(f"/api/calibration/sets/{gs['id']}").json()["metrics"]
    assert m["final"] == 1 and m["dimension_agreement"] is not None and m["conclusion_agreement"] in (0.0, 1.0)
    assert m["human_conclusion_agreement"] is not None and m["targets"] == {"dimension": 0.85, "conclusion": 0.95, "item": 0.85}
    assert db.scalar(select(AuditLog).where(AuditLog.action == "gold_finalize"))
    assert b.put(f"/api/calibration/assignments/{d['id']}", json={"evidence": []}).status_code == 404


def test_disagreement_needs_adjudication(login, seeded, video_file, make_user, app, db):
    admin, hr, recs, gs, a, b = _setup(login, seeded, video_file, make_user, app)
    _score(a, s1=10)
    _score(b, s1=3)  # 相差 7 > 满分 10 的 20%
    s = db.scalar(select(GoldSample))
    db.refresh(s)
    assert s.status == "needs_adjudication" and s.flagged_items == ["S1"]
    assert admin.post(f"/api/calibration/samples/{s.id}/adjudicate", json={"item_id": "P1", "score": 10, "note": "x"}).status_code == 422
    assert admin.post(f"/api/calibration/samples/{s.id}/adjudicate", json={"item_id": "S1", "score": 11, "note": "x"}).status_code == 422
    r = admin.post(f"/api/calibration/samples/{s.id}/adjudicate", json={"item_id": "S1", "score": 6, "note": "开会裁决：框架不完整"})
    assert r.status_code == 200 and r.json()["status"] == "final" and r.json()["gold"]["items"]["S1"] == 6


def test_incomplete_ai_counts_as_disagreement(login, seeded, video_file, make_user, app, db):
    """C35：AI 结果不完整（这里：按金标准集版本需要更多轮次）计为不一致，不从分母剔除。"""
    from tests.scoring.helpers import raw_config

    d = raw_config()
    d["version"] = "rubric-wide-band"
    d["critical"]["review_band"] = 30  # 所有样本都临界 → 需要 3 轮，AI 只跑了 1 轮
    admin, hr, recs, gs, a, b = _setup(login, seeded, video_file, make_user, app, rv_yaml=yaml.safe_dump(d, allow_unicode=True))
    _score(a)
    _score(b)
    m = admin.get(f"/api/calibration/sets/{gs['id']}").json()["metrics"]
    assert m["final"] == 1 and m["dimension_agreement"] == 0.0 and m["conclusion_agreement"] == 0.0 and m["gate_passed"] is False


def test_below_target_alerts_once(login, seeded, video_file, make_user, app, db):
    from tests.scoring.helpers import raw_config

    d = raw_config()
    d["version"] = "rubric-wide-band-2"
    d["critical"]["review_band"] = 30
    admin, hr, recs, gs, a, b = _setup(login, seeded, video_file, make_user, app, rv_yaml=yaml.safe_dump(d, allow_unicode=True))
    _score(a)
    _score(b)
    notes = db.scalars(select(Notification).where(Notification.template == "calibration_below_target")).all()
    metrics_ = {n.payload["metric"] for n in notes}
    assert {"dimension", "conclusion"} <= metrics_ and all(n.channel == "mock" for n in notes)
    from app.services.calibration import check_alerts
    from app.models.entities import GoldSet

    check_alerts(db, db.get(GoldSet, gs["id"]))
    db.commit()
    assert len(db.scalars(select(Notification).where(Notification.template == "calibration_below_target")).all()) == len(notes)


def test_monthly_sampling(login, seeded, video_file, make_user, app, db):
    hr, admin = login("hr"), login("admin")
    recs = [_done(hr, seeded, video_file) for _ in range(3)]
    db.get(Recording, recs[0].id).submitted_at = datetime(2026, 10, 15, tzinfo=timezone.utc)
    db.commit()
    rid = str(seeded.scalar(select(RubricVersion.id)))
    gs = admin.post("/api/calibration/sets", json={"name": "11 月抽检", "purpose": "monthly_sample", "rubric_version_id": rid}).json()
    month = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m")
    r = admin.post(f"/api/calibration/sets/{gs['id']}/sample-month", json={"month": month, "count": 10}).json()
    assert r["drawn"] == 2 and r["pool"] == 2 and r["samples"] == 2  # 10 月那条不在本月
    r = admin.post(f"/api/calibration/sets/{gs['id']}/sample-month", json={"month": month, "count": 10}).json()
    assert r["drawn"] == 0  # 不重复抽
    assert admin.post(f"/api/calibration/sets/{gs['id']}/assign", json={"calibrator_ids": [str(make_user("calibrator", "c1").id)]}).status_code == 422
    hr_user = hr.get("/api/auth/me").json()["id"]
    assert admin.post(f"/api/calibration/sets/{gs['id']}/assign", json={"calibrator_ids": [hr_user, str(make_user("calibrator", "c2").id)]}).status_code == 422


def test_dashboards(login, seeded, video_file, db):
    hr, admin = login("hr"), login("admin")
    _done(hr, seeded, video_file)
    e = admin.get("/api/dashboard/efficiency").json()
    assert e["submitted"] == 1 and e["done"] == 1 and e["failure_rate"] == 0.0 and e["minutes"]["median"] is not None
    assert e["over_30_min"] == 0 and len(e["low_confidence"]) == 23 and e["daily"][0]["done"] == 1
    a = admin.get("/api/dashboard/agreement").json()
    assert a["overall"]["samples"] == 0 and a["sets"] == []
    assert hr.get("/api/dashboard/efficiency").status_code == 403  # PRD：管理员看看板
    assert db.scalar(select(AuditLog).where(AuditLog.action == "dashboard_view"))
