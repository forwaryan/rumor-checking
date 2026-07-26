"""Tests for state isolation (P1)."""
from __future__ import annotations

import pytest

from backend.app.agent.state import AgentState, TokenUsage
from backend.app.agent.state_isolation import (
    StateSlice,
    create_slice,
    merge_slices,
)
from backend.app.models.schemas import AnalyzeRequest


def _make_state() -> AgentState:
    state = AgentState(request=AnalyzeRequest(raw_input="test"))
    state.done_actions = ["normalize", "search_news"]
    state.fetched_bodies = {"r1": "body1"}
    state.fetched_urls = {"https://a.com"}
    return state


# --- StateSlice read/write ---


def test_slice_read_from_snapshot():
    state = _make_state()
    s = create_slice(state)
    assert s.get("done_actions") == ["normalize", "search_news"]
    assert s.get("fetched_bodies") == {"r1": "body1"}


def test_slice_write_to_delta():
    state = _make_state()
    s = create_slice(state)
    s.set("investigation_rounds", 2)
    assert s.get("investigation_rounds") == 2
    # Parent unchanged
    assert state.investigation_rounds == 0


def test_slice_write_overrides_read():
    state = _make_state()
    s = create_slice(state)
    s.set("done_actions", ["normalize", "search_news", "investigate"])
    assert s.get("done_actions") == ["normalize", "search_news", "investigate"]
    # Original unchanged
    assert state.done_actions == ["normalize", "search_news"]


def test_slice_immutable_fields_raise():
    state = _make_state()
    s = create_slice(state)
    with pytest.raises(ValueError, match="Cannot write.*request"):
        s.set("request", AnalyzeRequest(raw_input="hack"))
    with pytest.raises(ValueError, match="Cannot write.*cancelled"):
        s.set("cancelled", True)


def test_slice_written_fields_tracking():
    state = _make_state()
    s = create_slice(state)
    s.set("investigation_rounds", 1)
    s.set("per_claim_searches", 2)
    assert s.written_fields == {"investigation_rounds", "per_claim_searches"}


def test_slice_to_state():
    state = _make_state()
    s = create_slice(state)
    s.set("investigation_rounds", 3)
    materialized = s.to_state()
    assert materialized.investigation_rounds == 3
    assert materialized.done_actions == ["normalize", "search_news"]


# --- merge_slices ---


def test_merge_additive_done_actions():
    state = _make_state()
    s1 = create_slice(state)
    s2 = create_slice(state)
    s1.set("done_actions", ["investigate"])
    s2.set("done_actions", ["fetch_url"])
    merge_slices(state, [s1, s2])
    # Original actions preserved, new ones added
    assert "normalize" in state.done_actions
    assert "search_news" in state.done_actions
    assert "investigate" in state.done_actions
    assert "fetch_url" in state.done_actions


def test_merge_additive_fetched_bodies():
    state = _make_state()
    s1 = create_slice(state)
    s2 = create_slice(state)
    s1.set("fetched_bodies", {"r2": "body2"})
    s2.set("fetched_bodies", {"r3": "body3"})
    merge_slices(state, [s1, s2])
    assert state.fetched_bodies == {"r1": "body1", "r2": "body2", "r3": "body3"}


def test_merge_additive_fetched_urls():
    state = _make_state()
    s1 = create_slice(state)
    s2 = create_slice(state)
    s1.set("fetched_urls", {"https://b.com"})
    s2.set("fetched_urls", {"https://c.com"})
    merge_slices(state, [s1, s2])
    assert state.fetched_urls == {"https://a.com", "https://b.com", "https://c.com"}


def test_merge_last_writer_wins():
    state = _make_state()
    s1 = create_slice(state)
    s2 = create_slice(state)
    s1.set("investigation_rounds", 1)
    s2.set("investigation_rounds", 2)
    merge_slices(state, [s1, s2])
    # Last slice wins
    assert state.investigation_rounds == 2


def test_merge_no_duplicate_done_actions():
    state = _make_state()
    s1 = create_slice(state)
    s2 = create_slice(state)
    # Both try to add "investigate"
    s1.set("done_actions", ["investigate"])
    s2.set("done_actions", ["investigate"])
    merge_slices(state, [s1, s2])
    assert state.done_actions.count("investigate") == 1


def test_merge_immutable_fields_ignored():
    state = _make_state()
    s = StateSlice(state)
    # Force a write to delta bypassing the check (simulating corruption)
    s._delta["request"] = AnalyzeRequest(raw_input="hacked")
    s._written_fields.add("request")
    merge_slices(state, [s])
    # Should be ignored during merge
    assert state.request.raw_input == "test"


def test_merge_empty_slices():
    state = _make_state()
    merge_slices(state, [])
    # State unchanged
    assert state.done_actions == ["normalize", "search_news"]


def test_multiple_slices_independent():
    """Two slices can't see each other's writes."""
    state = _make_state()
    s1 = create_slice(state)
    s2 = create_slice(state)
    s1.set("investigation_rounds", 5)
    # s2 still reads from the snapshot
    assert s2.get("investigation_rounds") == 0
