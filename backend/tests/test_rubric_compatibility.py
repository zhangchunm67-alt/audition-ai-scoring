"""部署保留旧评分配置时，新评分只能选择与当前检测器兼容的版本。"""
from datetime import datetime, timezone

import pytest
import yaml
from sqlalchemy import func, select

from app.models.entities import AuditionSheet, AuditLog, Product, RubricVersion
from app.services.rubrics import sync_bundled
from scoring import config_hash, parse_config
from test_config_api import LEGACY_YAML, YAML, resolved_yaml
from test_live_recordings import _create_live


def _legacy(db, status="draft"):
    row = RubricVersion(version="rubric-v0.1", status=status, yaml_text=LEGACY_YAML,
                        config_hash=config_hash(parse_config(yaml.safe_load(LEGACY_YAML))),
                        published_at=datetime.now(timezone.utc) if status == "published" else None)
    db.add(row)
    db.commit()
    return row


@pytest.mark.parametrize("status", ["draft", "published"])
def test_processing_reference_skips_newer_legacy_even_if_published(login, seeded, status):
    api = login("admin")
    current = seeded.scalar(select(RubricVersion))
    old = _legacy(seeded, status)
    original = old.yaml_text, old.config_hash, old.status
    # 历史内容仍按原来的版本优先级校验；新评分先校验证据协议。
    assert api.get("/api/rubrics/reference").json()["id"] == str(old.id)
    r = api.get("/api/rubrics/reference?for_processing=true")
    assert r.status_code == 200, r.text
    assert r.json()["id"] == str(current.id)
    assert r.json()["processing_supported"] is True
    detail = api.get(f"/api/rubrics/{old.id}").json()
    assert not detail["processing_supported"]
    assert any("O5" in b for b in detail["processing_blockers"])
    assert (detail["yaml_text"], detail["config_hash"], detail["status"]) == original


def test_processing_list_filters_by_protocol_and_status_not_version_name(login, seeded):
    api = login("admin")
    current = seeded.scalar(select(RubricVersion))
    _legacy(seeded)
    # 条目类型相同但仍截取 10 分钟的旧协议，也不能供当前检测器使用。
    data = yaml.safe_load(YAML)
    data["version"] = "custom-with-old-duration-policy"
    next(it for d in data["dimensions"] for it in d["items"] if it["id"] == "P2")["normalize"]["both_ways"] = False
    r = api.post("/api/rubrics", json={"yaml_text": yaml.safe_dump(data, allow_unicode=True)})
    assert r.status_code == 201, r.text
    assert not r.json()["processing_supported"]
    published = api.post("/api/rubrics", json={"yaml_text": resolved_yaml("custom-current")}).json()
    assert api.post(f"/api/rubrics/{published['id']}/publish").status_code == 200
    assert api.get("/api/rubrics/reference?for_processing=true").json()["id"] == published["id"]
    assert {r["id"] for r in api.get("/api/rubrics?for_processing=true").json()} == {str(current.id), published["id"]}
    assert api.post(f"/api/rubrics/{published['id']}/retire").status_code == 200
    assert [r["id"] for r in api.get("/api/rubrics?for_processing=true").json()] == [str(current.id)]
    assert len(api.get("/api/rubrics").json()) == 4  # 历史配置仍可查看


def test_no_compatible_reference_explains_remedy(login, db):
    api = login("hr")
    _legacy(db, "published")
    r = api.get("/api/rubrics/reference?for_processing=true")
    assert r.status_code == 422
    assert "导入现行评分配置" in r.json()["detail"]
    assert api.get("/api/rubrics?for_processing=true").json() == []


def test_live_default_uses_compatible_draft_and_explicit_legacy_stays_blocked(login, seeded, video_file):
    api = login("hr")
    current = seeded.scalar(select(RubricVersion))
    old = _legacy(seeded, "published")
    r = _create_live(api, seeded, video_file)
    assert r.status_code == 201, r.text
    sheet = seeded.get(AuditionSheet, r.json()["sheet_id"])
    assert sheet.rubric_version_id == current.id
    assert r.json()["uses_draft_config"] is True
    r = _create_live(api, seeded, video_file, rubric_version_id=str(old.id))
    assert r.status_code == 422 and "不匹配" in r.json()["detail"]
    assert seeded.scalar(select(func.count()).select_from(AuditionSheet)) == 1


def test_sync_only_adds_current_draft_once_and_preserves_legacy(db):
    old = _legacy(db, "published")
    original = old.yaml_text, old.config_hash, old.status
    current = sync_bundled(db)
    db.commit()
    assert current.version == "rubric-v0.3" and current.status == "draft"
    assert sync_bundled(db).id == current.id
    db.commit()
    db.expire_all()
    assert (old.yaml_text, old.config_hash, old.status) == original
    assert db.scalar(select(func.count()).select_from(RubricVersion)) == 2
    assert db.scalar(select(func.count()).select_from(Product)) == 0  # 升级不添加演示业务数据
    events = list(db.scalars(select(AuditLog).where(AuditLog.action == "rubric_import")))
    assert len(events) == 1 and events[0].detail["source"] == "bundled"
    current.status = "retired"
    db.commit()
    assert sync_bundled(db).status == "retired"  # 管理员主动停用的配置不重新启用


def test_sync_refuses_same_version_with_different_content(db):
    changed = yaml.safe_load(YAML)
    changed["thresholds"]["veteran"] = 7
    source = yaml.safe_dump(changed, allow_unicode=True)
    row = RubricVersion(version=changed["version"], status="draft", yaml_text=source,
                        config_hash=config_hash(parse_config(changed)))
    db.add(row)
    db.commit()
    with pytest.raises(ValueError, match="不能覆盖历史配置"):
        sync_bundled(db)
    assert row.yaml_text == source
