from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import replace

import httpx
import pytest

from backend.app.agent.trace import TraceExporter
from backend.app.core.config import get_settings
from backend.app.services import model_ledger
from backend.app.services.agent_reasoner import LlmAgentReasoner
from backend.app.services.model_call_observer import (
    model_call_attempt,
    model_observation_run,
    normalize_usage,
    observe_model_call,
)


@pytest.fixture
def settings(tmp_path):
    model_ledger._reset_for_tests()
    yield replace(get_settings(), model_ledger_enabled=True, model_ledger_dir=tmp_path,
                  analysis_provider="kimi", llm_api_key="private-test-secret", llm_model="test-model")
    model_ledger._reset_for_tests()


def _entries(settings):
    return [json.loads(line) for path in settings.model_ledger_dir.glob('*.jsonl') for line in path.read_text().splitlines()]


def _body(text="private prompt"):
    return {"model": "test-model", "messages": [{"role": "system", "content": "private system"},
                                                  {"role": "user", "content": text}]}


@pytest.mark.parametrize(("raw", "expected"), [
    (None, {}), ({}, {}),
    ({"prompt_tokens": 0, "completion_tokens": 0}, {"prompt": 0, "completion": 0, "total": 0}),
    ({"prompt_tokens": True, "completion_tokens": -1, "total_tokens": "4"}, {}),
    ({"prompt_tokens": 10, "completion_tokens": 3, "prompt_tokens_details": {"cached_tokens": 8}},
     {"prompt": 10, "completion": 3, "total": 13, "cache_read": 8}),
    ({"input_tokens": 10, "output_tokens": 2, "cached_tokens": 3},
     {"prompt": 10, "completion": 2, "total": 12, "cache_read": 3}),
    ({"prompt_tokens": 10, "completion_tokens": 2, "prompt_cache_hit_tokens": 6},
     {"prompt": 10, "completion": 2, "total": 12, "cache_read": 6}),
])
def test_usage_unknown_zero_and_cached_input_are_distinct(raw, expected):
    assert normalize_usage(raw) == expected


def test_context_changes_and_trace_ledger_correlation_without_content(settings):
    exporter = TraceExporter("run-one")
    with model_observation_run("run-one"), exporter.activate(), exporter.span("agent.research") as parent:
        for attempt, text in enumerate(("private prompt", "private prompt", "changed private prompt"), 1):
            with model_call_attempt("research", attempt), observe_model_call(
                settings=settings, provider="llm", model="test-model", request=_body(text),
            ) as call:
                call.response({"choices": [{"message": {"content": "private response"}}]}, status_code=200)
    spans = [span for span in exporter.record.spans if span.metadata.get("span_kind") == "LLM"]
    assert [span.metadata["context"]["changed"] for span in spans] == [None, False, True]
    assert spans[-1].metadata["context"]["changed_fields"] == ["messages"]
    assert all(span.parent_span_id == parent.span_id for span in spans)
    assert all(not span.metadata["usage_reported"] and span.token_usage == {} for span in spans)
    entries = _entries(settings)
    assert [entry["attempt"] for entry in entries] == [1, 2, 3]
    assert [entry["call_id"] for entry in entries] == [span.metadata["call_id"] for span in spans]
    assert all(entry["trace_id"] == "run-one" and entry["parent_span_id"] == parent.span_id for entry in entries)
    assert all(entry["usage_reported"] is False and entry["total_tokens"] is None for entry in entries)
    exported = exporter.record.to_json() + json.dumps(entries)
    for secret in ("private prompt", "private system", "private response", "private-test-secret"):
        assert secret not in exported
    with model_observation_run("run-two"), exporter.activate():
        with observe_model_call(settings=settings, provider="llm", model="test-model", request=_body()) as call:
            assert call.context["changed"] is None


def test_ledger_and_trace_failures_do_not_change_response_or_mask_error(settings, monkeypatch):
    exporter = TraceExporter("run-fail-sinks")
    def broken(*args, **kwargs):
        raise OSError("private sink failure")
    monkeypatch.setattr(exporter, "record_child_span", broken)
    with exporter.activate():
        with observe_model_call(settings=settings, provider="llm", model="test-model", request=_body()) as call:
            call.response({"choices": [{"message": {"content": "OK"}}]})
    assert _entries(settings)[0]["status"] == "ok"
    monkeypatch.setattr(model_ledger.ModelLedger, "append", broken)
    original = ValueError("private original error")
    with exporter.activate(), pytest.raises(ValueError) as caught:
        with observe_model_call(settings=settings, provider="llm", model="test-model", request=_body()):
            raise original
    assert caught.value is original


