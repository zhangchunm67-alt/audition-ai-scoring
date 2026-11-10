"""后端测试：需要 PostgreSQL。设置 TEST_DATABASE_URL（该库会被清空重建），未设置则全部跳过。"""
from __future__ import annotations

import base64
import os
import subprocess
import tempfile
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
    os.environ["APP_STORAGE"] = "local"
    os.environ["APP_STORAGE_DIR"] = tempfile.mkdtemp(prefix="audition-test-storage-")
    os.environ["APP_UPLOAD_PART_BYTES"] = str(64 * 1024)  # 测试用小分片，确保走多片
    os.environ["APP_QUEUE"] = "inline"  # 提交后同步处理
    os.environ["APP_RETRY_BACKOFF_S"] = "0,0"  # 重试不等待
    os.environ["APP_CALL_RETRY_BACKOFF_S"] = "0,0"


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

    from sqlalchemy import text

    eng = create_engine(URL)
    with eng.begin() as c:  # 清空重建，避免上次残留数据影响迁移
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))
    cfg = Config(str(BACKEND / "alembic.ini"))
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")  # 空库上验证全部迁移可降级
    command.upgrade(cfg, "head")
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
def seeded(db, request):
    """演示数据。默认关掉检测配置里的人工打分分工（老测试按全部机器评写）；
    标了 @pytest.mark.human_review 的测试保留检测配置原样。"""
    from sqlalchemy import select

    from app.cli import seed_demo
    from app.models.entities import DetectorConfigVersion

    seed_demo(db)
    if request.node.get_closest_marker("human_review") is None:
        for row in db.scalars(select(DetectorConfigVersion)):
            row.content = {**row.content, "human_review": {"manual": [], "confirm": [], "confirm_on_deduction": [], "fallback": False}}
        db.commit()
    return db


def _ffmpeg(path: Path, *args: str) -> Path:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args, str(path)], check=True)
    return path


@pytest.fixture(scope="session")
def media_dir():
    with tempfile.TemporaryDirectory(prefix="audition-test-media-") as d:
        yield Path(d)


@pytest.fixture(scope="session")
def video_file(media_dir) -> Path:
    """20 秒、带画面和声音的测试视频。"""
    return _ffmpeg(media_dir / "audition.mp4", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15:duration=20",
                   "-f", "lavfi", "-i", "sine=frequency=440:duration=20", "-c:v", "libx264", "-preset", "ultrafast",
                   "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest")


@pytest.fixture(scope="session")
def silent_video(media_dir) -> Path:
    return _ffmpeg(media_dir / "silent.mp4", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=3",
                   "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p")


@pytest.fixture(scope="session")
def full_video(media_dir) -> Path:
    """约 17 分钟的合成试镜视频（低分辨率，生成很快）：主体段 00:05–10:05、6 道题各 60 秒、朗读 1 分钟。"""
    return _ffmpeg(media_dir / "full.mp4", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=5:duration=1030",
                   "-f", "lavfi", "-i", "sine=frequency=220:duration=1030", "-c:v", "libx264", "-preset", "ultrafast",
                   "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "32k", "-shortest")


FULL_SEG = {"main_start_ms": 5000, "question_starts_ms": [605000 + i * 60000 for i in range(6)], "reading_start_ms": 965000,
            "objection_offsets_ms": [240000, 330000, 420000, 480000]}
