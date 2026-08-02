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
        self.sent_timeout: float | None = None

    def __call__(self, method, url, *, headers, json, timeout):  # noqa: A002 - httpx kwarg name
        self.sent_json = json
        self.sent_timeout = timeout
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


def test_fast_model_drops_json_object_and_uses_short_budget(monkeypatch):
    # json_object makes V4-Flash slow-trickle to the deadline and truncate on this
    # gateway, so we no longer pin it for fast models either. The fast model keeps
    # its modest max_tokens budget.
    cap = _Capture(_sse({"content": '{"ok": true}'}))
    r = _reasoner(llm_model="fast-x", llm_max_tokens=4096, provider_timeout_seconds=30.0)
    monkeypatch.setattr(r._client, "stream", cap)

    out = r._stream_completion(
        endpoint="http://gateway.test/v1/chat/completions",
        model="fast-x",
        system_prompt="sys",
        user_prompt="usr",
    )
    assert out == '{"ok": true}'
    assert "response_format" not in cap.sent_json
    assert cap.sent_json["max_tokens"] == 4096


def test_timeout_multiplier_extends_the_deadline(monkeypatch):
    # Synthesis passes a >1 multiplier so its heavy JSON body gets more wall-clock
    # than the short planner/investigation calls (which use multiplier 1.0).
    cap = _Capture(_sse({"content": '{"ok": true}'}))
    r = _reasoner(llm_model="think-x", llm_reasoning_models=("think-x",), llm_reasoning_timeout_seconds=200.0)
    monkeypatch.setattr(r._client, "stream", cap)

    r._stream_completion(
        endpoint="http://gateway.test/v1/chat/completions",
        model="think-x",
        system_prompt="sys",
        user_prompt="usr",
        timeout_multiplier=1.5,
    )
    assert cap.sent_timeout == 300.0  # 200 * 1.5


def test_timeout_multiplier_defaults_to_base(monkeypatch):
    cap = _Capture(_sse({"content": '{"ok": true}'}))
    r = _reasoner(llm_model="think-x", llm_reasoning_models=("think-x",), llm_reasoning_timeout_seconds=200.0)
    monkeypatch.setattr(r._client, "stream", cap)

    r._stream_completion(
        endpoint="http://gateway.test/v1/chat/completions",
        model="think-x",
        system_prompt="sys",
        user_prompt="usr",
    )
    assert cap.sent_timeout == 200.0  # no multiplier -> base deadline


def test_reasoning_model_drops_json_object_and_uses_reasoning_budget(monkeypatch):
    cap = _Capture(_sse({"content": '{"ok": true}'}))
    r = _reasoner(
        llm_model="think-x",
        llm_reasoning_models=("think-x",),
        llm_reasoning_max_tokens=16000,
        llm_reasoning_timeout_seconds=200.0,
    )
    monkeypatch.setattr(r._client, "stream", cap)

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
    r = _reasoner(llm_model="think-x", llm_reasoning_models=("think-x",))
    monkeypatch.setattr(r._client, "stream", cap)

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
    r = _reasoner(llm_model="fast-x", llm_max_tokens=1000)  # budget = 8000 chars
    monkeypatch.setattr(r._client, "stream", cap)

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

    r = _reasoner(llm_model="fast-x")
    monkeypatch.setattr(r._client, "stream", raising_stream)

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

    def flaky(*, endpoint, model, system_prompt, user_prompt, **_):
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
    # up to llm_reasoning_retries times, same as a reasoning model's. Use a
    # multi-candidate pool so each retry rotates to a fresh model and the
    # single-candidate empty-streak short-circuit does NOT apply (that short-circuit
    # is exercised by test_empty_streak_shortcircuits_when_only_one_candidate).
    calls = {"n": 0}

    def flaky(*, endpoint, model, system_prompt, user_prompt, **_):
        calls["n"] += 1
        return "" if calls["n"] < 3 else '{"ok": true}'

    r = _reasoner(
        llm_model="m-a",
        llm_models=("m-a", "m-b", "m-c"),
        llm_reasoning_retries=2,
    )
    monkeypatch.setattr(r, "_stream_completion", flaky)

    out = r._request_completion(stage_key="s", title="t", system_prompt="sys", user_prompt="usr")
    assert out == '{"ok": true}'
    assert calls["n"] == 3  # two retries after the two empty attempts


