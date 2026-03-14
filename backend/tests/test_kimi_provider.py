from __future__ import annotations

import backend.app.services.kimi_provider as kimi_provider_module
from backend.app.core.config import get_settings
from backend.app.models.schemas import NormalizedEvent
from backend.app.services.kimi_provider import KimiProvider


class _DummyResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self):
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"event": {"title": "待核实事件", "summary": "需要继续核查", "keywords": [], "source_name": null, "published_at": null}, "claims": []}'
                    }
                }
            ]
        }


def _question_event() -> NormalizedEvent:
    return NormalizedEvent(
        summary="最近是否有一个女网红因为脑出血去世了？",
        input_type="question_only",
        raw_input="最近是否有一个女网红因为脑出血去世了？",
    )


def test_settings_trim_kimi_model(monkeypatch):
    monkeypatch.setenv("KIMI_MODEL", "  kimi-k2.5  ")
    get_settings.cache_clear()
    try:
        assert get_settings().kimi_model == "kimi-k2.5"
    finally:
        get_settings.cache_clear()


def test_kimi_provider_uses_k2_5_temperature_requirement(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return _DummyResponse()

    monkeypatch.setenv("ANALYSIS_PROVIDER", "kimi")
    monkeypatch.setenv("KIMI_API_KEY", "test-kimi-key")
    monkeypatch.setenv("KIMI_MODEL", "kimi-k2.5")
    get_settings.cache_clear()
    monkeypatch.setattr(kimi_provider_module.httpx, "post", fake_post)
    try:
        provider = KimiProvider()
        analysis = provider.analyze(_question_event())
    finally:
        get_settings.cache_clear()

    assert analysis is not None
    assert captured["json"]["model"] == "kimi-k2.5"
    assert captured["json"]["temperature"] == 1.0
