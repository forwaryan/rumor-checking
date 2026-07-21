from __future__ import annotations

import backend.app.services.llm_provider as llm_provider_module
from backend.app.core.config import get_settings
from backend.app.models.schemas import NormalizedEvent
from backend.app.services.llm_provider import LlmStructuredProvider


class _DummyResponse:
    status_code = 200

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


def test_settings_trim_llm_model(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "  demo-model  ")
    get_settings.cache_clear()
    try:
        assert get_settings().llm_model == "demo-model"
    finally:
        get_settings.cache_clear()


def test_llm_provider_passes_configured_temperature(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return _DummyResponse()

    monkeypatch.setenv("ANALYSIS_PROVIDER", "kimi")
    monkeypatch.setenv("LLM_API_KEY", "test-llm-key")
    monkeypatch.setenv("LLM_MODEL", "demo-model")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.3")
    get_settings.cache_clear()
    monkeypatch.setattr(llm_provider_module.httpx, "post", fake_post)
    try:
        provider = LlmStructuredProvider()
        analysis = provider.analyze(_question_event())
    finally:
        get_settings.cache_clear()

    assert analysis is not None
    assert captured["json"]["model"] == "demo-model"
    assert captured["json"]["temperature"] == 0.3


def test_llm_provider_skips_broad_trend_questions(monkeypatch):
    def fail_post(*args, **kwargs):
        raise AssertionError("broad trend questions should not call analysis provider")

    monkeypatch.setenv("ANALYSIS_PROVIDER", "kimi")
    monkeypatch.setenv("LLM_API_KEY", "test-llm-key")
    get_settings.cache_clear()
    monkeypatch.setattr(llm_provider_module.httpx, "post", fail_post)
    try:
        provider = LlmStructuredProvider()
        analysis = provider.analyze(
            NormalizedEvent(
                summary="最近是不是有裁员",
                input_type="question_only",
                raw_input="最近是不是有裁员",
            )
        )
    finally:
        get_settings.cache_clear()

    assert analysis is None