def test_retries_are_capped_at_configured_count(monkeypatch):
    # A persistently-empty pool stops after llm_reasoning_retries + 1 attempts.
    # Same as above: use multiple candidates so the empty-streak short-circuit
    # (single-candidate specialization) does not fire before the budget is spent.
    calls = {"n": 0}

    def always_empty(*, endpoint, model, system_prompt, user_prompt, **_):
        calls["n"] += 1
        return ""

    r = _reasoner(
        llm_model="m-a",
        llm_models=("m-a", "m-b", "m-c"),
        llm_reasoning_retries=2,
    )
    monkeypatch.setattr(r, "_stream_completion", always_empty)

    out = r._request_completion(stage_key="s", title="t", system_prompt="sys", user_prompt="usr")
    assert out == ""
    assert calls["n"] == 3  # 1 initial + 2 retries, then give up


def test_failover_spends_shared_budget_across_candidates(monkeypatch):
    # The borrowed HappyClaw failover spends the SAME retry budget across models
    # rather than multiplying it: with 3 candidates and retries=2 (budget 3), an
    # empty first model advances to the next candidate on each retry — total 3
    # calls, one per candidate, NOT 3-per-model.
    seen: list[str] = []

    def empty_then_answer(*, endpoint, model, system_prompt, user_prompt, **_):
        seen.append(model)
        return '{"ok": true}' if model == "m-c" else ""

    r = _reasoner(
        llm_model="m-a",
        llm_models=("m-a", "m-b", "m-c"),
        llm_reasoning_retries=2,
    )
    monkeypatch.setattr(r, "_stream_completion", empty_then_answer)

    out = r._request_completion(stage_key="s", title="t", system_prompt="sys", user_prompt="usr")
    assert out == '{"ok": true}'
    assert seen == ["m-a", "m-b", "m-c"]  # switched models each attempt, one call each


def test_picker_override_never_fails_over(monkeypatch):
    # A per-request picker override pins one model: any attempt in the budget
    # retries THAT model, never switching to another candidate. When the
    # override keeps returning empty the empty-streak short-circuit may end
    # the loop early — that's fine (and desirable). The essential guarantee
    # under test is that we never silently route around a user-chosen model.
    seen: list[str] = []

    def always_empty(*, endpoint, model, system_prompt, user_prompt, **_):
        seen.append(model)
        return ""

    r = _reasoner(
        llm_model="m-a",
        llm_models=("m-a", "m-b", "m-c"),
        llm_reasoning_retries=2,
    )
    r.model_override = "picked-x"
    monkeypatch.setattr(r, "_stream_completion", always_empty)

    out = r._request_completion(stage_key="s", title="t", system_prompt="sys", user_prompt="usr")
    assert out == ""
    # Every observed call must be against the pinned model; no failover to
    # any of the whitelisted alternates.
    assert seen  # at least one call happened
    assert all(model == "picked-x" for model in seen)
    assert "m-a" not in seen and "m-b" not in seen and "m-c" not in seen


def test_empty_streak_shortcircuits_when_only_one_candidate(monkeypatch):
    """When there is only one candidate (either via picker-override or a
    single-model deployment) and it keeps returning empty, further retries
    are wasted wall-clock. After 2 consecutive empty returns the loop must
    bail out so the pipeline drops to the rule fallback in seconds, not
    minutes. This is the 耿同学/Nature 撤稿 case where GLM-5.2 was the only
    candidate and burned 2m 40s on one planner call before giving up."""
    seen: list[str] = []

    def always_empty(*, endpoint, model, system_prompt, user_prompt, **_):
        seen.append(model)
        return ""

    r = _reasoner(
        llm_model="only-one",
        llm_models=("only-one",),
        llm_reasoning_retries=4,  # budget of 5; without short-circuit we'd see 5 calls
    )
    monkeypatch.setattr(r, "_stream_completion", always_empty)
    out = r._request_completion(stage_key="s", title="t", system_prompt="sys", user_prompt="usr")
    assert out == ""
    # 2 empty returns = trigger the short-circuit. The exact count is 2 attempts,
    # not the full 5-attempt budget.
    assert len(seen) == 2


def test_empty_streak_does_not_shortcircuit_when_rotation_is_possible(monkeypatch):
    """When candidates rotate (multiple models available), the short-circuit
    must NOT fire — an empty return on m-a is not evidence that m-b will
    also fail. Rotation is the point of a failover pool."""
    seen: list[str] = []

    def always_empty(*, endpoint, model, system_prompt, user_prompt, **_):
        seen.append(model)
        return ""

    r = _reasoner(
        llm_model="m-a",
        llm_models=("m-a", "m-b", "m-c"),
        llm_reasoning_retries=2,  # 3 attempts total
    )
    monkeypatch.setattr(r, "_stream_completion", always_empty)
    r._request_completion(stage_key="s", title="t", system_prompt="sys", user_prompt="usr")
    # Full 3-attempt budget consumed because each attempt rotates to a fresh
    # candidate — the short-circuit only fires when the NEXT candidate is
    # the same as the current one.
    assert len(seen) == 3


