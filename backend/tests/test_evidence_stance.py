"""Tests for per-evidence stance parsing in agent_reasoner."""
from __future__ import annotations

from backend.app.models.schemas import EvidenceItem
from backend.app.services.agent_reasoner import LlmAgentReasoner
from backend.app.services.retrieval_models import SearchResult


def _hit(result_id: str, tier: str = "B") -> SearchResult:
    return SearchResult(
        case_id="real_search",
        query="q",
        result_id=result_id,
        title=f"title-{result_id}",
        url=f"https://example.com/{result_id}",
        source_name="example.com",
        published_at="2026-07-01",
        snippet=f"snippet-{result_id}",
        source_tier=tier,
    )


def _reasoner() -> LlmAgentReasoner:
    from backend.app.core.config import get_settings
    return LlmAgentReasoner(settings=get_settings())


def test_evidence_from_entries_parses_stance_and_quote():
    reasoner = _reasoner()
    result_map = {"r1": _hit("r1"), "r2": _hit("r2")}
    entries = [
        {"result_id": "r1", "stance": "supports", "quote": "官方确认"},
        {"result_id": "r2", "stance": "refutes", "quote": "系谣言"},
    ]
    items = reasoner._evidence_from_entries(
        result_map=result_map,
        evidence_entries=entries,
        evidence_ids=[],
        verdict="conflicting",
    )
    assert len(items) == 2
    assert items[0].stance == "supports"
    assert items[0].stance_quote == "官方确认"
    assert items[1].stance == "refutes"
    assert items[1].stance_quote == "系谣言"


def test_evidence_from_entries_falls_back_to_ids():
    reasoner = _reasoner()
    result_map = {"r1": _hit("r1")}
    items = reasoner._evidence_from_entries(
        result_map=result_map,
        evidence_entries=None,
        evidence_ids=["r1"],
        verdict="supported",
    )
    assert len(items) == 1
    assert items[0].stance is None


def test_evidence_from_entries_infers_stance_on_invalid():
    reasoner = _reasoner()
    result_map = {"r1": _hit("r1")}
    entries = [{"result_id": "r1", "stance": "bogus", "quote": "x"}]
    items = reasoner._evidence_from_entries(
        result_map=result_map,
        evidence_entries=entries,
        evidence_ids=[],
        verdict="refuted",
    )
    assert len(items) == 1
    assert items[0].stance == "refutes"


def test_evidence_from_entries_caps_at_four():
    reasoner = _reasoner()
    result_map = {f"r{i}": _hit(f"r{i}") for i in range(6)}
    entries = [{"result_id": f"r{i}", "stance": "supports", "quote": "x"} for i in range(6)]
    items = reasoner._evidence_from_entries(
        result_map=result_map,
        evidence_entries=entries,
        evidence_ids=[],
        verdict="supported",
    )
    assert len(items) == 4
