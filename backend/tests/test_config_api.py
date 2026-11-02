"""评分标准版本、产品与卖点卡、异议库、题库、朗读稿、抽题规则（M1-1 至 M1-3）。"""
import copy

import yaml

from tests.scoring.helpers import CONFIG_PATH, raw_config

YAML = CONFIG_PATH.read_text("utf-8")
CHECKLIST = [
    {"id": "coverage", "name": "保障范围", "points": 5}, {"id": "deductible", "name": "免赔额", "points": 4, "compliance_required": True},
    {"id": "ratio", "name": "报销比例", "points": 3}, {"id": "waiting", "name": "等待期", "points": 4, "compliance_required": True},
    {"id": "health", "name": "健康告知", "points": 4, "compliance_required": True}, {"id": "exclusion", "name": "责任免除", "points": 3, "compliance_required": True},
    {"id": "renewal", "name": "续保条件", "points": 4}, {"id": "price", "name": "价格", "points": 3},
]


def _strip(node):
    if isinstance(node, dict):
        node.pop("pending", None)
        node.pop("calibration_required", None)
        for v in node.values():
            _strip(v)
    elif isinstance(node, list):
        for v in node:
            _strip(v)
    return node


def resolved_yaml(version="rubric-test-resolved"):
    d = _strip(raw_config())
    d["version"] = version
    return yaml.safe_dump(d, allow_unicode=True)


# ───────────── 评分标准 ─────────────


def test_import_draft_lists_blockers(login, db):
    api = login("admin")
    r = api.post("/api/rubrics", json={"yaml_text": YAML})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "draft" and body["version"] == "rubric-v0.1" and body["config_hash"].startswith("sha256:")
    assert body["blocker_count"] > 0 and any("Q6" in b for b in body["blockers"])
    assert len(body["items"]) == 23 and body["checklist_max"] == 30
    assert body["thresholds"] == {"veteran": 8, "month_1": 10, "new_trial": 15}
    assert api.get("/api/rubrics/reference").json()["id"] == body["id"]
    assert api.post("/api/rubrics", json={"yaml_text": YAML}).status_code == 409  # 同版本号不能重复导入


def test_publish_blocked_by_pending_rules(login):
    api = login("admin")
    rid = api.post("/api/rubrics", json={"yaml_text": YAML}).json()["id"]
    r = api.post(f"/api/rubrics/{rid}/publish")
    assert r.status_code == 409
    assert "blockers" in r.json()["detail"] and r.json()["detail"]["blockers"]
    assert api.get(f"/api/rubrics/{rid}").json()["status"] == "draft"


def test_publish_resolved_config(login):
    api = login("admin")
    rid = api.post("/api/rubrics", json={"yaml_text": resolved_yaml()}).json()["id"]
    r = api.post(f"/api/rubrics/{rid}/publish")
    assert r.status_code == 200 and r.json()["status"] == "published" and r.json()["published_at"]
    assert api.post(f"/api/rubrics/{rid}/publish").status_code == 409
    assert api.post(f"/api/rubrics/{rid}/retire").json()["status"] == "retired"


def test_invalid_yaml_rejected_with_reason(login):
    api = login("admin")
    r = api.post("/api/rubrics", json={"yaml_text": "a: [1, 2"})
    assert r.status_code == 422 and "YAML" in r.json()["detail"]
    d = raw_config()
    d["dimensions"][0]["items"].pop()
    r = api.post("/api/rubrics", json={"yaml_text": yaml.safe_dump(d, allow_unicode=True)})
    assert r.status_code == 422 and "条目数" in r.json()["detail"]
    d = raw_config()
    d["status"] = "published"
    r = api.post("/api/rubrics", json={"yaml_text": yaml.safe_dump(d, allow_unicode=True)})
    assert r.status_code == 422 and "不能发布" in r.json()["detail"]


# ───────────── 产品与卖点卡 ─────────────