def test_unparseable_completion_is_retried_when_validator_supplied(monkeypatch):
    # The run-3 bug: a fast model returns a NON-empty but truncated JSON fragment
    # (stream dropped mid-answer). Without a validator the truthy fragment breaks
    # the loop, fails to parse, and drops the whole run to the rule fallback. With
    # an is_valid validator, the bad fragment is retried like an empty one.
    calls = {"n": 0}

    def flaky(*, endpoint, model, system_prompt, user_prompt, **_):
        calls["n"] += 1
        # First attempt: truncated fragment (what V4-Flash actually returned).
        if calls["n"] < 2:
            return '{ "event": { "title": "x", "summary": "拼'
        return '{"claims": [{"claim": "c"}]}'

    r = _reasoner(llm_model="fast-x", llm_reasoning_retries=2)
    monkeypatch.setattr(r, "_stream_completion", flaky)

    out = r._request_completion(
        stage_key="s",
        title="t",
        system_prompt="sys",
        user_prompt="usr",
        is_valid=r._synthesis_content_usable,
    )
    assert out == '{"claims": [{"claim": "c"}]}'
    assert calls["n"] == 2  # retried once after the truncated fragment


def test_nonempty_completion_accepted_without_validator(monkeypatch):
    # Callers that pass no validator (planner, investigation, question-resolution)
    # keep the original behavior: any non-empty completion is accepted on attempt 1,
    # even if it is not valid JSON — their own lenient parsers handle recovery.
    calls = {"n": 0}

    def once(*, endpoint, model, system_prompt, user_prompt, **_):
        calls["n"] += 1
        return "not json but non-empty"

    r = _reasoner(llm_model="fast-x", llm_reasoning_retries=2)
    monkeypatch.setattr(r, "_stream_completion", once)

    out = r._request_completion(stage_key="s", title="t", system_prompt="sys", user_prompt="usr")
    assert out == "not json but non-empty"
    assert calls["n"] == 1  # no retry — no validator means non-empty is enough


def test_synthesis_content_usable_rejects_truncated_and_claimless():
    r = _reasoner(llm_model="fast-x")
    # A cut before ANY nested element closes has nothing to recover.
    assert r._synthesis_content_usable('{ "event": { "summary": "拼') is False
    # Parseable but carries no claims -> not usable for synthesis.
    assert r._synthesis_content_usable('{"event": {"title": "x"}, "claims": []}') is False
    # A well-formed object with at least one claim is usable.
    assert r._synthesis_content_usable('{"claims": [{"claim": "c"}]}') is True


def test_synthesis_content_usable_accepts_recoverable_truncation():
    # After the lenient parser learned to salvage complete elements, a stream cut
    # mid-third-claim is usable — the two finished claims are recovered rather than
    # dropping the whole run to the rule fallback.
    r = _reasoner(llm_model="fast-x")
    frag = (
        '{"claims": [{"claim": "拼多多买了5栋楼", "verdict": "insufficient"}, '
        '{"claim": "拼多多招了6000研发", "verdict": "insufficient"}, '
        '{"claim": "拼多多在雄安扩招", "truth_probability":'
    )
    assert r._synthesis_content_usable(frag) is True


def test_synthesis_model_defaults_to_the_reasoning_model_when_unset():
    # LLM_SYNTHESIS_MODEL blank -> synthesis uses the same model as everything else.
    r = _reasoner(llm_model="fast-x", llm_synthesis_model="")
    assert r._synthesis_model() == "fast-x"


def test_synthesis_model_routes_only_synthesis_when_set():
    # Set -> synthesis goes to the opt-in model, planner/investigation stay on fast.
    r = _reasoner(llm_model="fast-x", llm_synthesis_model="think-x")
    assert r._synthesis_model() == "think-x"
    assert r._reasoning_model() == "fast-x"


def test_per_request_override_wins_over_synthesis_model():
    # A validated per-request picker override applies to every stage, including
    # synthesis, regardless of LLM_SYNTHESIS_MODEL.
    r = _reasoner(llm_model="fast-x", llm_synthesis_model="think-x")
    r.model_override = "picked-x"
    assert r._synthesis_model() == "picked-x"
    assert r._reasoning_model() == "picked-x"


