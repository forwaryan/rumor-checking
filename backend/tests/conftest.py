from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import get_settings
from backend.app.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]
EVALS_ROOT = REPO_ROOT / "evals" / "minimal_v1"


def load_eval_fixture(filename: str):
    return json.loads((EVALS_ROOT / filename).read_text(encoding="utf-8-sig"))


@pytest.fixture(autouse=True)
def stable_test_env(monkeypatch):
    monkeypatch.setenv("ANALYSIS_PROVIDER", "off")
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.setenv("RETRIEVAL_PROVIDER", "mock")
    monkeypatch.setenv("RETRIEVAL_FALLBACK_TO_MOCK", "true")
    monkeypatch.setenv("RETRIEVAL_CACHE_ENABLED", "true")
    monkeypatch.setenv("RETRIEVAL_CACHE_ALLOW_STALE_ON_ERROR", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def client() -> TestClient:
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    get_settings.cache_clear()
