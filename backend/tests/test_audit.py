"""审计：登录、账号管理、配置变更、题单生成、查看审计本身都要留痕。"""
from sqlalchemy import select

from app.models.entities import AuditLog, Product, RubricVersion
from tests.scoring.helpers import CONFIG_PATH


def _actions(db):
    return [a.action for a in db.scalars(select(AuditLog).order_by(AuditLog.id))]


def test_actions_are_logged(login, db, anon):
    admin = login("admin")
    anon.post("/api/auth/login", json={"username": "admin1", "password": "bad-password"})
    admin.post("/api/users", json={"username": "hr9", "display_name": "HR", "role": "hr", "password": "0123456789ab"})
    rid = admin.post("/api/rubrics", json={"yaml_text": CONFIG_PATH.read_text("utf-8")}).json()["id"]
    admin.post(f"/api/rubrics/{rid}/publish")  # 被拒绝：不应留下发布记录
    admin.post("/api/products", json={"code": "kids", "name": "少儿医疗险"})
    admin.get("/api/audit-logs")
    acts = _actions(db)
    for a in ("login", "login_failed", "user_create", "rubric_import", "product_create", "audit_view"):
        assert a in acts, a
    assert "rubric_publish" not in acts
    row = db.scalar(select(AuditLog).where(AuditLog.action == "rubric_import"))
    assert row.detail["version"] == "rubric-v0.3" and row.actor_type == "user" and row.actor_id


def test_sheet_generation_logged(login, seeded, db):
    api = login("admin")
    pid, rid = seeded.scalar(select(Product.id)), seeded.scalar(select(RubricVersion.id))
    s = api.post("/api/sheets", json={"product_id": str(pid), "rubric_version_id": str(rid)}).json()
    row = db.scalar(select(AuditLog).where(AuditLog.action == "sheet_create"))
    assert row.target_id == s["id"] and row.detail["uses_draft_config"] is True


def test_audit_filter(login):
    admin = login("admin")
    admin.post("/api/products", json={"code": "kids", "name": "少儿医疗险"})
    rows = admin.get("/api/audit-logs?action=product_create").json()
    assert len(rows) == 1 and rows[0]["action"] == "product_create"


def test_user_admin_cannot_lock_self_out(login):
    admin = login("admin")
    me = admin.get("/api/auth/me").json()
    assert admin.patch(f"/api/users/{me['id']}", json={"role": "hr"}).status_code == 409
    assert admin.patch(f"/api/users/{me['id']}", json={"is_active": False}).status_code == 409
