from __future__ import annotations

from types import SimpleNamespace

import httpx

from backend.app.services import searxng_search_provider
from backend.app.services.searxng_search_provider import SearxngSearchProvider


def _settings(*, enabled: bool, base_url: str):
    return SimpleNamespace(
        searxng_search_enabled=enabled,
        searxng_base_url=base_url,
        retrieval_timeout_seconds=12.0,
        url_fetch_max_retries=1,
    )


def test_disabled_when_flag_off():
    provider = SearxngSearchProvider(settings=_settings(enabled=False, base_url="https://s.example"))
    assert provider.enabled is False
    assert provider.search("任何查询") == []


def test_disabled_when_no_base_url():
    provider = SearxngSearchProvider(settings=_settings(enabled=True, base_url=""))
    assert provider.enabled is False
    assert provider.search("任何查询") == []


def test_parses_searxng_json_results(monkeypatch):
    provider = SearxngSearchProvider(settings=_settings(enabled=True, base_url="https://s.example"))
    payload = {
        "results": [
            {
                "url": "https://reuters.com/a",
                "title": "Reuters report on the event",
                "content": "An overseas outlet covers the story.",
                "engine": "reuters",
                "publishedDate": "2026-08-20",
            },
            {"url": "", "title": "no url dropped"},  # skipped: missing url
        ]
    }

    def _fake_get(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(searxng_search_provider, "reliable_get", _fake_get)

    results = provider.search("事件核查")
    assert len(results) == 1
    r = results[0]
    assert r.url == "https://reuters.com/a"
    assert r.provider_name == "searxng"
    assert r.source_tier == "C"  # metasearch defaults conservative
    assert r.source_name == "reuters"


def test_search_degrades_to_empty_on_transport_error(monkeypatch):
    provider = SearxngSearchProvider(settings=_settings(enabled=True, base_url="https://s.example"))

    def _boom(url, **kwargs):
        raise httpx.ConnectError("unreachable")

    monkeypatch.setattr(searxng_search_provider, "reliable_get", _boom)

    # A dead instance must never break the run — just yields nothing.
    assert provider.search("事件核查") == []


def test_search_returns_empty_on_non_200(monkeypatch):
    provider = SearxngSearchProvider(settings=_settings(enabled=True, base_url="https://s.example"))

    def _fake_get(url, **kwargs):
        return httpx.Response(502, request=httpx.Request("GET", url))

    monkeypatch.setattr(searxng_search_provider, "reliable_get", _fake_get)

    assert provider.search("事件核查") == []
