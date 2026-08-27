from __future__ import annotations

from types import SimpleNamespace

from backend.app.services import source_registry


def _settings(**overrides):
    values = {
        "retrieval_provider": "playwright",
        "llm_api_key": None,
        "xhs_search_enabled": True,
        "toutiao_search_enabled": True,
        "sogou_weixin_search_enabled": True,
        "piyao_search_enabled": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_registry_separates_configuration_availability_and_enabled(monkeypatch):
    monkeypatch.setattr(source_registry, "which", lambda command: None)

    sources = {
        source.id: source
        for source in source_registry.list_source_capabilities(_settings())
    }

    assert sources["baidu"].configured is True
    assert sources["baidu"].available is True
    assert sources["baidu"].enabled is True
    assert sources["xiaohongshu"].configured is True
    assert sources["xiaohongshu"].available is False
    assert sources["xiaohongshu"].enabled is False
    assert sources["xiaohongshu"].unavailable_reason == "未检测到 xhs-cli"


def test_registry_reports_missing_llm_credential_without_exposing_secrets(monkeypatch):
    monkeypatch.setattr(source_registry, "which", lambda command: "/usr/local/bin/xhs")

    snapshot = source_registry.source_capability_snapshot(
        _settings(retrieval_provider="kimi", llm_api_key=None)
    )
    sources = {source["id"]: source for source in snapshot["sources"]}

    assert sources["kimi"]["configured"] is True
    assert sources["kimi"]["available"] is False
    assert sources["kimi"]["enabled"] is False
    assert sources["kimi"]["unavailable_reason"] == "未配置 LLM 凭据"
    assert snapshot["summary"]["status"] == "degraded"
    assert snapshot["summary"]["active_primary"] is None
    assert snapshot["summary"]["unavailable"] == 2
    assert "api_key" not in str(snapshot).lower()
    assert "base_url" not in str(snapshot).lower()


def test_registry_marks_disabled_http_source_as_available_but_not_enabled(monkeypatch):
    monkeypatch.setattr(source_registry, "which", lambda command: None)

    sources = {
        source.id: source
        for source in source_registry.list_source_capabilities(
            _settings(toutiao_search_enabled=False)
        )
    }

    assert sources["toutiao"].configured is False
    assert sources["toutiao"].available is True
    assert sources["toutiao"].enabled is False
    assert sources["toutiao"].unavailable_reason == "配置已关闭"


def test_snapshot_reports_enabled_sources_by_kind(monkeypatch):
    monkeypatch.setattr(source_registry, "which", lambda command: None)

    summary = source_registry.source_capability_snapshot(_settings())["summary"]

    assert summary["status"] == "degraded"
    assert summary["active_primary"] == "baidu"
    assert summary["enabled_by_kind"] == {
        "primary": 1,
        "supplementary": 3,
        "derived": 1,
    }