def _product(api):
    r = api.post("/api/products", json={"code": "kids", "name": "少儿医疗险"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_card_points_must_total_checklist_max(login):
    """C25：必讲要点分值合计必须等于 30，否则不能保存。"""
    api = login("admin")
    api.post("/api/rubrics", json={"yaml_text": YAML})
    pid = _product(api)
    bad = copy.deepcopy(CHECKLIST)[:-1]  # 合计 27
    r = api.post(f"/api/products/{pid}/cards", json={"checklist": bad})
    assert r.status_code == 422 and "27" in r.json()["detail"] and "30" in r.json()["detail"]
    r = api.post(f"/api/products/{pid}/cards", json={"checklist": CHECKLIST, "glossary": [{"term": "免赔额", "plain": "先自己掏的那部分钱"}]})
    assert r.status_code == 201 and r.json()["points_total"] == 30 and r.json()["version"] == 1


def test_card_needs_rubric_and_unique_points(login):
    api = login("admin")
    pid = _product(api)
    assert api.post(f"/api/products/{pid}/cards", json={"checklist": CHECKLIST}).status_code == 422  # 还没有评分标准
    api.post("/api/rubrics", json={"yaml_text": YAML})
    dup = copy.deepcopy(CHECKLIST)
    dup[1]["id"] = "coverage"
    assert api.post(f"/api/products/{pid}/cards", json={"checklist": dup}).status_code == 422


def test_card_versions_and_publish(login):
    api = login("admin")
    api.post("/api/rubrics", json={"yaml_text": YAML})
    pid = _product(api)
    c1 = api.post(f"/api/products/{pid}/cards", json={"checklist": CHECKLIST}).json()
    c2 = api.post(f"/api/products/{pid}/cards", json={"checklist": CHECKLIST, "scenarios": ["缴费场景"]}).json()
    assert (c1["version"], c2["version"]) == (1, 2)
    assert api.post(f"/api/cards/{c1['id']}/publish").json()["status"] == "published"
    assert api.post(f"/api/cards/{c2['id']}/publish").json()["status"] == "published"
    cards = {c["version"]: c["status"] for c in api.get(f"/api/products/{pid}/cards").json()}
    assert cards == {1: "retired", 2: "published"}  # 同一产品只有一个已发布版本
    assert api.get(f"/api/products/{pid}").json()["published_card_version"] == 2


# ───────────── 异议库、题库、朗读稿、抽题规则 ─────────────


def test_objections_and_questions_crud(login):
    api = login("admin")
    pid = _product(api)
    o = api.post(f"/api/products/{pid}/objections", json={"text": "孩子有医保了，还需要买吗？", "answer_points": ["医保有报销范围限制"]}).json()
    api.put(f"/api/objections/{o['id']}", json={"text": o["text"], "active": False})
    assert api.get(f"/api/products/{pid}/objections").json() == []
    assert len(api.get(f"/api/products/{pid}/objections?include_inactive=true").json()) == 1
    q = api.post(f"/api/products/{pid}/questions", json={"text": "什么是等待期？", "full_points": ["合同生效后的一段时间"]})
    assert q.status_code == 201
    assert api.post(f"/api/products/{pid}/questions", json={"text": "无要点", "full_points": []}).status_code == 422
    assert api.get(f"/api/products/{pid}").json()["active_questions"] == 1


def test_reading_scripts(login):
    api = login("admin")
    s = api.post("/api/reading-scripts", json={"title": "稿一", "text": "各位 家长 好"}).json()
    assert s["char_count"] == 5
    assert api.put(f"/api/reading-scripts/{s['id']}", json={"title": "稿一", "text": "改", "active": False}).json()["active"] is False


def test_draw_rule_validation(login):
    api = login("admin")
    pid = _product(api)
    assert api.get(f"/api/products/{pid}/draw-rule").json() is None
    r = api.put(f"/api/products/{pid}/draw-rule", json={})
    assert r.status_code == 200 and r.json()["objection_times_ms"] == [240000, 330000, 420000, 480000]
    for bad in ({"objection_times_ms": [240000, 330000]}, {"objection_times_ms": [330000, 240000, 420000, 480000]},
                {"objection_times_ms": [240000, 330000, 420000, 600000]}):
        assert api.put(f"/api/products/{pid}/draw-rule", json=bad).status_code == 422, bad
