"""Tests for the /health/* endpoints.

Skip TestClient (starlette version-skew makes it TypeError in this environment)
and call the endpoint functions directly — they are plain callables that return
plain dicts. What matters is the shape and the security constraint that no
internal-gateway details leak through them."""
from __future__ import annotations

from types import SimpleNamespace

from backend.app.api.v1.endpoints.health import (
    list_search_sources,
    model_health_snapshot,
    source_capabilities,
)
from backend.app.services import model_health, source_registry


def test_model_health_snapshot_returns_registry_state(monkeypatch):
    # Isolate the process-wide registry so activity from other tests can't leak in.
    monkeypatch.setattr(model_health, "_registry", None)
    reg = model_health.get_model_health_registry()
    reg.report_failure("fast-a")
    reg.report_success("fast-a")   # clears consecutive_errors but total_failures stays 1
    reg.report_failure("fast-b")

    body = model_health_snapshot()
    assert set(body["models"]) == {"fast-a", "fast-b"}
    assert body["models"]["fast-a"]["total_failures"] == 1
    assert body["models"]["fast-a"]["total_successes"] == 1
    assert body["models"]["fast-a"]["healthy"] is True   # success reset it
    assert body["models"]["fast-b"]["healthy"] is True   # 1 < threshold
    assert body["models"]["fast-b"]["consecutive_errors"] == 1


def test_model_health_snapshot_never_leaks_gateway_or_key(monkeypatch):
    # A dashboard-facing endpoint must not surface the internal-gateway host or the
    # API key. Only model names (which the whitelist already exposes) are OK.
    monkeypatch.setattr(model_health, "_registry", None)
    reg = model_health.get_model_health_registry()
    reg.report_failure("m")
    body = model_health_snapshot()

    import json
    text = json.dumps(body)
    # No secret we know about must appear anywhere in the payload.
    assert "llm-gw" not in text.lower()
    assert "bearer" not in text.lower()
    assert "api_key" not in text.lower()


def test_model_health_snapshot_empty_by_default(monkeypatch):
    # Post-restart / never-touched: no models tracked yet — that's the correct
    # "everything's fine" signal (see model_health.py), not an error.
    monkeypatch.setattr(model_health, "_registry", None)
    body = model_health_snapshot()
    assert body == {"models": {}}


def test_source_endpoints_share_registry_and_keep_ui_compatibility(monkeypatch):
    settings = SimpleNamespace(
        retrieval_provider="playwright",
        llm_api_key=None,
        xhs_search_enabled=True,
        toutiao_search_enabled=True,
        sogou_weixin_search_enabled=True,
        piyao_search_enabled=True,
    )
    monkeypatch.setattr(source_registry, "get_settings", lambda: settings)
    monkeypatch.setattr(source_registry, "which", lambda command: None)

    selectable = list_search_sources()["sources"]
    doctor = source_capabilities()
    selectable_ids = {source["id"] for source in selectable}
    doctor_ids = {source["id"] for source in doctor["sources"]}

    assert {"baidu", "xiaohongshu", "toutiao", "sogou_weixin", "piyao", "official_boost"} == selectable_ids
    assert {"mock", "gdelt", "kimi"} < doctor_ids
    assert all(
        {"id", "label", "description", "enabled", "default_on"} <= source.keys()
        for source in selectable
    )
    assert doctor["summary"]["total"] == len(doctor["sources"])
    assert doctor["summary"]["active_primary"] == "baidu"
    assert doctor["summary"]["status"] == "degraded"
