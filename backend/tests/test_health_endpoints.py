"""Tests for the /health/* endpoints.

Skip TestClient (starlette version-skew makes it TypeError in this environment)
and call the endpoint functions directly — they are plain callables that return
plain dicts. What matters is the shape and the security constraint that no
internal-gateway details leak through them."""
from __future__ import annotations

from backend.app.api.v1.endpoints.health import model_health_snapshot
from backend.app.services import model_health


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
