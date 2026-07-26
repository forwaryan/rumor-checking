"""Tests for P0-P3 harness features: retry, budget, parallel dispatch, tool registry, hooks."""
from __future__ import annotations

import time
from dataclasses import replace
from unittest.mock import MagicMock

import pytest

from backend.app.agent.planner import RulePlanner, _budget_exhausted, legal_actions
from backend.app.agent.runner import (
    AgentRunner,
    _CRITICAL_ACTIONS,
    _RETRY_BACKOFF_BASE,
    _RETRY_POLICY,
)
from backend.app.agent.state import AgentState, StepOutcome, TokenUsage
from backend.app.agent_tools.base import (
    HookContext,
    HookRegistry,
    ToolContext,
    ToolSpec,
    get_all_tool_specs,
    get_tool_spec,
    tool,
    _TOOL_REGISTRY,
)
from backend.app.core.config import get_settings
from backend.app.models.schemas import AnalyzeRequest


def _request() -> AnalyzeRequest:
    return AnalyzeRequest(raw_input="测试用传闻")


# ============================================================
# P0: Tool-level retry with backoff
# ============================================================


def test_retry_succeeds_on_second_attempt(monkeypatch):
    """A tool that fails once then succeeds should produce a success outcome."""
    attempts = {"n": 0}

    def flaky_dispatch(self, action, state):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise TimeoutError("gateway timeout")
        # Succeed on second attempt
        from backend.app.models.schemas import NormalizedEvent
        state.normalized_event = NormalizedEvent(
            title="t", summary="s", raw_input="t",
            input_type="text_news", source_name="s", source_url="",
        )
        state.resolved_event = state.normalized_event

    monkeypatch.setattr(AgentRunner, "_dispatch", flaky_dispatch)

    ctx = MagicMock(spec=ToolContext)
    ctx.settings = replace(get_settings(), agent_tool_max_retries=2)
    ctx.agent_reasoner = MagicMock()
    ctx.agent_reasoner.enabled = False

    runner = AgentRunner(ctx, planner=RulePlanner())
    outcome = runner._dispatch_with_retry("normalize", runner._state or AgentState(request=_request()))
    assert outcome.success
    assert attempts["n"] == 2


def test_retry_exhausted_returns_failure(monkeypatch):
    """After all retries exhausted, returns a failure outcome."""
    def always_fail(self, action, state):
        raise ConnectionError("refused")

    monkeypatch.setattr(AgentRunner, "_dispatch", always_fail)

    ctx = MagicMock(spec=ToolContext)
    ctx.settings = replace(get_settings(), agent_tool_max_retries=2)
    ctx.agent_reasoner = MagicMock()
    ctx.agent_reasoner.enabled = False

    runner = AgentRunner(ctx, planner=RulePlanner())
    state = AgentState(request=_request())
    outcome = runner._dispatch_with_retry("normalize", state)
    assert not outcome.success
    assert outcome.error_type == "ConnectionError"


def test_retry_respects_settings_cap(monkeypatch):
    """The settings cap limits the max retries regardless of policy."""
    attempts = {"n": 0}

    def always_fail(self, action, state):
        attempts["n"] += 1
        raise RuntimeError("fail")

    monkeypatch.setattr(AgentRunner, "_dispatch", always_fail)

    ctx = MagicMock(spec=ToolContext)
    # Settings cap = 1, but policy says 2 for normalize → actual retries = 1
    ctx.settings = replace(get_settings(), agent_tool_max_retries=1)
    ctx.agent_reasoner = MagicMock()
    ctx.agent_reasoner.enabled = False

    runner = AgentRunner(ctx, planner=RulePlanner())
    state = AgentState(request=_request())
    outcome = runner._dispatch_with_retry("normalize", state)
    assert not outcome.success
    # 1 initial + 1 retry = 2 attempts total
    assert attempts["n"] == 2


