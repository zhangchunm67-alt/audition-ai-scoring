"""登录、会话、CSRF、限流。"""
from app.security import tokens

PASSWORD = "correct-horse-battery"


def test_login_me_logout(login):
    api = login("admin")
    me = api.get("/api/auth/me").json()
    assert me["role"] == "admin" and "config.write" in me["permissions"]
    assert api.post("/api/auth/logout").status_code == 204
    assert api.get("/api/auth/me").status_code == 401


def test_session_cookie_flags(anon, make_user):
    make_user("hr")
    r = anon.post("/api/auth/login", json={"username": "hr1", "password": PASSWORD})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie


def test_wrong_password_and_unknown_user(anon, make_user):
    make_user("hr")
    assert anon.post("/api/auth/login", json={"username": "hr1", "password": "wrong-password"}).status_code == 401
    assert anon.post("/api/auth/login", json={"username": "nobody", "password": "wrong-password"}).status_code == 401


def test_inactive_user_cannot_login_and_session_revoked(login, db):
    from app.models.entities import User

    api = login("hr")
    u = db.query(User).filter_by(username="hr1").one()
    u.is_active = False
    db.commit()
    assert api.get("/api/auth/me").status_code == 401  # 已登录的会话也立即失效
    assert api.post("/api/auth/login", json={"username": "hr1", "password": PASSWORD}).status_code == 401


def test_role_change_takes_effect_immediately(login, db):
    from app.models.entities import User

    api = login("admin", "boss")
    assert api.get("/api/users").status_code == 200
    u = db.query(User).filter_by(username="boss").one()
    u.role = "hr"
    db.commit()
    assert api.get("/api/users").status_code == 403


def test_csrf_header_required_for_writes(app, make_user):
    from fastapi.testclient import TestClient

    make_user("admin")
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"username": "admin1", "password": PASSWORD}).status_code == 403
    assert c.get("/api/health").status_code == 200


def test_tampered_or_forged_token_rejected(anon):
    import uuid

    anon.c.cookies.set(tokens.COOKIE, tokens.issue(uuid.uuid4(), b"x" * 32, 1))
    assert anon.get("/api/auth/me").status_code == 401
    anon.c.cookies.set(tokens.COOKIE, "garbage")
    assert anon.get("/api/auth/me").status_code == 401


def test_login_rate_limited_after_10_failures(anon, make_user):
    make_user("hr")
    for _ in range(10):
        assert anon.post("/api/auth/login", json={"username": "hr1", "password": "wrong-password"}).status_code == 401
    assert anon.post("/api/auth/login", json={"username": "hr1", "password": PASSWORD}).status_code == 429
