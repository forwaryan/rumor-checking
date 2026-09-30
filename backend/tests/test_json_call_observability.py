from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest

from backend.app.core.config import get_settings
from backend.app.models.schemas import NormalizedEvent
from backend.app.services import model_ledger
from backend.app.services.llm_provider import LlmStructuredProvider
from backend.app.services.retrieval_provider import LlmWebSearchProvider


@pytest.fixture
def observed_settings(tmp_path):
    model_ledger._reset_for_tests()
    settings = replace(
        get_settings(),
        llm_api_key="private-test-key",
        llm_model="test-model",
        llm_search_model="test-search-model",
        model_ledger_enabled=True,
        model_ledger_dir=tmp_path,
    )
    yield settings
    model_ledger._reset_for_tests()


def _invoke(provider, settings):
    if provider == "structured":
        event = NormalizedEvent(raw_input="private-user-input", summary="input", input_type="text_news")
        return LlmStructuredProvider(settings)._request_completion(event)
    return LlmWebSearchProvider(settings)._request_completion([
        {"role": "user", "content": "private-user-input"},
    ])


def _records(settings):
    return [
        json.loads(line)
        for path in settings.model_ledger_dir.glob("model-calls-*.jsonl")
        for line in path.read_text().splitlines()
    ]


@pytest.mark.parametrize("provider", ["structured", "web_search"])
def test_json_transports_record_reported_usage_without_content(monkeypatch, observed_settings, provider):
    message = {"content": "private-model-answer"}

    def post(url, **kwargs):
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "choices": [{"message": message}],
            "usage": {
                "prompt_tokens": 42,
                "completion_tokens": 11,
                "prompt_tokens_details": {"cached_tokens": 7},
            },
        })

    monkeypatch.setattr(httpx, "post", post)
    result = _invoke(provider, observed_settings)
    assert result == (message["content"] if provider == "structured" else message)
    [record] = _records(observed_settings)
    assert record["provider"] == provider
    assert record["stage_key"] == ("provider_enrichment" if provider == "structured" else "retrieval_initial")
    assert record["status"] == "ok"
    assert record["input_tokens"] == 42
    assert record["output_tokens"] == 11
    assert record["cache_tokens"] == 7
    assert record["total_tokens"] == 53
    assert record["usage_reported"] is True
    assert record["call_id"]
    serialized = json.dumps(record)
    for private_value in ("private-user-input", "private-model-answer", "private-test-key"):
        assert private_value not in serialized


@pytest.mark.parametrize("provider", ["structured", "web_search"])
@pytest.mark.parametrize("failure", ["http", "network", "message", "json"])
def test_json_transport_failures_are_recorded_and_propagated(monkeypatch, observed_settings, provider, failure):
    def post(url, **kwargs):
        request = httpx.Request("POST", url)
        if failure == "network":
            raise httpx.ConnectError("private-network-error", request=request)
        if failure == "http":
            return httpx.Response(429, request=request, text="private-server-body")
        if failure == "json":
            return httpx.Response(200, request=request, text="private-invalid-json")
        return httpx.Response(200, request=request, json={"choices": [{"message": None}]})

    monkeypatch.setattr(httpx, "post", post)
    expected_error = {
        "http": httpx.HTTPStatusError,
        "network": httpx.ConnectError,
        "json": json.JSONDecodeError,
        "message": AttributeError if provider == "structured" else ValueError,
    }[failure]
    with pytest.raises(expected_error):
        _invoke(provider, observed_settings)
    [record] = _records(observed_settings)
    assert record["status"] == "error"
    assert record["error_class"] == expected_error.__name__
    assert "private-" not in json.dumps(record)
