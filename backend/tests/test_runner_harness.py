"""Tests for agent runner resilience, cancellation, token tracking, and planner context."""
from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock

import pytest

from backend.app.agent.planner import RulePlanner, _evidence_snapshot
from backend.app.agent.runner import _CRITICAL_ACTIONS, AgentRunner
from backend.app.agent.state import AgentState, StepOutcome, TokenUsage
from backend.app.agent_tools.base import ToolContext
from backend.app.core.config import get_settings
from backend.app.models.schemas import AnalyzeRequest


def _request() -> AnalyzeRequest:
    return AnalyzeRequest(raw_input="拼多多在雄安买了5栋楼")


# --- TokenUsage ---


def test_token_usage_accumulates():
    t = TokenUsage()
    t.add(prompt=100, completion=50, total=150)
    t.add(prompt=200, completion=100, total=300)
    assert t.prompt_tokens == 300
    assert t.completion_tokens == 150
    assert t.total_tokens == 450
    assert t.call_count == 2


def test_token_usage_derives_total_when_zero():
    t = TokenUsage()
    t.add(prompt=100, completion=50, total=0)
    assert t.total_tokens == 150


# --- StepOutcome ---


def test_step_outcome_success():
    o = StepOutcome(action="search_news", success=True, summary="done")
    assert o.success
    assert o.error_type is None


def test_step_outcome_failure():
    o = StepOutcome(
        action="investigate", success=False, summary="failed",
        error_type="ValueError", error_message="bad input",
    )
    assert not o.success
    assert o.error_type == "ValueError"


# --- Runner loop-level resilience ---


def test_runner_survives_non_critical_tool_failure(monkeypatch):
    """A non-critical tool failure should not crash the run."""
    from backend.app.agent import runner as runner_mod

    call_log = []

    def fake_dispatch(self, action, state):
        call_log.append(action)
        if action == "follow_up_retrieval":
            raise ValueError("simulated non-critical failure")
        if action == "normalize":
            from backend.app.models.schemas import NormalizedEvent
            state.normalized_event = NormalizedEvent(
                title="t", summary="s", raw_input="t",
                input_type="text_news", source_name="s", source_url="",
            )
            state.resolved_event = state.normalized_event
        elif action == "search_news":
            from backend.app.services.retrieval_models import RetrievalBundle
            state.retrieval_bundle = RetrievalBundle(query="q", provider_name="mock")
            state.initial_retrieval_bundle = state.retrieval_bundle
        elif action == "resolve_question":
            from backend.app.services.question_resolver import QuestionResolution
            state.question_resolution = QuestionResolution(
                event=state.resolved_event, follow_up_query=None, selected_result=None,
            )
        elif action == "synthesize":
            state.agent_synthesized = False
            state.synthesis_attempted = True
        elif action == "enrich":
            state.final_event = state.resolved_event
        elif action == "extract_claims":
            from backend.app.models.schemas import ClaimItem
            from backend.app.services.claim_extractor import ClaimExtraction
            state.claim_extraction = ClaimExtraction(
                claims=[ClaimItem(claim="X。", claim_type="fact")],
                source="rule", query_hints={},
            )
        elif action == "judge_claims":
            from backend.app.models.schemas import ClaimResult
            from backend.app.services.verdict_engine import VerdictEvaluation
            state.verdict = VerdictEvaluation(
                claim_results=[ClaimResult(
                    claim="X。", claim_type="fact", verdict="insufficient",
                    confidence="low", evidence=[], notes="n",
                )],
                evidence=[], evidence_grade="D", evidence_source="retrieval_mock",
            )
        elif action == "build_timeline":
            from backend.app.services.timeline_builder import TimelineBuild
            state.timeline = TimelineBuild(nodes=[], source="none", completeness=0, confidence=0)
        elif action == "finalize_report":
            from backend.app.models.schemas import Event, Report, ReportProvenance
            state.report = Report(
                mode="safe_mode",
                event=Event(title="t", summary="s", source_name="n", source_url="u", published_at="2026-07-01", mode="safe_mode"),
                claim_results=state.verdict.claim_results,
                timeline=[],
                sources=[],
                overall_credibility_score=30.0,
                overall_credibility_label="insufficient_evidence",
                final_summary="test",
                provenance=ReportProvenance(
                    source_type="backend_mock", event_source="input_normalized",
                    claim_source="rule", evidence_source="retrieval_mock",
                    timeline_source="none",
                ),
            )

    monkeypatch.setattr(AgentRunner, "_dispatch", fake_dispatch)

    ctx = MagicMock(spec=ToolContext)
    ctx.settings = get_settings()
    ctx.agent_reasoner = MagicMock()
    ctx.agent_reasoner.enabled = False

    runner = AgentRunner(ctx, planner=RulePlanner())
    report = runner.run(_request())

    assert report is not None
    assert "follow_up_retrieval" in call_log
    assert "finalize_report" in call_log


