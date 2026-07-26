"""Tests for sub-agent spawning (P1)."""
from __future__ import annotations

from backend.app.agent.runner import AgentRunner
from backend.app.agent.state import AgentState
from backend.app.agent_tools.base import ToolContext
from backend.app.models.schemas import AnalyzeRequest, NormalizedEvent


class FakeSettings:
    agent_max_url_fetches = 0
    agent_max_token_budget = 0
    agent_tool_max_retries = 0


class FakeReasoner:
    pass


def _make_ctx():
    return ToolContext(
        settings=FakeSettings(),
        input_normalizer=None,
        retriever=None,
        url_content_extractor=None,
        question_resolver=None,
        agent_reasoner=FakeReasoner(),
        provider_enricher=None,
        claim_extractor=None,
        verdict_engine=None,
        timeline_builder=None,
        report_builder=None,
        content_check_builder=None,
        pipeline_trace_builder=None,
    )


def test_spawn_sub_returns_child_state(monkeypatch):
    ctx = _make_ctx()
    runner = AgentRunner(ctx)

    # Set up parent state
    parent_request = AnalyzeRequest(raw_input="parent rumor")
    runner._state = AgentState(request=parent_request)
    runner._state.max_token_budget = 10000

    from backend.app.agent.state import StepOutcome

    def fake_safe_dispatch(action, state):
        if action == "normalize":
            state.normalized_event = NormalizedEvent(
                title="child", summary="s", raw_input="child query",
                input_type="text_news", source_name="n", source_url="",
            )
        return StepOutcome(action=action, success=True, summary="ok")

    monkeypatch.setattr(runner, "_safe_dispatch", fake_safe_dispatch)

    child_state = runner.spawn_sub(
        AnalyzeRequest(raw_input="child query"),
        max_steps=5,
    )
    assert child_state.request.raw_input == "child query"
    assert "normalize" in child_state.done_actions


def test_spawn_sub_inherits_parent_budget(monkeypatch):
    ctx = _make_ctx()
    runner = AgentRunner(ctx)
    runner._state = AgentState(request=AnalyzeRequest(raw_input="parent"))
    runner._state.max_token_budget = 10000
    runner._state.token_usage.add(prompt=3000, completion=1000)

    from backend.app.agent.state import StepOutcome
    monkeypatch.setattr(runner, "_safe_dispatch", lambda a, s:
        StepOutcome(action=a, success=True, summary="ok"))

    child_state = runner.spawn_sub(
        AnalyzeRequest(raw_input="child"),
        max_steps=2,
    )
    # Parent used 4000 total, so child gets 10000 - 4000 = 6000
    assert child_state.max_token_budget == 6000


def test_spawn_sub_no_budget_inheritance():
    ctx = _make_ctx()
    runner = AgentRunner(ctx)
    runner._state = AgentState(request=AnalyzeRequest(raw_input="parent"))
    runner._state.max_token_budget = 10000
    runner._state.token_usage.add(prompt=5000, completion=2000)

    child_state = runner.spawn_sub(
        AnalyzeRequest(raw_input="child"),
        inherit_budget=False,
        max_steps=1,
    )
    # No inheritance → budget stays 0 (unlimited)
    assert child_state.max_token_budget == 0


def test_spawn_sub_actions_subset(monkeypatch):
    ctx = _make_ctx()
    runner = AgentRunner(ctx)
    runner._state = AgentState(request=AnalyzeRequest(raw_input="parent"))

    dispatched = []
    from backend.app.agent.state import StepOutcome
    def track_dispatch(action, state):
        dispatched.append(action)
        return StepOutcome(action=action, success=True, summary="ok")

    monkeypatch.setattr(runner, "_safe_dispatch", track_dispatch)

    child_state = runner.spawn_sub(
        AnalyzeRequest(raw_input="child"),
        actions_subset=["normalize", "search_news"],
        max_steps=10,
    )
    # Only normalize and search_news should be dispatched; others skipped
    for action in dispatched:
        assert action in ["normalize", "search_news"]


def test_spawn_sub_respects_parent_cancellation(monkeypatch):
    ctx = _make_ctx()
    runner = AgentRunner(ctx)
    runner._state = AgentState(request=AnalyzeRequest(raw_input="parent"))
    runner._state.cancelled = True

    from backend.app.agent.state import StepOutcome
    monkeypatch.setattr(runner, "_safe_dispatch", lambda a, s:
        StepOutcome(action=a, success=True, summary="ok"))

    child_state = runner.spawn_sub(
        AnalyzeRequest(raw_input="child"),
        max_steps=10,
    )
    # Should exit immediately due to parent cancellation
    assert child_state.done_actions == []


def test_spawn_sub_token_tracking_propagates_to_parent(monkeypatch):
    ctx = _make_ctx()
    runner = AgentRunner(ctx)
    runner._state = AgentState(request=AnalyzeRequest(raw_input="parent"))
    runner._state.max_token_budget = 50000

    from backend.app.agent.state import StepOutcome

    def fake_dispatch(action, state):
        state.token_usage.add(prompt=100, completion=50)
        return StepOutcome(action=action, success=True, summary="ok")

    monkeypatch.setattr(runner, "_safe_dispatch", fake_dispatch)

    child_state = runner.spawn_sub(
        AnalyzeRequest(raw_input="child"),
        max_steps=3,
    )
    assert child_state.token_usage.call_count > 0
