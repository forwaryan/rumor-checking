"""Tests for the model-health state machine and the shared health-aware
one-shot completion transport (backend/app/services/model_health.py)."""
from __future__ import annotations

import pytest

from backend.app.core.config import get_settings
from backend.app.services import model_health, progress
from backend.app.services.model_health import (
    ModelHealthRegistry,
    complete_once,
    diff_snapshot,
)


# --------------------------------------------------------------------------- #
# ModelHealthRegistry state machine
# --------------------------------------------------------------------------- #
def test_fresh_model_is_healthy():
    reg = ModelHealthRegistry()
    assert reg.is_healthy("never-seen")


def test_evicts_only_at_threshold():
    reg = ModelHealthRegistry(failure_threshold=3, recovery_seconds=300.0)
    reg.report_failure("m")
    assert reg.is_healthy("m")  # 1 < 3
    reg.report_failure("m")
    assert reg.is_healthy("m")  # 2 < 3
    reg.report_failure("m")
    assert not reg.is_healthy("m")  # 3 >= 3 -> evicted


def test_success_restores_health_immediately():
    reg = ModelHealthRegistry(failure_threshold=1)
    reg.report_failure("m")
    assert not reg.is_healthy("m")
    reg.report_success("m")
    assert reg.is_healthy("m")


def test_success_on_unseen_model_is_noop():
    reg = ModelHealthRegistry()
    reg.report_success("never-seen")  # must not create state or raise
    assert reg.is_healthy("never-seen")


def test_time_window_recovery(monkeypatch):
    reg = ModelHealthRegistry(failure_threshold=1, recovery_seconds=100.0)
    clock = {"t": 1000.0}
    monkeypatch.setattr(reg, "_now", lambda: clock["t"])

    reg.report_failure("m")
    assert not reg.is_healthy("m")

    clock["t"] = 1099.0  # 99s elapsed, still inside window
    assert not reg.is_healthy("m")

    clock["t"] = 1100.0  # exactly recovery_seconds elapsed
    assert reg.is_healthy("m")


def test_recovery_disabled_when_seconds_non_positive(monkeypatch):
    reg = ModelHealthRegistry(failure_threshold=1, recovery_seconds=0.0)
    clock = {"t": 0.0}
    monkeypatch.setattr(reg, "_now", lambda: clock["t"])

    reg.report_failure("m")
    assert not reg.is_healthy("m")
    clock["t"] = 10_000_000.0  # far future
    assert not reg.is_healthy("m")  # time alone never recovers
    reg.report_success("m")
    assert reg.is_healthy("m")  # only an explicit success clears it


def test_order_by_health_puts_healthy_first_preserving_order():
    reg = ModelHealthRegistry(failure_threshold=1)
    reg.report_failure("b")
    assert reg.order_by_health(["a", "b", "c"]) == ["a", "c", "b"]


def test_order_by_health_dedupes_keeping_first_occurrence():
    reg = ModelHealthRegistry()
    assert reg.order_by_health(["a", "a", "b", "a"]) == ["a", "b"]


def test_order_by_health_skips_blank_entries():
    reg = ModelHealthRegistry()
    assert reg.order_by_health(["", "a", ""]) == ["a"]


def test_order_by_health_never_empty_when_all_unhealthy():
    reg = ModelHealthRegistry(failure_threshold=1)
    reg.report_failure("a")
    reg.report_failure("b")
    # Every model evicted -> fall back to original order (best-effort last resort).
    assert reg.order_by_health(["a", "b"]) == ["a", "b"]


# --------------------------------------------------------------------------- #
# complete_once transport
# --------------------------------------------------------------------------- #
class _FakeResp:
    def __init__(self, status_code=200, content="", reasoning=None):
        self.status_code = status_code
        self._content = content
        self._reasoning = reasoning

    def json(self):
        message = {"content": self._content}
        if self._reasoning is not None:
            message["reasoning_content"] = self._reasoning
        return {"choices": [{"message": message}]}


@pytest.fixture()
def fast_settings(monkeypatch):
    """Settings whose whitelist has two fast models and one reasoning model."""
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "fast-a")
    monkeypatch.setenv("LLM_MODELS", "fast-a,fast-b,reason-x")
    monkeypatch.setenv("LLM_REASONING_MODELS", "reason-x")
    monkeypatch.setenv("LLM_BASE_URL", "http://gw.test/v1")
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture(autouse=True)
def reset_health_singleton():
    """Isolate the process-wide registry so eviction state never leaks between tests."""
    model_health._registry = None
    yield
    model_health._registry = None


def _one(settings, **overrides):
    kwargs = dict(temperature=0.1, max_tokens=64, timeout=5.0)
    kwargs.update(overrides)
    return complete_once("sys", "usr", settings=settings, **kwargs)


def test_complete_once_returns_first_healthy_and_stops(monkeypatch, fast_settings):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append(json["model"])
        return _FakeResp(200, "答案")

    monkeypatch.setattr(model_health.httpx, "post", fake_post)
    assert _one(fast_settings) == "答案"
    assert calls == ["fast-a"]  # succeeded on the first candidate; no failover


