"""试镜题单生成（C29）。"""
from app.models.entities import Objection, ProductCard, Product, RubricVersion
from sqlalchemy import select


def _ids(seeded):
    pid = seeded.scalar(select(Product.id))
    rid = seeded.scalar(select(RubricVersion.id))
    return str(pid), str(rid)


def test_generate_sheet_from_demo(login, seeded):
    pid, rid = _ids(seeded)
    api = login("admin")
    r = api.post("/api/sheets", json={"product_id": pid, "rubric_version_id": rid, "note": "11 月第 1 批"})
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["code"].startswith("TS") and s["status"] == "issued"
    assert len(s["objections"]) == 4 and len({o["objection_id"] for o in s["objections"]}) == 4
    assert [o["at_ms"] for o in s["objections"]] == [240000, 330000, 420000, 480000]
    assert len(s["questions"]) == 6 and len({q["question_id"] for q in s["questions"]}) == 6
    assert s["reading_text"] and s["recording_rules_version"] == "rules-v1"
    assert s["uses_draft_config"] is True  # 评分标准和红线词表都是草稿，报告须标“非正式”
    assert s["rubric_version"] == "rubric-v0.1" and s["product_card_version"] == 1
    hr = login("hr")
    assert hr.get(f"/api/sheets/{s['id']}").status_code == 200
    assert hr.post("/api/sheets", json={"product_id": pid, "rubric_version_id": rid}).status_code == 403


def test_sheet_snapshot_survives_bank_edits(login, seeded):
    pid, rid = _ids(seeded)
    api = login("admin")
    s = api.post("/api/sheets", json={"product_id": pid, "rubric_version_id": rid}).json()
    oid = s["objections"][0]["objection_id"]
    api.put(f"/api/objections/{oid}", json={"text": "改过的弹幕", "active": True})
    assert api.get(f"/api/sheets/{s['id']}").json()["objections"][0]["text"] == s["objections"][0]["text"]


def test_not_enough_objections(login, seeded):
    pid, rid = _ids(seeded)
    o = seeded.scalars(select(Objection)).first()
    o.active = False
    seeded.commit()
    r = login("admin").post("/api/sheets", json={"product_id": pid, "rubric_version_id": rid})
    assert r.status_code == 422 and "异议只有 3 条" in r.json()["detail"]


def test_requires_published_card(login, seeded):
    pid, rid = _ids(seeded)
    for c in seeded.scalars(select(ProductCard)):
        c.status = "draft"
    seeded.commit()
    r = login("admin").post("/api/sheets", json={"product_id": pid, "rubric_version_id": rid})
    assert r.status_code == 422 and "卖点卡" in r.json()["detail"]


def test_draw_rule_must_match_rubric_counts(login, seeded):
    pid, rid = _ids(seeded)
    api = login("admin")
    api.put(f"/api/products/{pid}/draw-rule", json={"objection_count": 3, "objection_times_ms": [240000, 330000, 420000]})
    r = api.post("/api/sheets", json={"product_id": pid, "rubric_version_id": rid})
    assert r.status_code == 422 and "不一致" in r.json()["detail"]


def test_card_rechecked_against_chosen_rubric(login, seeded):
    pid, rid = _ids(seeded)
    card = seeded.scalars(select(ProductCard)).first()
    content = dict(card.content)
    content["checklist"] = content["checklist"][:-1]  # 直接改库模拟历史数据：合计 27
    card.content = content
    seeded.commit()
    r = login("admin").post("/api/sheets", json={"product_id": pid, "rubric_version_id": rid})
    assert r.status_code == 422 and "27" in r.json()["detail"]


def test_void(login, seeded):
    pid, rid = _ids(seeded)
    api = login("admin")
    s = api.post("/api/sheets", json={"product_id": pid, "rubric_version_id": rid}).json()
    assert api.post(f"/api/sheets/{s['id']}/void").json()["status"] == "void"
    assert api.post(f"/api/sheets/{s['id']}/void").status_code == 409
    assert api.get("/api/sheets?status=void").json()[0]["id"] == s["id"]
