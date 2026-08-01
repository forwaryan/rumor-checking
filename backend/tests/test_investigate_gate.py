from __future__ import annotations

from types import SimpleNamespace

from backend.app.agent.multi.merge_agent import MergeAgent
from backend.app.agent.multi.retrieval_agent import RetrievalAgent
from backend.app.agent.state import AgentState
from backend.app.models.schemas import AnalyzeRequest
from backend.app.services.retrieval_models import (
    LOW_EVIDENCE_GRADES,
    RetrievalBundle,
    SearchResult,
)


def _hit(result_id: str, tier: str, host: str) -> SearchResult:
    return SearchResult(
        case_id="real_search",
        query="q",
        result_id=result_id,
        title=f"title-{result_id}",
        url=f"https://{host}/{result_id}",
        source_name=host,
        published_at="2026-07-01",
        snippet="s",
        source_tier=tier,
    )


def _bundle(*hits: SearchResult) -> RetrievalBundle:
    return RetrievalBundle(query="q", canonical_results=tuple(hits))


def _state(bundle: RetrievalBundle | None) -> AgentState:
    state = AgentState(request=AnalyzeRequest(raw_input="x"))
    state.retrieval_bundle = bundle
    return state


def _ctx(lightweight: bool = True) -> SimpleNamespace:
    return SimpleNamespace(settings=SimpleNamespace(lightweight_agent_ready=lightweight))


# --- grade sanity: the property only ever emits A/B/C/D ---


def test_evidence_grade_uses_letters_not_weak_none():
    # Guards the root cause: consumers compared against "weak"/"none" but the
    # property emits letters, so investigate never triggered.
    assert _bundle().evidence_grade == "D"  # empty
    assert _bundle(_hit("r1", "C", "a.com")).evidence_grade == "C"  # low tier only
    assert _bundle(_hit("r1", "A", "a.com")).evidence_grade == "B"  # one high-trust
    assert _bundle(_hit("r1", "A", "a.com"), _hit("r2", "S", "b.com")).evidence_grade == "A"
    assert "weak" not in LOW_EVIDENCE_GRADES and "none" not in LOW_EVIDENCE_GRADES


# --- both agents must investigate on thin (C/D) evidence, and only then ---


def test_merge_agent_investigates_on_low_grade():
    ctx = _ctx()
    assert MergeAgent._should_investigate(_state(_bundle(_hit("r1", "C", "a.com"))), ctx) is True  # C
    assert MergeAgent._should_investigate(_state(_bundle()), ctx) is True  # D


def test_merge_agent_skips_investigate_on_strong_grade():
    ctx = _ctx()
    b_grade = _state(_bundle(_hit("r1", "A", "a.com")))  # B
    a_grade = _state(_bundle(_hit("r1", "A", "a.com"), _hit("r2", "S", "b.com")))  # A
    assert MergeAgent._should_investigate(b_grade, ctx) is False
    assert MergeAgent._should_investigate(a_grade, ctx) is False


def test_retrieval_agent_investigates_on_low_grade():
    agent = RetrievalAgent.__new__(RetrievalAgent)
    ctx = _ctx()
    assert agent._should_investigate(_state(_bundle(_hit("r1", "C", "a.com"))), ctx) is True
    assert agent._should_investigate(_state(_bundle(_hit("r1", "A", "a.com"))), ctx) is False


def test_investigate_gated_by_lightweight_flag_and_bundle():
    # The two real guards must still hold: no lightweight runtime, or no bundle.
    assert MergeAgent._should_investigate(_state(_bundle()), _ctx(lightweight=False)) is False
    assert MergeAgent._should_investigate(_state(None), _ctx()) is False