def test_retry_disabled_by_default(monkeypatch):
    """With default settings (agent_tool_max_retries=0), no retries occur."""
    attempts = {"n": 0}

    def always_fail(self, action, state):
        attempts["n"] += 1
        raise RuntimeError("fail")

    monkeypatch.setattr(AgentRunner, "_dispatch", always_fail)

    ctx = MagicMock(spec=ToolContext)
    # Default: agent_tool_max_retries=0 → no retries
    ctx.settings = replace(get_settings(), agent_tool_max_retries=0)
    ctx.agent_reasoner = MagicMock()
    ctx.agent_reasoner.enabled = False

    runner = AgentRunner(ctx, planner=RulePlanner())
    state = AgentState(request=_request())
    outcome = runner._dispatch_with_retry("normalize", state)
    assert not outcome.success
    assert attempts["n"] == 1  # Only the initial attempt, no retry


def test_retry_backoff_delay(monkeypatch):
    """Retry uses exponential backoff."""
    call_times = []

    def always_fail(self, action, state):
        call_times.append(time.monotonic())
        raise RuntimeError("fail")

    monkeypatch.setattr(AgentRunner, "_dispatch", always_fail)
    # Speed up backoff for testing
    monkeypatch.setattr("backend.app.agent.runner._RETRY_BACKOFF_BASE", 0.05)

    ctx = MagicMock(spec=ToolContext)
    ctx.settings = replace(get_settings(), agent_tool_max_retries=3)
    ctx.agent_reasoner = MagicMock()
    ctx.agent_reasoner.enabled = False

    runner = AgentRunner(ctx, planner=RulePlanner())
    state = AgentState(request=_request())
    runner._dispatch_with_retry("normalize", state, max_retries=2)

    # Should have 3 attempts with increasing gaps
    assert len(call_times) == 3
    gap1 = call_times[1] - call_times[0]
    gap2 = call_times[2] - call_times[1]
    assert gap1 >= 0.04  # ~0.05
    assert gap2 >= 0.08  # ~0.1 (doubled)


# ============================================================
# P1: Token budget hard limit
# ============================================================


def test_budget_exhausted_false_when_no_budget():
    state = AgentState(request=_request())
    state.max_token_budget = 0
    assert not _budget_exhausted(state)


def test_budget_exhausted_false_when_under_limit():
    state = AgentState(request=_request())
    state.max_token_budget = 10000
    state.token_usage.add(prompt=3000, completion=2000, total=5000)
    assert not _budget_exhausted(state)


def test_budget_exhausted_true_when_over_limit():
    state = AgentState(request=_request())
    state.max_token_budget = 10000
    state.token_usage.add(prompt=6000, completion=5000, total=11000)
    assert _budget_exhausted(state)


def test_budget_forces_synthesize_skipping_optional_steps():
    """When budget is exhausted, legal_actions skips investigate."""
    state = AgentState(request=_request())
    state.max_token_budget = 100
    state.token_usage.add(prompt=60, completion=50, total=110)
    # Simulate: normalize, search, resolve, follow_up done
    state.done_actions = ["normalize", "search_news", "resolve_question", "follow_up_retrieval"]

    actions = legal_actions(state)
    # Should skip investigate and go straight to synthesize
    assert actions == ["synthesize"]


def test_budget_forces_finalize_after_synthesize():
    """With budget exhausted and agent_synthesized=True, go straight to finalize."""
    state = AgentState(request=_request())
    state.max_token_budget = 100
    state.token_usage.add(prompt=60, completion=50, total=110)
    state.done_actions = ["normalize", "search_news", "resolve_question", "follow_up_retrieval", "synthesize"]
    state.agent_synthesized = True

    actions = legal_actions(state)
    assert actions == ["finalize_report"]


def test_budget_snapshot_includes_remaining():
    """The planner snapshot should include budget and remaining when set."""
    from backend.app.agent.planner import _evidence_snapshot

    state = AgentState(request=_request())
    state.max_token_budget = 20000
    state.token_usage.add(prompt=5000, completion=3000, total=8000)

    # Need a minimal normalized event for the snapshot to work
    from backend.app.models.schemas import NormalizedEvent
    state.normalized_event = NormalizedEvent(
        title="t", summary="s", raw_input="t",
        input_type="text_news", source_name="s", source_url="",
    )
    state.resolved_event = state.normalized_event

    snapshot = _evidence_snapshot(state)
    assert "token_usage" in snapshot
    assert snapshot["token_usage"]["budget"] == 20000
    assert snapshot["token_usage"]["remaining"] == 12000


