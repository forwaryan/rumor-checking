from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import replace

import httpx
import pytest

from backend.app.core.config import get_settings
from backend.app.models.schemas import ClaimResult, EvidenceItem, NormalizedEvent
from backend.app.services.llm_provider import LlmStructuredProvider
from backend.app.services.llm_verdict import llm_judge_claims
from backend.app.services.model_health import complete_once
from backend.app.services.progress import reset_progress_callback, set_progress_callback
from backend.app.services.retrieval_provider import LlmWebSearchProvider
from backend.app.services.run_control import (
    RunControl,
    RunStopped,
    check_run_control,
    get_run_control,
    reserve_llm_call,
    reset_run_control,
    set_run_control,
)


def test_control_cancellation_is_not_caught_as_an_analysis_error():
    control = RunControl(cancelled=lambda: True)
    with pytest.raises(RunStopped) as stopped:
        try:
            control.check()
        except Exception:
            pytest.fail("cancellation must bypass analysis fallback")
    assert stopped.value.reason == "user_cancelled"


def test_budget_reservations_are_atomic_across_parallel_calls():
    control = RunControl(max_llm_calls=2, max_tokens=20)

    def reserve():
        try:
            control.reserve(10)
            return True
        except RunStopped:
            return False

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda index: reserve(), range(8)))
    assert sum(results) == 2
    assert control.llm_calls == 2
    assert control.reserved_tokens == 20


def test_deadline_and_failed_control_lookup_stop_without_reserving():
    with pytest.raises(RunStopped, match="deadline_exceeded"):
        RunControl(deadline=20, clock=lambda: 21).reserve(1)

    def unavailable():
        raise OSError("unavailable")

    with pytest.raises(RunStopped, match="control_unavailable"):
        RunControl(cancelled=unavailable).reserve(1)


def test_persistent_reservation_failure_does_not_consume_local_budget():
    def reserve(amount):
        raise RunStopped("token_budget_exhausted")

    control = RunControl(reserve_callback=reserve)
    with pytest.raises(RunStopped):
        control.reserve(100)
    assert control.llm_calls == control.reserved_tokens == 0


def test_context_is_scoped_and_can_follow_existing_progress_callbacks():
    control = RunControl(max_llm_calls=1)
    token = set_run_control(control)
    try:
        reserve_llm_call(system_prompt="system", user_prompt="query", max_output_tokens=10)
        assert control.reserved_tokens >= 26
        with ThreadPoolExecutor(max_workers=1) as executor:
            assert executor.submit(copy_context().run, get_run_control).result() is control
    finally:
        reset_run_control(token)
    assert get_run_control() is None

    def callback(event):
        pass

    callback.run_control = control
    progress_token = set_progress_callback(callback)
    try:
        assert get_run_control() is control
        with pytest.raises(RunStopped, match="call_budget_exhausted"):
            reserve_llm_call(system_prompt="", user_prompt="", max_output_tokens=1)
    finally:
        reset_progress_callback(progress_token)
    check_run_control()


def test_call_budget_stops_model_failover_before_another_http_request(monkeypatch):
    settings = replace(get_settings(), llm_api_key="test-key", llm_model="first", llm_models=("first", "second"))
    requests = []

    def request(url, **kwargs):
        requests.append(kwargs["json"]["model"])
        return httpx.Response(503, request=httpx.Request("POST", url))

    monkeypatch.setattr("backend.app.services.model_health.httpx.post", request)
    control = RunControl(max_llm_calls=1)
    token = set_run_control(control)
    try:
        with pytest.raises(RunStopped, match="call_budget_exhausted"):
            complete_once("system", "query", settings=settings, temperature=0, max_tokens=10, timeout=1)
    finally:
        reset_run_control(token)
    assert requests == ["first"]


def test_structured_and_search_transports_share_the_same_budget(monkeypatch):
    settings = replace(get_settings(), llm_api_key="test-key", llm_model="test-model", llm_search_model="test-model")
    calls = []

    def request(url, **kwargs):
        calls.append(kwargs["json"])
        return httpx.Response(200, request=httpx.Request("POST", url), json={"choices": [{"message": {"content": "{}"}}]})

    monkeypatch.setattr(httpx, "post", request)
    control = RunControl(max_llm_calls=1)
    token = set_run_control(control)
    try:
        event = NormalizedEvent(raw_input="input", summary="input", input_type="text_news")
        assert LlmStructuredProvider(settings)._request_completion(event) == "{}"
        with pytest.raises(RunStopped, match="call_budget_exhausted"):
            LlmWebSearchProvider(settings)._request_completion([])
    finally:
        reset_run_control(token)
    assert len(calls) == 1
    assert calls[0]["max_tokens"] == settings.llm_max_tokens


def test_parallel_verdict_workers_inherit_control():
    evidence = EvidenceItem(title="proof", url="https://example.com/proof", source_name="source", published_at="", snippet="proof", relevance_reason="proof")
    claims = [ClaimResult(claim=claim, claim_type="fact", verdict="supported", confidence="high", evidence=[evidence], notes="") for claim in ("first", "second")]

    def completion(system_prompt, user_prompt):
        reserve_llm_call(system_prompt=system_prompt, user_prompt=user_prompt, max_output_tokens=100)
        return '{"verdict":"supported","confidence":"high","reason":"proof"}'

    control = RunControl(max_llm_calls=1)
    token = set_run_control(control)
    try:
        with pytest.raises(RunStopped, match="call_budget_exhausted"):
            llm_judge_claims(claims, completion_fn=completion)
    finally:
        reset_run_control(token)
    assert control.llm_calls == 1