def _capture_outcomes(r, monkeypatch, *, content, is_valid=None):
    """Run _request_completion capturing the outcome= emitted per attempt."""
    from backend.app.services import progress

    monkeypatch.setattr(r, "_stream_completion", lambda **k: content)
    events: list[dict] = []
    token = progress.set_progress_callback(events.append)
    try:
        r._request_completion(
            stage_key="s", title="t", system_prompt="sys", user_prompt="usr", is_valid=is_valid
        )
    finally:
        progress.reset_progress_callback(token)
    outcomes = []
    for e in events:
        if e.get("type") != "api_call":
            continue
        for d in e.get("details", []):
            if d.startswith("outcome="):
                outcomes.append(d[len("outcome=") :])
    return outcomes


def test_outcome_is_unchecked_not_accepted_without_validator(monkeypatch):
    # The trace must not claim "校验通过" for a validator-less call — the retry loop
    # never judged usability, the caller's own parser does. Claiming it passed here
    # would lie when that downstream parse then fails (the run-4 bug).
    r = _reasoner(llm_model="fast-x", llm_reasoning_retries=2)
    outcomes = _capture_outcomes(r, monkeypatch, content='{ "next_action": "investigate"')
    assert outcomes == ["原样采用（未做解析校验）"]  # non-empty, no validator -> honest, no retry


def test_outcome_is_accepted_only_when_validator_passes(monkeypatch):
    r = _reasoner(llm_model="fast-x", llm_reasoning_retries=2)
    outcomes = _capture_outcomes(
        r, monkeypatch, content='{"claims": [{"claim": "c"}]}', is_valid=r._synthesis_content_usable
    )
    assert outcomes == ["校验通过"]


def test_health_aware_order_puts_healthy_before_unhealthy(monkeypatch):
    from backend.app.services.model_health import ModelHealthRegistry

    registry = ModelHealthRegistry(failure_threshold=1)
    monkeypatch.setattr(
        "backend.app.services.agent_reasoner.get_model_health_registry",
        lambda: registry,
    )
    registry.report_failure("m-a")

    seen: list[str] = []

    def record(*, endpoint, model, system_prompt, user_prompt, **_):
        seen.append(model)
        return '{"ok": true}'

    r = _reasoner(llm_model="m-a", llm_models=("m-a", "m-b"), llm_reasoning_retries=2)
    monkeypatch.setattr(r, "_stream_completion", record)
    r._request_completion(stage_key="s", title="t", system_prompt="sys", user_prompt="usr")
    assert seen[0] == "m-b"


def test_health_aware_order_skipped_for_picker_override(monkeypatch):
    from backend.app.services.model_health import ModelHealthRegistry

    registry = ModelHealthRegistry(failure_threshold=1)
    monkeypatch.setattr(
        "backend.app.services.agent_reasoner.get_model_health_registry",
        lambda: registry,
    )
    registry.report_failure("picked-x")

    seen: list[str] = []

    def record(*, endpoint, model, system_prompt, user_prompt, **_):
        seen.append(model)
        return '{"ok": true}'

    r = _reasoner(llm_model="m-a", llm_models=("m-a", "m-b"), llm_reasoning_retries=2)
    r.model_override = "picked-x"
    monkeypatch.setattr(r, "_stream_completion", record)
    r._request_completion(stage_key="s", title="t", system_prompt="sys", user_prompt="usr")
    assert seen == ["picked-x"]


def test_unhealthy_model_still_tried_when_healthy_ones_fail(monkeypatch):
    from backend.app.services.model_health import ModelHealthRegistry

    registry = ModelHealthRegistry(failure_threshold=1)
    monkeypatch.setattr(
        "backend.app.services.agent_reasoner.get_model_health_registry",
        lambda: registry,
    )
    registry.report_failure("m-a")

    seen: list[str] = []

    def only_unhealthy_works(*, endpoint, model, system_prompt, user_prompt, **_):
        seen.append(model)
        return '{"ok": true}' if model == "m-a" else ""

    r = _reasoner(llm_model="m-a", llm_models=("m-a", "m-b"), llm_reasoning_retries=2)
    monkeypatch.setattr(r, "_stream_completion", only_unhealthy_works)
    out = r._request_completion(stage_key="s", title="t", system_prompt="sys", user_prompt="usr")
    assert out == '{"ok": true}'
    assert "m-b" in seen
    assert "m-a" in seen


def test_close_is_idempotent_noop():
    r = _reasoner(llm_model="fast-x")
    r.close()
    r.close()  # second call must not raise
    assert not r._client.is_closed  # module-level client stays open


def test_reasoners_share_httpx_client_across_instances():
    r1 = _reasoner(llm_model="fast-x")
    r2 = _reasoner(llm_model="think-x")
    assert r1._client is r2._client