# ============================================================
# P2: Parallel dispatch + Tool registry
# ============================================================


def test_parallel_dispatch_runs_multiple_actions(monkeypatch):
    """run_parallel executes actions concurrently and returns outcomes in order."""
    call_log = []

    def tracked_dispatch(self, action, state):
        call_log.append(action)

    monkeypatch.setattr(AgentRunner, "_dispatch", tracked_dispatch)

    ctx = MagicMock(spec=ToolContext)
    ctx.settings = replace(get_settings(), agent_tool_max_retries=0)
    ctx.agent_reasoner = MagicMock()
    ctx.agent_reasoner.enabled = False

    runner = AgentRunner(ctx, planner=RulePlanner())
    state = AgentState(request=_request())
    outcomes = runner.run_parallel(["action_a", "action_b", "action_c"], state)

    assert len(outcomes) == 3
    assert all(o.success for o in outcomes)
    assert set(call_log) == {"action_a", "action_b", "action_c"}


def test_parallel_dispatch_partial_failure(monkeypatch):
    """One failing action in parallel doesn't crash the others."""

    def selective_dispatch(self, action, state):
        if action == "action_b":
            raise ValueError("b failed")

    monkeypatch.setattr(AgentRunner, "_dispatch", selective_dispatch)

    ctx = MagicMock(spec=ToolContext)
    ctx.settings = replace(get_settings(), agent_tool_max_retries=0)
    ctx.agent_reasoner = MagicMock()
    ctx.agent_reasoner.enabled = False

    runner = AgentRunner(ctx, planner=RulePlanner())
    state = AgentState(request=_request())
    outcomes = runner.run_parallel(["action_a", "action_b", "action_c"], state)

    assert outcomes[0].success
    assert not outcomes[1].success
    assert "b failed" in (outcomes[1].error_message or "")
    assert outcomes[2].success


def test_tool_decorator_registers_spec():
    """The @tool decorator populates the registry."""
    # Clean up any existing entry from a prior test run
    _TOOL_REGISTRY.pop("_test_tool_xyz", None)

    @tool(name="_test_tool_xyz", description="Test tool", critical=True, retries=3)
    def _test_tool_fn(ctx, state):
        pass

    spec = get_tool_spec("_test_tool_xyz")
    assert spec is not None
    assert spec.name == "_test_tool_xyz"
    assert spec.critical is True
    assert spec.retries == 3
    assert spec.description == "Test tool"

    # Cleanup
    _TOOL_REGISTRY.pop("_test_tool_xyz", None)


def test_get_all_tool_specs():
    """get_all_tool_specs returns all registered specs."""
    _TOOL_REGISTRY.pop("_test_a", None)
    _TOOL_REGISTRY.pop("_test_b", None)

    @tool(name="_test_a", description="A")
    def _a(ctx, state):
        pass

    @tool(name="_test_b", description="B")
    def _b(ctx, state):
        pass

    specs = get_all_tool_specs()
    names = [s.name for s in specs]
    assert "_test_a" in names
    assert "_test_b" in names

    _TOOL_REGISTRY.pop("_test_a", None)
    _TOOL_REGISTRY.pop("_test_b", None)


# ============================================================
# P3: Hook system
# ============================================================


def test_pre_hook_fires_before_dispatch(monkeypatch):
    """Pre-hooks run before the tool dispatch."""
    hook_log = []

    def track_dispatch(self, action, state):
        hook_log.append(f"dispatch:{action}")

    monkeypatch.setattr(AgentRunner, "_dispatch", track_dispatch)

    def pre_hook(ctx: HookContext):
        hook_log.append(f"pre:{ctx.action}")

    hooks = HookRegistry()
    hooks.add_pre(pre_hook)

    ctx = MagicMock(spec=ToolContext)
    ctx.settings = replace(get_settings(), agent_tool_max_retries=0)
    ctx.agent_reasoner = MagicMock()
    ctx.agent_reasoner.enabled = False

    runner = AgentRunner(ctx, planner=RulePlanner(), hooks=hooks)
    state = AgentState(request=_request())
    outcome = runner._safe_dispatch("test_action", state)

    assert hook_log == ["pre:test_action", "dispatch:test_action"]
    assert outcome.success