def test_runner_crashes_on_critical_action_failure(monkeypatch):
    """A critical tool (normalize) failure must crash the run with RuntimeError."""
    from backend.app.agent import runner as runner_mod

    def failing_dispatch(self, action, state):
        if action == "normalize":
            raise RuntimeError("normalize exploded")

    monkeypatch.setattr(AgentRunner, "_dispatch", failing_dispatch)

    ctx = MagicMock(spec=ToolContext)
    ctx.settings = get_settings()
    ctx.agent_reasoner = MagicMock()
    ctx.agent_reasoner.enabled = False

    runner = AgentRunner(ctx, planner=RulePlanner())
    with pytest.raises(RuntimeError, match="critical_action_failed:normalize"):
        runner.run(_request())


# --- Cancellation ---


def test_runner_respects_cancellation(monkeypatch):
    """Setting cancelled=True should abort the loop before the next step."""

    def fake_dispatch(self, action, state):
        if action == "normalize":
            from backend.app.models.schemas import NormalizedEvent
            state.normalized_event = NormalizedEvent(
                title="t", summary="s", raw_input="t",
                input_type="text_news", source_name="s", source_url="",
            )
            state.resolved_event = state.normalized_event
            # Cancel after normalize completes
            state.cancelled = True

    monkeypatch.setattr(AgentRunner, "_dispatch", fake_dispatch)

    ctx = MagicMock(spec=ToolContext)
    ctx.settings = get_settings()
    ctx.agent_reasoner = MagicMock()
    ctx.agent_reasoner.enabled = False

    runner = AgentRunner(ctx, planner=RulePlanner())
    # Should raise because no report was produced, but not crash on tool failure
    with pytest.raises(RuntimeError, match="agent_runner_finished_without_report"):
        runner.run(_request())

    # Only normalize should have run
    assert runner._state is not None
    assert runner._state.done_actions == ["normalize"]


def test_runner_cancel_method():
    """AgentRunner.cancel() sets the flag on the live state."""
    ctx = MagicMock(spec=ToolContext)
    ctx.settings = get_settings()
    ctx.agent_reasoner = MagicMock()
    ctx.agent_reasoner.enabled = False
    runner = AgentRunner(ctx)
    # Before run: no state -> cancel is a no-op
    runner.cancel()
    assert runner._state is None


# --- Planner context (evidence_snapshot) ---


def test_evidence_snapshot_includes_last_step_outcome():
    state = AgentState(request=_request())
    state.last_step_outcome = StepOutcome(
        action="investigate", success=False,
        error_type="TimeoutError", error_message="timed out",
    )
    snapshot = _evidence_snapshot(state)
    assert "last_step" in snapshot
    assert snapshot["last_step"]["action"] == "investigate"
    assert snapshot["last_step"]["success"] is False
    assert snapshot["last_step"]["error_type"] == "TimeoutError"


def test_evidence_snapshot_includes_token_usage():
    state = AgentState(request=_request())
    state.token_usage.add(prompt=500, completion=200, total=700)
    state.token_usage.add(prompt=300, completion=100, total=400)
    snapshot = _evidence_snapshot(state)
    assert "token_usage" in snapshot
    assert snapshot["token_usage"]["total_tokens"] == 1100
    assert snapshot["token_usage"]["call_count"] == 2


def test_evidence_snapshot_omits_token_usage_when_no_calls():
    state = AgentState(request=_request())
    snapshot = _evidence_snapshot(state)
    assert "token_usage" not in snapshot


def test_evidence_snapshot_omits_last_step_when_none():
    state = AgentState(request=_request())
    snapshot = _evidence_snapshot(state)
    assert "last_step" not in snapshot
