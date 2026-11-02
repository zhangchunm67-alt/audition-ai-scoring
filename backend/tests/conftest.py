"""后端测试：需要 PostgreSQL。设置 TEST_DATABASE_URL（该库会被清空重建），未设置则全部跳过。"""
from __future__ import annotations

import base64
import os
from pathlib import Path

import pytest

URL = os.environ.get("TEST_DATABASE_URL")
BACKEND = Path(__file__).resolve().parents[1]
PASSWORD = "correct-horse-battery"

if URL:
    os.environ["DATABASE_URL"] = URL
    for k in ("APP_SESSION_KEY", "APP_DATA_KEY", "APP_HASH_KEY"):
        os.environ.setdefault(k, base64.b64encode(os.urandom(32)).decode())
    os.environ["APP_COOKIE_SECURE"] = "false"  # 测试客户端走 http


def pytest_collection_modifyitems(config, items):
    if URL:
        return
    skip = pytest.mark.skip(reason="未设置 TEST_DATABASE_URL")
    for it in items:
        if str(BACKEND) in str(it.fspath):
            it.add_marker(skip)


@pytest.fixture(scope="session")
def engine():
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    cfg = Config(str(BACKEND / "alembic.ini"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    eng = create_engine(URL)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def _clean(request, engine):
    from sqlalchemy import text

    from app.models import Base

    names = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as c:
        c.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def db(engine):
    from sqlalchemy.orm import Session

    with Session(engine) as s:
        yield s


@pytest.fixture(scope="session")
def app(engine):
    from app.main import create_app

    return create_app()


class Api:
    """带登录状态的测试客户端；写操作自动带上 X-Requested-With。"""

    def __init__(self, app):
        from fastapi.testclient import TestClient

        self.c = TestClient(app, headers={"X-Requested-With": "fetch"})

    def __getattr__(self, name):
        return getattr(self.c, name)


@pytest.fixture
def make_user(db):
    from app.cli import create_user

    def make(role: str, username: str | None = None):
        return create_user(db, username or f"{role}1", role, f"{role} 测试", PASSWORD)

    return make


@pytest.fixture
def login(app, make_user):
    def as_role(role: str, username: str | None = None) -> Api:
        u = make_user(role, username)
        api = Api(app)
        r = api.post("/api/auth/login", json={"username": u.username, "password": PASSWORD})
        assert r.status_code == 200, r.text
        return api

    return as_role


@pytest.fixture
def anon(app) -> Api:
    return Api(app)


@pytest.fixture
def seeded(db):
    from app.cli import seed_demo

    seed_demo(db)
    return db
