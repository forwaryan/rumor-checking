from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest

from backend.app.core.config import get_settings
from backend.app.services.agent_reasoner import LlmAgentReasoner


def _reasoner(**overrides) -> LlmAgentReasoner:
    settings = replace(
        get_settings(),
        analysis_provider="kimi",
        llm_api_key="test-key",
        llm_base_url="http://gateway.test/v1",
        **overrides,
    )
    return LlmAgentReasoner(settings=settings)


def _sse(*deltas: dict) -> bytes:
    """Build an OpenAI-style SSE body from a list of delta dicts."""
    lines = []
    for delta in deltas:
        lines.append("data: " + json.dumps({"choices": [{"delta": delta}]}, ensure_ascii=False))
    lines.append("data: [DONE]")
    return ("\n".join(lines) + "\n").encode("utf-8")


class _Capture:
    """Captures the request body handed to httpx.stream and replays a canned SSE."""

    def __init__(self, body: bytes):
        self.body = body
        self.sent_json: dict | None = None

    def __call__(self, method, url, *, headers, json, timeout):  # noqa: A002 - httpx kwarg name
        self.sent_json = json
        request = httpx.Request(method, url)
        response = httpx.Response(200, request=request, content=self.body)
        return _StreamCtx(response)


class _StreamCtx:
    def __init__(self, response: httpx.Response):
        self._response = response

    def __enter__(self) -> httpx.Response:
        return self._response

    def __exit__(self, *exc) -> bool:
        return False


def test_fast_model_pins_json_object_and_short_budget(monkeypatch):
    cap = _Capture(_sse({"content": '{"ok": true}'}))
    monkeypatch.setattr(httpx, "stream", cap)
    r = _reasoner(llm_model="fast-x", llm_max_tokens=4096, provider_timeout_seconds=30.0)

    out = r._stream_completion(
        endpoint="http://gateway.test/v1/chat/completions",
        model="fast-x",
        system_prompt="sys",
        user_prompt="usr",
    )
    assert out == '{"ok": true}'
    assert cap.sent_json["response_format"] == {"type": "json_object"}
    assert cap.sent_json["max_tokens"] == 4096


def test_reasoning_model_drops_json_object_and_uses_reasoning_budget(monkeypatch):
    cap = _Capture(_sse({"content": '{"ok": true}'}))
    monkeypatch.setattr(httpx, "stream", cap)
    r = _reasoner(
        llm_model="think-x",
        llm_reasoning_models=("think-x",),
        llm_reasoning_max_tokens=16000,
        llm_reasoning_timeout_seconds=200.0,
    )

    out = r._stream_completion(
        endpoint="http://gateway.test/v1/chat/completions",
        model="think-x",
        system_prompt="sys",
        user_prompt="usr",
    )
    assert out == '{"ok": true}'
    # json_object stalls reasoning models, so it must NOT be pinned.
    assert "response_format" not in cap.sent_json
    assert cap.sent_json["max_tokens"] == 16000


def test_reasoning_content_is_not_part_of_the_answer(monkeypatch):
    # The reasoning model streams a long chain-of-thought in reasoning_content
    # BEFORE the answer content. Only the content is the answer.
    cap = _Capture(
        _sse(
            {"reasoning_content": "让我想想……" * 10},
            {"reasoning_content": "继续推理……"},
            {"content": '{"verdict": '},
            {"content": '"supported"}'},
        )
    )
    monkeypatch.setattr(httpx, "stream", cap)
    r = _reasoner(llm_model="think-x", llm_reasoning_models=("think-x",))

    out = r._stream_completion(
        endpoint="http://gateway.test/v1/chat/completions",
        model="think-x",
        system_prompt="sys",
        user_prompt="usr",
    )
    assert out == '{"verdict": "supported"}'