def test_complete_once_fails_over_on_http_error(monkeypatch, fast_settings):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append(json["model"])
        if json["model"] == "fast-a":
            return _FakeResp(500, "")
        return _FakeResp(200, "备用答案")

    monkeypatch.setattr(model_health.httpx, "post", fake_post)
    assert _one(fast_settings) == "备用答案"
    assert calls == ["fast-a", "fast-b"]
    reg = model_health.get_model_health_registry()
    assert reg._states["fast-a"].consecutive_errors == 1  # failure recorded


def test_complete_once_fails_over_on_transport_exception(monkeypatch, fast_settings):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append(json["model"])
        if json["model"] == "fast-a":
            raise RuntimeError("read timeout")
        return _FakeResp(200, "备用答案")

    monkeypatch.setattr(model_health.httpx, "post", fake_post)
    assert _one(fast_settings) == "备用答案"
    assert calls == ["fast-a", "fast-b"]


def test_complete_once_treats_empty_content_as_failure(monkeypatch, fast_settings):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append(json["model"])
        if json["model"] == "fast-a":
            return _FakeResp(200, "   ")  # 200 but blank -> failure, fail over
        return _FakeResp(200, "有内容")

    monkeypatch.setattr(model_health.httpx, "post", fake_post)
    assert _one(fast_settings) == "有内容"
    assert calls == ["fast-a", "fast-b"]


def test_complete_once_all_fail_returns_empty(monkeypatch, fast_settings):
    def fake_post(url, headers, json, timeout):
        return _FakeResp(503, "")

    monkeypatch.setattr(model_health.httpx, "post", fake_post)
    assert _one(fast_settings) == ""


def test_complete_once_fails_over_on_malformed_200_body(monkeypatch, fast_settings):
    # A 200 whose body isn't the expected chat-completions shape must be treated as
    # a model failure (evict + fail over), never propagate a KeyError to the caller.
    calls = []

    class _BadResp:
        status_code = 200

        def json(self):
            return {"unexpected": "shape"}  # no ["choices"][0]["message"]

    def fake_post(url, headers, json, timeout):
        calls.append(json["model"])
        if json["model"] == "fast-a":
            return _BadResp()
        return _FakeResp(200, "恢复")

    monkeypatch.setattr(model_health.httpx, "post", fake_post)
    assert _one(fast_settings) == "恢复"
    assert calls == ["fast-a", "fast-b"]


def test_complete_once_include_reasoning_takes_last_cot_line(monkeypatch, fast_settings):
    def fake_post(url, headers, json, timeout):
        return _FakeResp(200, "", reasoning="先想第一步\n再想第二步\n最终结论")

    monkeypatch.setattr(model_health.httpx, "post", fake_post)
    assert _one(fast_settings, include_reasoning=True) == "最终结论"


def test_complete_once_ignores_reasoning_when_flag_off(monkeypatch, fast_settings):
    def fake_post(url, headers, json, timeout):
        return _FakeResp(200, "", reasoning="只有思维链")

    monkeypatch.setattr(model_health.httpx, "post", fake_post)
    # Default (include_reasoning=False): blank content is a failure on both models.
    assert _one(fast_settings) == ""


def test_complete_once_returns_empty_without_api_key(monkeypatch, fast_settings):
    monkeypatch.setenv("LLM_API_KEY", "")
    get_settings.cache_clear()
    settings = get_settings()

    def boom(*a, **kw):
        raise AssertionError("must not POST without an api key")

    monkeypatch.setattr(model_health.httpx, "post", boom)
    assert _one(settings) == ""


def test_complete_once_returns_empty_when_no_fast_model(monkeypatch):
    # Whitelist has only a reasoning model and no default model -> no fast candidate.
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "")
    monkeypatch.setenv("LLM_MODELS", "reason-x")
    monkeypatch.setenv("LLM_REASONING_MODELS", "reason-x")
    get_settings.cache_clear()
    settings = get_settings()

    def boom(*a, **kw):
        raise AssertionError("must not POST when there is no fast candidate")

    monkeypatch.setattr(model_health.httpx, "post", boom)
    assert _one(settings) == ""


def test_complete_once_falls_back_to_default_model_when_no_fast_in_list(monkeypatch):
    # No non-reasoning model in LLM_MODELS, but a default llm_model exists: it should
    # be used as the sole candidate rather than giving up.
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "default-fast")
    monkeypatch.setenv("LLM_MODELS", "reason-x")
    monkeypatch.setenv("LLM_REASONING_MODELS", "reason-x")
    get_settings.cache_clear()
    settings = get_settings()

    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append(json["model"])
        return _FakeResp(200, "ok")

    monkeypatch.setattr(model_health.httpx, "post", fake_post)
    assert _one(settings) == "ok"
    assert calls == ["default-fast"]


# --------------------------------------------------------------------------- #
# Snapshot / diff — used by the pipeline's per-run failover summary
# --------------------------------------------------------------------------- #
def test_snapshot_only_reports_seen_models():
    reg = ModelHealthRegistry(failure_threshold=2)
    reg.report_failure("m")
    reg.report_failure("m")
    snap = reg.snapshot()
    assert set(snap) == {"m"}  # never-seen models are absent
    assert snap["m"] == {
        "healthy": False,
        "consecutive_errors": 2,
        "total_failures": 2,
        "total_successes": 0,
        "total_evictions": 1,
    }


