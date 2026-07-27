"""Regression tests for wall-clock soft-landing behaviour at the tool level."""
from __future__ import annotations

from unittest.mock import MagicMock

from backend.app.agent.state import AgentState
from backend.app.agent_tools import tools
from backend.app.models.schemas import AnalyzeRequest, NormalizedEvent
from backend.app.services.question_resolver import QuestionResolution


def _question_state(*, time_exhausted: bool, follow_up_query: str | None) -> AgentState:
    state = AgentState(request=AnalyzeRequest(raw_input="小米汽车出事了吗"))
    state.time_exhausted = time_exhausted
    event = NormalizedEvent(summary="s", input_type="question_only", raw_input="x")
    state.resolved_event = event
    state.question_resolution = QuestionResolution(
        event=event, follow_up_query=follow_up_query, selected_result=None
    )
    return state


def test_follow_up_skips_network_when_time_exhausted():
    """After the wall-clock deadline fires, follow_up_retrieval must not spend a
    network round-trip even though a follow_up_query exists — that's the whole
    point of the soft-landing."""
    state = _question_state(time_exhausted=True, follow_up_query="小米 汽车 事故")
    ctx = MagicMock()

    tools.follow_up_retrieval(ctx, state)

    assert not ctx.retriever.retrieve_for_event.called
    assert state.follow_up_used is False


def test_follow_up_runs_network_when_time_remains():
    """Sanity check the other side: with time left and a query present, the
    follow-up retrieval still fires (unchanged behaviour)."""
    state = _question_state(time_exhausted=False, follow_up_query="小米 汽车 事故")
    ctx = MagicMock()
    ctx.retriever.retrieve_for_event.return_value = MagicMock(
        canonical_results=(), matched_case_id=None
    )

    tools.follow_up_retrieval(ctx, state)

    assert ctx.retriever.retrieve_for_event.called
