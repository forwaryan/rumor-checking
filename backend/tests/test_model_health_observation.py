"""Shared verdict/correction transport records each actual HTTP attempt."""
import json
from dataclasses import replace
from threading import Barrier

import httpx
import pytest

from backend.app.agent.trace import TraceExporter
from backend.app.core.config import get_settings
from backend.app.models.schemas import ClaimResult, EvidenceItem
from backend.app.services import model_health, model_ledger
from backend.app.services.llm_verdict import llm_judge_claims
from backend.app.services.model_health import complete_once
from backend.app.services.run_control import RunControl, RunStopped, reset_run_control, set_run_control

SECRET = "TEST_PRIVATE_PROMPT_KEY_ENDPOINT_RESPONSE_SENTINEL"


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setattr(model_health, "_registry", None)
    monkeypatch.setattr(model_ledger, "_ledger", None)
    return replace(get_settings(), llm_api_key=SECRET, llm_model="first", llm_models=("first", "second"),
                   llm_reasoning_models=(), model_ledger_enabled=True, model_ledger_dir=tmp_path)


def complete(settings, **kwargs):
    return complete_once(SECRET, SECRET, settings=settings, temperature=0, max_tokens=32,
                         timeout=1, stage_key="llm_verdict", **kwargs)


def response(content="answer", *, status=200, usage=None, reasoning=""):
    body = {"choices": [{"message": {"content": content, "reasoning_content": reasoning}}]}
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(status, json=body)


def test_failover_records_http_error_and_usage_with_shared_parent_and_safe_ledger(settings, monkeypatch):
    def post(url, **kwargs):
        if kwargs["json"]["model"] == "first":
            return response(SECRET, status=503)
        return response(SECRET, usage={"prompt_tokens": 20, "completion_tokens": 3,
                                       "prompt_tokens_details": {"cached_tokens": 4}})

    monkeypatch.setattr(model_health.httpx, "post", post)
    exporter = TraceExporter("judge")
    with exporter.span("judge.parent") as parent:
        assert complete(settings) == SECRET
    calls = [s for s in exporter.record.spans if s.metadata.get("span_kind") == "LLM"]
    assert len(calls) == 2
    assert [s.metadata["attempt"] for s in calls] == [1, 2]
    assert [s.metadata["status"] for s in calls] == ["error", "ok"]
    assert calls[0].metadata["status_code"] == 503 and calls[0].error_type == "HTTPStatusError"
    assert calls[1].token_usage == {"prompt": 20, "completion": 3, "cache_read": 4, "total": 23}
    assert all(s.parent_span_id == parent.span_id and s.metadata["stage_key"] == "llm_verdict" for s in calls)
    assert len({s.metadata["call_id"] for s in calls}) == 2
    ledger = "".join(p.read_text() for p in settings.model_ledger_dir.glob("*.jsonl"))
    records = [json.loads(line) for line in ledger.splitlines()]
    assert len(records) == 2 and records[1]["total_tokens"] == 23
    assert SECRET not in ledger and SECRET not in exporter.record.to_json()


@pytest.mark.parametrize("kind,status,error_class", [
    ("timeout", "error", "TimeoutError"), ("malformed", "error", "KeyError"),
    ("empty", "empty", None), ("reasoning_unused", "empty", None),
])
def test_unusable_attempts_record_failure_or_empty_before_failover(settings, monkeypatch, kind, status, error_class):
    def post(url, **kwargs):
        if kwargs["json"]["model"] == "second":
            return response(usage={"prompt_tokens": 0, "completion_tokens": 0})
        if kind == "timeout":
            raise TimeoutError(SECRET)
        if kind == "malformed":
            return httpx.Response(200, json={"private": SECRET})
        return response("   ", reasoning=SECRET if kind == "reasoning_unused" else "")

    monkeypatch.setattr(model_health.httpx, "post", post)
    exporter = TraceExporter("failover")
    with exporter.activate():
        assert complete(settings) == "answer"
    first, second = exporter.record.spans
    assert first.metadata["status"] == status and first.error_type == error_class
    assert first.error_message is None and first.metadata["usage_reported"] is False
    assert second.metadata["usage_reported"] is True and second.token_usage["total"] == 0
    assert SECRET not in exporter.record.to_json()


def test_opt_in_reasoning_fallback_is_observed_as_usable(settings, monkeypatch):
    monkeypatch.setattr(model_health.httpx, "post", lambda *a, **kw: response("", reasoning=f"{SECRET}\nanswer"))
    exporter = TraceExporter("reasoning")
    with exporter.activate():
        assert complete(settings, include_reasoning=True) == "answer"
    assert len(exporter.record.spans) == 1
    span = exporter.record.spans[0]
    assert span.metadata["status"] == "ok" and span.metadata["response_chars"] == 0
    assert span.metadata["reasoning_chars"] > 0


def test_budget_rejection_does_not_create_phantom_attempt(settings, monkeypatch):
    monkeypatch.setattr(model_health.httpx, "post", lambda *a, **kw: response(status=503))
    control = RunControl(max_llm_calls=1)
    token = set_run_control(control)
    exporter = TraceExporter("budget")
    try:
        with exporter.activate(), pytest.raises(RunStopped, match="call_budget_exhausted"):
            complete(settings)
    finally:
        reset_run_control(token)
    assert len(exporter.record.spans) == control.llm_calls == 1
    assert exporter.record.spans[0].metadata["attempt"] == 1


def test_actual_parallel_judge_path_inherits_trace_and_records_every_judgment(settings, monkeypatch):
    barrier = Barrier(2)

    def post(url, **kwargs):
        barrier.wait(timeout=5)
        return response(json.dumps({"verdict": "refuted", "confidence": "high", "reason": "evidence"}),
                        usage={"prompt_tokens": 7, "completion_tokens": 2})

    monkeypatch.setattr(model_health.httpx, "post", post)
    evidence = EvidenceItem(title=SECRET, url="https://example.org/article", source_name="source",
                            published_at="2026-09-01", snippet=SECRET, relevance_reason="r", source_tier="A")
    claims = [ClaimResult(claim=f"{SECRET}{i}", claim_type="fact", verdict="insufficient", confidence="low",
                          evidence=[evidence], notes="") for i in range(2)]
    exporter = TraceExporter("judge-workers")
    with exporter.span("verdict") as parent:
        result = llm_judge_claims(claims, settings=settings)
    assert all(claim.verdict == "refuted" for claim in result)
    calls = [s for s in exporter.record.spans if s.metadata.get("span_kind") == "LLM"]
    assert len(calls) == 2 and all(s.parent_span_id == parent.span_id for s in calls)
    assert all(s.metadata["stage_key"] == "llm_verdict" and s.token_usage["total"] == 9 for s in calls)
    assert exporter.record.total_tokens == 18
    assert SECRET not in exporter.record.to_json()
