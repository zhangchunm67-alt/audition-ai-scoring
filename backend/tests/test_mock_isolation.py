from app.providers.registry import get_providers
from app.pipeline.readiness import blockers
from app.models.entities import AuditionSheet,Product,RubricVersion
from app.api.sheets import create_live_sheet
from sqlalchemy import select


def test_init_config_is_idempotent_and_does_not_seed_products(db):
    from app.cli import init_config
    from sqlalchemy import func
    init_config(db)
    init_config(db)
    assert db.scalar(select(func.count()).select_from(Product)) == 0
    assert db.scalar(select(func.count()).select_from(RubricVersion)) == 1


def test_live_submission_blocks_mock_asr_by_default(login, seeded, monkeypatch):
    api = login("admin")
    from app.models.entities import User
    actor = seeded.scalar(select(User).where(User.username == "admin1"))
    sheet = create_live_sheet(seeded, seeded.scalar(select(Product.id)), seeded.scalar(select(RubricVersion.id)), actor)
    monkeypatch.setenv("APP_ALLOW_MOCK_SCORING", "false")
    assert any("Mock" in reason for reason in blockers(seeded, sheet, get_providers(), live=True))


def test_old_mock_report_hidden_from_real_ranking_but_readable(login, seeded, video_file, monkeypatch):
    from test_reports_api import _done
    api = login("hr")
    _, report = _done(api, seeded, video_file)
    assert len(api.get("/api/reports").json()) == 1
    monkeypatch.setenv("APP_ALLOW_MOCK_SCORING", "false")
    assert api.get("/api/reports").json() == []
    assert api.get(f"/api/reports/{report.id}").status_code == 200
