from app.providers.registry import allow_mock_scoring, mock_capabilities, get_providers
from app.pipeline.detectors import human_plan
from app.pipeline.detector_config import load_file
from app.pipeline.readiness import material_review_items


def test_missing_material_is_not_a_zero_and_script_is_sufficient_for_targeting():
    assert material_review_items({}) == {"L5", "O2"}
    assert material_review_items({"fixed_script": {"text": "产品参考话术"}}) == {"L5"}
    assert material_review_items({"targeted_points": ["目标人群"], "key_numbers": [{"name": "核实过的参数", "value": "1"}]}) == set()


def test_mock_requires_explicit_permission_and_production_never_allows(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("APP_ALLOW_MOCK_SCORING", raising=False)
    assert not allow_mock_scoring()
    monkeypatch.setenv("APP_ALLOW_MOCK_SCORING", "true")
    assert allow_mock_scoring()
    monkeypatch.setenv("APP_ENV", "production")
    assert not allow_mock_scoring()


def test_mock_capabilities_are_manual_outside_demo(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("APP_PROVIDERS", "mock")
    providers = get_providers()
    assert "asr" in mock_capabilities(providers)
    monkeypatch.setenv("APP_ALLOW_MOCK_SCORING", "false")
    cfg, _ = load_file()
    plan = human_plan(cfg, providers, {"O1", "O2", "O3", "P7"})
    assert set(plan["manual"]) == {"O1", "O2", "O3", "P7"}
