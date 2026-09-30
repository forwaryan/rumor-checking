from __future__ import annotations

import ipaddress
import json
import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import get_settings
from backend.app.main import create_app
from backend.app.services.model_health import _reset_for_tests as reset_model_health_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
EVALS_ROOT = REPO_ROOT / "evals" / "minimal_v1"


def load_eval_fixture(filename: str):
    return json.loads((EVALS_ROOT / filename).read_text(encoding="utf-8-sig"))


@pytest.fixture(autouse=True)
def stable_test_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ANALYSIS_PROVIDER", "off")
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    # Neutralize any real LLM gateway from backend/.env so tests never reach a
    # real/internal endpoint and so a test's own KIMI_*/LLM_* setenv wins. We
    # setenv "" (not delenv) because _load_env_defaults() re-reads backend/.env
    # via os.environ.setdefault, which would otherwise restore the real values.
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:0/v1")
    monkeypatch.setenv("LLM_MODEL", "")
    monkeypatch.setenv("LLM_SEARCH_MODEL", "")
    monkeypatch.setenv("KIMI_BASE_URL", "http://127.0.0.1:0/v1")
    monkeypatch.setenv("KIMI_MODEL", "")
    monkeypatch.setenv("KIMI_SEARCH_MODEL", "")
    # Pin agent-orchestrator flags to defaults so a developer's local backend/.env
    # (which may enable the live agent path) never leaks into the test process.
    monkeypatch.setenv("AGENT_ORCHESTRATOR_ENABLED", "false")
    monkeypatch.setenv("LIGHTWEIGHT_AGENT_ENABLED", "false")
    monkeypatch.setenv("RETRIEVAL_PROVIDER", "mock")
    monkeypatch.setenv("RETRIEVAL_FALLBACK_TO_MOCK", "true")
    monkeypatch.setenv("XHS_SEARCH_ENABLED", "false")
    monkeypatch.setenv("TOUTIAO_SEARCH_ENABLED", "false")
    monkeypatch.setenv("SOGOU_WEIXIN_SEARCH_ENABLED", "false")
    monkeypatch.setenv("PIYAO_SEARCH_ENABLED", "false")
    monkeypatch.setenv("RETRIEVAL_CACHE_ENABLED", "true")
    monkeypatch.setenv("RETRIEVAL_CACHE_ALLOW_STALE_ON_ERROR", "false")
    # Isolate the retrieval cache per test so runs never read or clobber the
    # shared data/cache/retrieval directory (order-dependent contamination).
    monkeypatch.setenv("RETRIEVAL_CACHE_DIR", str(tmp_path / "retrieval-cache"))
    monkeypatch.setenv("URL_FETCH_CACHE_DIR", str(tmp_path / "url-cache"))
    monkeypatch.setenv("ANALYSIS_RUN_DIR", str(tmp_path / "analysis-runs"))
    monkeypatch.setenv("AGENT_CONTEXT_MAX_TOKENS", "0")
    monkeypatch.setenv("AGENT_LAYERED_CONTEXT_ENABLED", "true")
    monkeypatch.setenv("AGENT_PLAYBOOKS_ENABLED", "true")
    monkeypatch.setenv("AGENT_PLAYBOOK_DIR", str(REPO_ROOT / "backend" / "app" / "agent" / "playbooks"))
    get_settings.cache_clear()
    reset_model_health_registry()
    yield
    get_settings.cache_clear()
    reset_model_health_registry()


@pytest.fixture(autouse=True)
def fixture_domain_dns(monkeypatch, request):
    if request.node.get_closest_marker("slow"):
        return
    original = socket.getaddrinfo
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def resolve(host, port, *args, **kwargs):
        if host is None or host in {"", "localhost"}:
            return original(host, port, *args, **kwargs)
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", port or 443))]
        return original(host, port, *args, **kwargs)

    def allowed(address):
        if not isinstance(address, tuple) or address[0] == "localhost":
            return True
        try:
            return ipaddress.ip_address(address[0]).is_loopback
        except ValueError:
            return False

    def connect(connection, address):
        if not allowed(address):
            raise OSError("Unrecorded external connection in an offline test")
        return original_connect(connection, address)

    def connect_ex(connection, address):
        if not allowed(address):
            raise OSError("Unrecorded external connection in an offline test")
        return original_connect_ex(connection, address)

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)


@pytest.fixture()
def client() -> TestClient:
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    get_settings.cache_clear()
