import pytest


@pytest.fixture(autouse=True)
def isolated_demo_mode(monkeypatch):
    monkeypatch.setenv("APP_ALLOW_MOCK_SCORING", "true")