def test_post_hook_fires_after_dispatch(monkeypatch):
    """Post-hooks run after dispatch with outcome."""
    outcomes_seen = []

    def noop_dispatch(self, action, state):
        pass

    monkeypatch.setattr(AgentRunner, "_dispatch", noop_dispatch)

    def post_hook(ctx: HookContext):
        outcomes_seen.append(ctx.outcome)

    hooks = HookRegistry()
    hooks.add_post(post_hook)

    ctx = MagicMock(spec=ToolContext)
    ctx.settings = replace(get_settings(), agent_tool_max_retries=0)
    ctx.agent_reasoner = MagicMock()
    ctx.agent_reasoner.enabled = False

    runner = AgentRunner(ctx, planner=RulePlanner(), hooks=hooks)
    state = AgentState(request=_request())
    runner._safe_dispatch("test_action", state)

    assert len(outcomes_seen) == 1
    assert outcomes_seen[0].success


def test_post_hook_receives_error_on_failure(monkeypatch):
    """Post-hooks see the error when dispatch fails."""
    errors_seen = []

    def failing_dispatch(self, action, state):
        raise ValueError("boom")

    monkeypatch.setattr(AgentRunner, "_dispatch", failing_dispatch)

    def post_hook(ctx: HookContext):
        errors_seen.append(ctx.error)

    hooks = HookRegistry()
    hooks.add_post(post_hook)

    ctx = MagicMock(spec=ToolContext)
    ctx.settings = replace(get_settings(), agent_tool_max_retries=0)
    ctx.agent_reasoner = MagicMock()
    ctx.agent_reasoner.enabled = False

    runner = AgentRunner(ctx, planner=RulePlanner(), hooks=hooks)
    state = AgentState(request=_request())
    outcome = runner._safe_dispatch("test_action", state)

    assert not outcome.success
    assert len(errors_seen) == 1
    assert isinstance(errors_seen[0], ValueError)


def test_hook_failure_does_not_crash_dispatch(monkeypatch):
    """A hook that throws does not affect the tool outcome."""

    def noop_dispatch(self, action, state):
        pass

    monkeypatch.setattr(AgentRunner, "_dispatch", noop_dispatch)

    def crashing_pre_hook(ctx: HookContext):
        raise RuntimeError("hook exploded")

    hooks = HookRegistry()
    hooks.add_pre(crashing_pre_hook)

    ctx = MagicMock(spec=ToolContext)
    ctx.settings = replace(get_settings(), agent_tool_max_retries=0)
    ctx.agent_reasoner = MagicMock()
    ctx.agent_reasoner.enabled = False

    runner = AgentRunner(ctx, planner=RulePlanner(), hooks=hooks)
    state = AgentState(request=_request())
    outcome = runner._safe_dispatch("test_action", state)

    # Hook crash is swallowed — dispatch still succeeds
    assert outcome.success


def test_multiple_hooks_all_fire(monkeypatch):
    """All registered hooks fire in order."""
    log = []

    def noop_dispatch(self, action, state):
        pass

    monkeypatch.setattr(AgentRunner, "_dispatch", noop_dispatch)

    hooks = HookRegistry()
    hooks.add_pre(lambda ctx: log.append("pre1"))
    hooks.add_pre(lambda ctx: log.append("pre2"))
    hooks.add_post(lambda ctx: log.append("post1"))
    hooks.add_post(lambda ctx: log.append("post2"))

    ctx = MagicMock(spec=ToolContext)
    ctx.settings = replace(get_settings(), agent_tool_max_retries=0)
    ctx.agent_reasoner = MagicMock()
    ctx.agent_reasoner.enabled = False

    runner = AgentRunner(ctx, planner=RulePlanner(), hooks=hooks)
    state = AgentState(request=_request())
    runner._safe_dispatch("x", state)

    assert log == ["pre1", "pre2", "post1", "post2"]