def test_sse_usage_only_chunk_and_choice_usage_and_tool_fragments(settings):
    exporter = TraceExporter("sse")
    with exporter.activate(), observe_model_call(settings=settings, provider="llm", model="test-model", request=_body()) as call:
        call.chunk({"choices": [{"delta": {"reasoning_content": "private reasoning"}}]})
        for text in ('{"q":', '"private"}'):
            call.chunk({"choices": [{"index": 0, "delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": text}},
            ]}}]})
        call.chunk({"choices": [{"delta": {"content": "OK"}, "usage": {"prompt_tokens": 10}}]})
        call.chunk({"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 2,
                                              "prompt_tokens_details": {"cached_tokens": 4}}})
    span = exporter.record.spans[0]
    assert span.token_usage == {"prompt": 10, "completion": 2, "total": 12, "cache_read": 4}
    assert span.metadata["tool_call_count"] == 1
    assert span.metadata["response_chars"] == 2
    assert span.metadata["first_token_ms"] >= 0
    assert exporter.record.total_tokens == 12


@pytest.mark.parametrize("mode", ["success", "network", "timeout", "no_usage", "length", "early_eof"])
def test_real_reasoner_stream_attempts_are_observed(settings, monkeypatch, mode):
    reasoner = LlmAgentReasoner(settings=settings)
    captured = []
    usage_callbacks = []
    reasoner._on_token_usage = lambda *counts: usage_callbacks.append(counts)
    @contextmanager
    def stream(method, url, **kwargs):
        captured.append(kwargs["json"])
        if mode == "network":
            raise httpx.ConnectError("private endpoint and key")
        if mode == "timeout":
            raise httpx.ReadTimeout("private endpoint and key")
        chunks = [{"choices": [{"delta": {"content": "OK"}, "finish_reason": "length" if mode == "length" else "stop"}]}]
        if mode != "no_usage":
            chunks.append({"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9}})
        if mode == "early_eof":
            chunks = [{"choices": [{"delta": {"content": "OK"}}]}]
        data = ''.join('data: ' + json.dumps(c) + '\n\n' for c in chunks) + ('' if mode == 'early_eof' else 'data: [DONE]\n\n')
        yield httpx.Response(200, request=httpx.Request(method, url), text=data)
    monkeypatch.setattr(reasoner._client, "stream", stream)
    exporter = TraceExporter("reasoner-run")
    with model_observation_run("reasoner-run"), exporter.activate(), model_call_attempt("investigation", 2):
        result = reasoner._stream_completion(endpoint="https://private.example/v1/chat/completions", model="test-model",
                                             system_prompt="private system", user_prompt="private prompt")
    assert result == ("" if mode in {"network", "timeout"} else "OK")
    assert captured[0]["stream_options"] == {"include_usage": True}
    entry = _entries(settings)[0]
    expected_status = {"network": "error", "timeout": "truncated", "length": "truncated", "early_eof": "truncated"}.get(mode, "ok")
    assert entry["status"] == expected_status
    assert entry["attempt"] == 2 and entry["stage_key"] == "investigation"
    assert exporter.record.spans[0].success == (expected_status == "ok")
    assert "private" not in json.dumps(entry) + exporter.record.to_json()
    if mode in {"success", "length"}:
        assert usage_callbacks == [(7, 2, 9)]
    elif mode == "no_usage":
        assert entry["usage_reported"] is False and usage_callbacks == []


def test_stream_usage_request_can_be_disabled_for_legacy_gateway(settings, monkeypatch):
    reasoner = LlmAgentReasoner(settings=replace(settings, llm_stream_include_usage=False))
    @contextmanager
    def stream(method, url, **kwargs):
        assert "stream_options" not in kwargs["json"]
        yield httpx.Response(200, request=httpx.Request(method, url), text='data: [DONE]\n\n')
    monkeypatch.setattr(reasoner._client, "stream", stream)
    assert reasoner._stream_completion(endpoint="https://example.com/chat/completions", model="test-model",
                                       system_prompt="sys", user_prompt="user") == ""


def test_partial_usage_updates_recompute_total_and_preserve_explicit_total(settings):
    with observe_model_call(settings=settings, provider="llm", model="test-model", request=_body()) as call:
        call.chunk({"usage": {"prompt_tokens": 10, "completion_tokens": 1}})
        assert call.usage["total"] == 11
        call.chunk({"usage": {"completion_tokens": 2}})
        assert call.usage == {"prompt": 10, "completion": 2, "total": 12}
        call.chunk({"usage": {"completion_tokens": 3, "total_tokens": 15}})
        assert call.usage["total"] == 15
        call.chunk({"usage": {"cached_tokens": 8}})
        assert call.usage["total"] == 15


@pytest.mark.parametrize("delta", [None, {}])
def test_length_finish_without_content_is_still_truncated(settings, delta):
    exporter = TraceExporter("length-only")
    with exporter.activate(), observe_model_call(settings=settings, provider="llm", model="test-model", request=_body()) as call:
        call.chunk({"choices": [{"delta": {"content": "partial"}}]})
        call.chunk({"choices": [{"delta": delta, "finish_reason": "length"}]})
    assert exporter.record.spans[0].metadata["status"] == "truncated"
    assert not exporter.record.spans[0].success
