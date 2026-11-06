"""精简业务字段后，历史数据库仍可读取，新增记录仍满足原约束。"""
import yaml
from sqlalchemy import select, text

from app.models.entities import DetectorRun, GoldSet, PipelineRun, RubricVersion
from scoring import config_hash, parse_config
from test_config_api import resolved_yaml
from test_models import _recording


def test_detector_legacy_tries_keeps_storage_and_insert_default(db):
    rec, _ = _recording(db)
    run = PipelineRun(recording_id=rec.id, round_no=1)
    db.add(run)
    db.flush()
    detector = DetectorRun(run_id=run.id, detector_id="P1", status="completed")
    db.add(detector)
    db.flush()
    assert db.scalar(text("SELECT tries FROM detector_runs WHERE id=:id"), {"id": detector.id}) == 1

    db.execute(text("UPDATE detector_runs SET tries=3 WHERE id=:id"), {"id": detector.id})
    db.expire(detector)
    assert detector._legacy_tries == 3
    detector.status = "failed"
    db.flush()
    assert db.scalar(text("SELECT tries FROM detector_runs WHERE id=:id"), {"id": detector.id}) == 3


def test_historical_regression_set_readable_but_not_creatable(login, seeded):
    api = login("admin")
    rv = seeded.scalar(select(RubricVersion))
    legacy = GoldSet(name="历史回归集", purpose="regression", rubric_version_id=rv.id)
    seeded.add(legacy)
    seeded.commit()
    seeded.expire_all()
    assert seeded.get(GoldSet, legacy.id).purpose == "regression"
    response = api.get(f"/api/calibration/sets/{legacy.id}")
    assert response.status_code == 200, response.text
    assert response.json()["purpose"] == "regression"
    response = api.post("/api/calibration/sets", json={
        "name": "新增回归集", "purpose": "regression", "rubric_version_id": str(rv.id),
    })
    assert response.status_code == 422


def test_rubric_lifecycle_keeps_original_yaml_and_hash(login):
    api = login("admin")
    legacy = yaml.safe_load(resolved_yaml("legacy-format"))
    legacy.update(status="draft", rounding="half_up")
    for dimension in legacy["dimensions"]:
        for item in dimension["items"]:
            if item["type"] == "T2":
                item["cap"] = item["max"]
            elif item["type"] == "T3+T4":
                item["penalty_scope"] = "item"
    old_yaml = yaml.safe_dump(legacy, allow_unicode=True)
    new_yaml = resolved_yaml("simplified-format")
    for source in (old_yaml, new_yaml):
        expected_hash = config_hash(parse_config(yaml.safe_load(source)))
        response = api.post("/api/rubrics", json={"yaml_text": source})
        assert response.status_code == 201, response.text
        rid = response.json()["id"]
        for action, status in ((None, "draft"), ("publish", "published"), ("retire", "retired")):
            if action:
                assert api.post(f"/api/rubrics/{rid}/{action}").status_code == 200
            detail = api.get(f"/api/rubrics/{rid}").json()
            assert detail["status"] == status
            assert detail["yaml_text"] == source
            assert detail["config_hash"] == expected_hash