def test_runaway_stream_is_cut_by_char_budget(monkeypatch):
    # A model that ignores max_tokens and floods content must be bounded by the
    # client-side char budget (llm_max_tokens * _STREAM_CHARS_PER_TOKEN).
    flood = [{"content": "x" * 1000} for _ in range(500)]  # 500k chars
    cap = _Capture(_sse(*flood))
    monkeypatch.setattr(httpx, "stream", cap)
    r = _reasoner(llm_model="fast-x", llm_max_tokens=1000)  # budget = 8000 chars

    out = r._stream_completion(
        endpoint="http://gateway.test/v1/chat/completions",
        model="fast-x",
        system_prompt="sys",
        user_prompt="usr",
    )
    # Cut off well before the full 500k flood.
    assert len(out) < 20000


def test_read_timeout_keeps_partial_content(monkeypatch):
    # If the stream stalls mid-answer, keep what arrived rather than losing it all.
    def raising_stream(method, url, *, headers, json, timeout):
        class _Ctx:
            def __enter__(self_inner):
                request = httpx.Request(method, url)

                class _Resp:
                    def raise_for_status(self_r):
                        return None

                    def iter_lines(self_r):
                        yield "data: " + __import__("json").dumps({"choices": [{"delta": {"content": '{"partial":'}}]})
                        raise httpx.ReadTimeout("stalled")

                return _Resp()

            def __exit__(self_inner, *exc):
                return False

        return _Ctx()

    monkeypatch.setattr(httpx, "stream", raising_stream)
    r = _reasoner(llm_model="fast-x")

    out = r._stream_completion(
        endpoint="http://gateway.test/v1/chat/completions",
        model="fast-x",
        system_prompt="sys",
        user_prompt="usr",
    )
    assert out == '{"partial":'


def test_reasoning_model_retries_on_empty_content(monkeypatch):
    # The gateway's reasoning model intermittently stalls with empty content. An
    # empty return is retried up to llm_reasoning_retries times; the first
    # non-empty answer wins.
    calls = {"n": 0}

    def flaky(*, endpoint, model, system_prompt, user_prompt):
        calls["n"] += 1
        return "" if calls["n"] < 2 else '{"verdict": "supported"}'

    r = _reasoner(llm_model="think-x", llm_reasoning_models=("think-x",), llm_reasoning_retries=2)
    monkeypatch.setattr(r, "_stream_completion", flaky)

    out = r._request_completion(stage_key="s", title="t", system_prompt="sys", user_prompt="usr")
    assert out == '{"verdict": "supported"}'
    assert calls["n"] == 2  # one retry after the empty first attempt


def test_empty_completion_is_retried_regardless_of_model(monkeypatch):
    # Empties happen to fast models too — the heavy synthesis prompt times out
    # mid-answer (observed in real runs). So a fast model's empty output is retried
    # up to llm_reasoning_retries times, same as a reasoning model's.
    calls = {"n": 0}

    def flaky(*, endpoint, model, system_prompt, user_prompt):
        calls["n"] += 1
        return "" if calls["n"] < 3 else '{"ok": true}'

    r = _reasoner(llm_model="fast-x", llm_reasoning_retries=2)
    monkeypatch.setattr(r, "_stream_completion", flaky)

    out = r._request_completion(stage_key="s", title="t", system_prompt="sys", user_prompt="usr")
    assert out == '{"ok": true}'
    assert calls["n"] == 3  # two retries after the two empty attempts


def test_retries_are_capped_at_configured_count(monkeypatch):
    # A persistently-empty model stops after llm_reasoning_retries + 1 attempts.
    calls = {"n": 0}

    def always_empty(*, endpoint, model, system_prompt, user_prompt):
        calls["n"] += 1
        return ""

    r = _reasoner(llm_model="fast-x", llm_reasoning_retries=2)
    monkeypatch.setattr(r, "_stream_completion", always_empty)

    out = r._request_completion(stage_key="s", title="t", system_prompt="sys", user_prompt="usr")
    assert out == ""
    assert calls["n"] == 3  # 1 initial + 2 retries, then give up