def test_snapshot_counters_track_lifetime_totals():
    # Lifetime counters keep climbing even after a success clears consecutive_errors,
    # so an ops dashboard sees the true failure rate across a whole run.
    reg = ModelHealthRegistry(failure_threshold=3)
    reg.report_failure("m")
    reg.report_failure("m")
    reg.report_success("m")  # clears consecutive_errors but total_failures stays 2
    reg.report_failure("m")
    snap = reg.snapshot()["m"]
    assert snap["total_failures"] == 3
    assert snap["total_successes"] == 1
    assert snap["consecutive_errors"] == 1  # reset by the success then +1
    assert snap["total_evictions"] == 0     # never crossed the threshold


def test_diff_snapshot_returns_only_changed_models():
    before = {"m": {"total_failures": 1, "total_successes": 0, "total_evictions": 0}}
    # "m" gained a success; "n" is new and gained a failure + eviction.
    after = {
        "m": {"total_failures": 1, "total_successes": 1, "total_evictions": 0},
        "n": {"total_failures": 3, "total_successes": 0, "total_evictions": 1},
        "quiet": {"total_failures": 5, "total_successes": 5, "total_evictions": 0},
    }
    # "quiet" was not in `before` -> looks like everything happened this run.
    before["quiet"] = {"total_failures": 5, "total_successes": 5, "total_evictions": 0}
    diffs = diff_snapshot(before, after)
    assert set(diffs) == {"m", "n"}  # "quiet" has zero delta -> omitted
    assert diffs["m"] == {"failures": 0, "successes": 1, "evictions": 0}
    assert diffs["n"] == {"failures": 3, "successes": 0, "evictions": 1}


def test_diff_snapshot_handles_missing_keys_on_either_side():
    # A model present only in `before` (unlikely) or only in `after` (a fresh model
    # touched this run) must not raise — and the missing side is treated as zero.
    before = {"only_before": {"total_failures": 2, "total_successes": 0, "total_evictions": 0}}
    after = {"only_after": {"total_failures": 1, "total_successes": 0, "total_evictions": 0}}
    diffs = diff_snapshot(before, after)
    assert diffs["only_before"]["failures"] == -2  # disappeared -> negative delta
    assert diffs["only_after"]["failures"] == 1


# --------------------------------------------------------------------------- #
# complete_once — stage_key surfaces failover in the trace
# --------------------------------------------------------------------------- #
def test_complete_once_emits_switch_log_on_failover_when_stage_key_given(monkeypatch, fast_settings):
    def fake_post(url, headers, json, timeout):
        if json["model"] == "fast-a":
            return _FakeResp(500, "")
        return _FakeResp(200, "备用答案")

    monkeypatch.setattr(model_health.httpx, "post", fake_post)
    events: list[dict] = []
    token = progress.set_progress_callback(events.append)
    try:
        assert complete_once(
            "sys", "usr",
            settings=fast_settings, temperature=0.1, max_tokens=64, timeout=5.0,
            stage_key="verdict_engine",
        ) == "备用答案"
    finally:
        progress.reset_progress_callback(token)
    switch = [e for e in events if e.get("type") == "log" and e.get("title") == "切换备用模型"]
    assert len(switch) == 1
    assert switch[0]["stage_key"] == "verdict_engine"
    assert "fast-b" in switch[0]["summary"]


def test_complete_once_stays_silent_without_stage_key(monkeypatch, fast_settings):
    # The original callers can still opt out of trace emissions by omitting
    # stage_key — we must not force every user of complete_once onto the trace.
    def fake_post(url, headers, json, timeout):
        if json["model"] == "fast-a":
            return _FakeResp(500, "")
        return _FakeResp(200, "ok")

    monkeypatch.setattr(model_health.httpx, "post", fake_post)
    events: list[dict] = []
    token = progress.set_progress_callback(events.append)
    try:
        assert complete_once(
            "sys", "usr",
            settings=fast_settings, temperature=0.1, max_tokens=64, timeout=5.0,
        ) == "ok"
    finally:
        progress.reset_progress_callback(token)
    assert not any(e.get("type") == "log" and e.get("title") == "切换备用模型" for e in events)


def test_complete_once_no_switch_log_when_first_candidate_answers(monkeypatch, fast_settings):
    # Success on the first candidate must not emit a switch log — that would lie
    # about the trace showing failover activity.
    monkeypatch.setattr(model_health.httpx, "post",
                        lambda url, headers, json, timeout: _FakeResp(200, "答案"))
    events: list[dict] = []
    token = progress.set_progress_callback(events.append)
    try:
        assert complete_once(
            "sys", "usr",
            settings=fast_settings, temperature=0.1, max_tokens=64, timeout=5.0,
            stage_key="verdict_engine",
        ) == "答案"
    finally:
        progress.reset_progress_callback(token)
    assert not any(e.get("type") == "log" and e.get("title") == "切换备用模型" for e in events)
