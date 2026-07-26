"""Tests for dynamic tool discovery (P1)."""
from __future__ import annotations

from backend.app.agent_tools import tools as _tools  # noqa: F401 — triggers registration
from backend.app.agent_tools.base import get_all_tool_specs, get_tool_fn, get_tool_spec


def test_all_tools_registered():
    """Verify all expected tools are in the registry after import."""
    expected = {
        "normalize", "search_news", "resolve_question", "follow_up_retrieval",
        "investigate", "fetch_url", "synthesize", "enrich", "extract_claims",
        "judge_claims", "per_claim_search", "re_judge_claims", "build_timeline",
        "finalize_report",
    }
    specs = get_all_tool_specs()
    registered_names = {s.name for s in specs}
    assert expected.issubset(registered_names), f"Missing: {expected - registered_names}"


def test_get_tool_fn_returns_callable():
    fn = get_tool_fn("normalize")
    assert fn is not None
    assert callable(fn)


def test_get_tool_fn_returns_none_for_unknown():
    assert get_tool_fn("nonexistent_tool") is None


def test_get_tool_spec_has_metadata():
    spec = get_tool_spec("normalize")
    assert spec is not None
    assert spec.critical is True
    assert spec.retries == 2

    spec_search = get_tool_spec("search_news")
    assert spec_search is not None
    assert spec_search.critical is True

    spec_investigate = get_tool_spec("investigate")
    assert spec_investigate is not None
    assert spec_investigate.critical is False
    assert spec_investigate.retries == 1


def test_per_claim_search_is_parallelizable():
    spec = get_tool_spec("per_claim_search")
    assert spec is not None
    assert spec.parallelizable is True


def test_registry_dispatch_matches_direct_call():
    """The function in the registry is the exact same object as the module-level function."""
    from backend.app.agent_tools import tools as t
    assert get_tool_fn("normalize") is t.normalize
    assert get_tool_fn("search_news") is t.search_news
    assert get_tool_fn("synthesize") is t.synthesize
    assert get_tool_fn("finalize_report") is t.finalize_report
