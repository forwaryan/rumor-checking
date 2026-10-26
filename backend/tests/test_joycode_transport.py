from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import replace
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from backend.app.core.config import get_settings
from backend.app.services import agent_reasoner, joycode_transport, model_health
from backend.app.services.agent_reasoner import LlmAgentReasoner


def _settings(tmp_path):
    auth_file = tmp_path / "plugin-auth.json"
    auth_file.write_text(json.dumps({
        "joycode": {"type": "api", "key": "test-ticket", "metadata": {"tenant": "研究 组"}},
    }))
    return replace(
        get_settings(), joycode_models=("DeepSeek-V4.1-Flash",),
        joycode_base_url="https://gateway.test", joycode_sign_key="test-signing-key",
        joycode_auth_file=auth_file,
    )


def test_prepares_signed_request_with_authenticated_identity(monkeypatch, tmp_path):
    settings = _settings(tmp_path)
    calls = []

    def fake_post(url, *, headers, json, timeout):
        calls.append((url, headers, json, timeout))
        return httpx.Response(
            200, request=httpx.Request("POST", url),
            json={"code": 0, "data": {"userId": "account-1", "tenant": "研究 组"}},
        )

    monkeypatch.setattr(joycode_transport.httpx, "post", fake_post)
    monkeypatch.setattr(joycode_transport.time, "time", lambda: 123.456)
    body = {"model": "DeepSeek-V4.1-Flash", "messages": [{"role": "user", "content": "hi"}]}
    url, headers, payload = joycode_transport.prepare_joycode_request(settings, body, timeout=20)

    assert len(calls) == 1
    assert calls[0][1]["ptkey"] == "test-ticket"
    assert calls[0][1]["tenant"] == "%E7%A0%94%E7%A9%B6%20%E7%BB%84"
    assert "Authorization" not in headers
    assert payload == {**body, "userId": "account-1", "tenant": "研究 组", "orgFullName": "", "language": "UNKNOWN"}
    assert calls[0][2] == {}
    for signed_url, function_id in ((calls[0][0], "joycode_userInfo"), (url, "chat_completions")):
        parsed = urlparse(signed_url)
        fields = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        assert parsed.path == "/api"
        assert fields["functionId"] == function_id
        assert fields["t"] == "123456"
        material = "&".join(fields[key] for key in sorted(fields) if key != "sign")
        signature = hmac.new(b"test-signing-key", material.encode(), hashlib.sha256).hexdigest()
        assert fields["sign"] == signature


def test_rejects_missing_joycode_login_without_request(monkeypatch, tmp_path):
    settings = replace(_settings(tmp_path), joycode_auth_file=tmp_path / "missing.json")
    monkeypatch.setattr(joycode_transport.httpx, "post", lambda *a, **k: pytest.fail("must not request"))
    with pytest.raises(FileNotFoundError):
        joycode_transport.prepare_joycode_request(settings, {"model": "DeepSeek-V4.1-Flash"}, timeout=20)


def test_streamed_agent_uses_joycode_headers_without_bearer(monkeypatch, tmp_path):
    settings = replace(_settings(tmp_path), llm_api_key=None, agent_prompt_cache_enabled=True)
    reasoner = LlmAgentReasoner(settings=settings)
    seen = {}

    def prepare(_settings, body, *, timeout):
        seen["body"] = body
        return "https://gateway.test/api?signed=example", {"ptkey": "test-ticket"}, body

    class Stream:
        def __enter__(self):
            return httpx.Response(
                200, request=httpx.Request("POST", "https://gateway.test/api"),
                content=b'data: {"choices":[{"delta":{"content":"OK"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n',
            )

        def __exit__(self, *args):
            return False

    def stream(method, url, *, headers, json, timeout):
        seen.update(url=url, headers=headers)
        return Stream()

    monkeypatch.setattr(agent_reasoner, "prepare_joycode_request", prepare)
    monkeypatch.setattr(reasoner._client, "stream", stream)
    content = reasoner._stream_completion(
        endpoint="https://unused.test/chat/completions", model="DeepSeek-V4.1-Flash",
        system_prompt="You are helpful", user_prompt="Say OK",
    )
    assert content == "OK"
    assert seen["headers"] == {"ptkey": "test-ticket"}
    assert seen["body"]["messages"][0]["content"] == "You are helpful"
    assert "stream_options" not in seen["body"]


def test_joycode_only_skips_unavailable_bearer_models(tmp_path):
    settings = replace(_settings(tmp_path), analysis_provider="kimi", llm_api_key=None,
                       llm_model="DeepSeek-V4.1-Flash", llm_models=("other-gateway", "DeepSeek-V4.1-Flash"))
    reasoner = LlmAgentReasoner(settings=settings)
    assert reasoner.enabled
    assert reasoner._candidate_models("DeepSeek-V4.1-Flash") == ["DeepSeek-V4.1-Flash"]
    reasoner.model_override = "DeepSeek-V4.1-Flash"
    assert reasoner._candidate_models("DeepSeek-V4.1-Flash") == ["DeepSeek-V4.1-Flash"]


def test_one_shot_judge_uses_joycode_route(monkeypatch, tmp_path):
    settings = replace(_settings(tmp_path), llm_api_key=None, llm_model="DeepSeek-V4.1-Flash",
                       llm_models=("DeepSeek-V4.1-Flash",), llm_reasoning_models=())
    seen = {}

    def prepare(_settings, body, *, timeout):
        return "https://gateway.test/api?signed=example", {"ptkey": "test-ticket"}, body

    def post(url, *, headers, json, timeout):
        seen.update(url=url, headers=headers, model=json["model"])
        return httpx.Response(200, request=httpx.Request("POST", url),
                              json={"choices": [{"message": {"content": "OK"}}]})

    monkeypatch.setattr(model_health, "prepare_joycode_request", prepare)
    monkeypatch.setattr(model_health.httpx, "post", post)
    assert model_health.complete_once("sys", "user", settings=settings, temperature=0.1,
                                      max_tokens=64, timeout=20) == "OK"
    assert seen["model"] == "DeepSeek-V4.1-Flash"
    assert seen["headers"] == {"ptkey": "test-ticket"}


def test_rejects_identity_without_user_id(monkeypatch, tmp_path):
    settings = _settings(tmp_path)
    monkeypatch.setattr(
        joycode_transport.httpx, "post",
        lambda url, **k: httpx.Response(
            200, request=httpx.Request("POST", url), json={"code": 0, "data": {"tenant": "研究 组"}},
        ),
    )
    with pytest.raises(RuntimeError, match="identity is unavailable"):
        joycode_transport.prepare_joycode_request(settings, {"model": "DeepSeek-V4.1-Flash"}, timeout=20)
