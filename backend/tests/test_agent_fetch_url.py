from __future__ import annotations

from dataclasses import dataclass

from backend.app.agent import planner as planner_mod
from backend.app.agent.planner import RulePlanner, legal_actions
from backend.app.agent.state import AgentState
from backend.app.agent_tools import tools
from backend.app.models.schemas import AnalyzeRequest, MockFetchResult
from backend.app.services.retrieval_models import RetrievalBundle, SearchResult


def _result(result_id, tier, source, url):
    return SearchResult(
        case_id="t",
        query="q",
        result_id=result_id,
        title=f"title-{result_id}",
        url=url,
        source_name=source,
        published_at="2026-03-15T08:00:00+08:00",
        snippet="short snippet",
        source_tier=tier,
    )


def _bundle(results):
    ordered = tuple(results)
    return RetrievalBundle(query="q", canonical_results=ordered, raw_results=ordered, provider_name="kimi")


def _branch_state(*, max_fetches, results=None):
    """State sitting at the evidence branch (normalize..follow_up done)."""
    state = AgentState(request=AnalyzeRequest(raw_input="x"))
    state.done_actions.extend(["normalize", "search_news", "resolve_question", "follow_up_retrieval"])
    state.max_url_fetches = max_fetches
    state.retrieval_bundle = _bundle(
        results
        or [
            _result("r1", "C", "blog.example.com", "https://blog.example.com/1"),
            _result("r2", "S", "gov.example.com", "https://gov.example.com/notice"),
        ]
    )
    return state


# --- planner: fetch_url availability + parity --------------------------------


def test_branch_offers_fetch_url_when_budget_and_urls_available():
    state = _branch_state(max_fetches=1)
    assert legal_actions(state) == [planner_mod.INVESTIGATE, planner_mod.FETCH_URL, planner_mod.SYNTHESIZE]


def test_branch_omits_fetch_url_when_cap_zero():
    state = _branch_state(max_fetches=0)
    assert legal_actions(state) == [planner_mod.INVESTIGATE, planner_mod.SYNTHESIZE]


def test_rule_planner_never_picks_fetch_url():
    # RulePlanner takes index 0 -> INVESTIGATE, never FETCH_URL. Parity preserved.
    state = _branch_state(max_fetches=1)
    assert RulePlanner().next_action(state) == planner_mod.INVESTIGATE


def test_fetch_url_offered_after_investigate_but_synthesize_stays_first():
    state = _branch_state(max_fetches=1)
    state.done_actions.append("investigate")
    options = legal_actions(state)
    assert options[0] == planner_mod.SYNTHESIZE  # rule path still goes to synthesize
    assert planner_mod.FETCH_URL in options


def test_branch_omits_fetch_url_when_all_urls_fetched():
    state = _branch_state(max_fetches=2)
    state.fetched_bodies["r1"] = "body"
    state.fetched_bodies["r2"] = "body"
    assert legal_actions(state) == [planner_mod.INVESTIGATE, planner_mod.SYNTHESIZE]


# --- fetch_url tool: selection, dedup, grounding-safe storage, failure --------


@dataclass
class _FakeExtractor:
    result: object
    calls: int = 0

    def extract(self, url):
        self.calls += 1
        return self.result


class _FakeCache:
    def __init__(self, result=None):
        self.result = result
        self.read_urls = []
        self.writes = []

    def read(self, *, url):
        self.read_urls.append(url)
        return self.result

    def write(self, *, url, result):
        self.writes.append((url, result))


class _Settings:
    url_fetch_cache_enabled = True


class _Ctx:
    def __init__(self, extractor, cache=None, settings=None):
        self.settings = settings or _Settings()
        self.url_content_extractor = extractor
        self.url_fetch_cache = cache or _FakeCache()


def test_fetch_url_picks_highest_trust_and_stores_by_result_id():
    state = _branch_state(max_fetches=1)
    extractor = _FakeExtractor(MockFetchResult(status="ok", body="full authoritative body text"))
    cache = _FakeCache()
    ctx = _Ctx(extractor, cache=cache)
    tools.fetch_url(ctx, state)
    # r2 is tier S (high trust) -> chosen over r1 tier C.
    assert "r2" in state.fetched_bodies
    assert state.fetched_bodies["r2"] == "full authoritative body text"
    assert "https://gov.example.com/notice" in state.fetched_urls
    assert extractor.calls == 1
    assert cache.writes[0][0] == "https://gov.example.com/notice"


def test_fetch_url_reuses_cached_body_without_refetching():
    state = _branch_state(max_fetches=1)
    extractor = _FakeExtractor(MockFetchResult(status="ok", body="network body"))
    cache = _FakeCache(MockFetchResult(status="ok", body="cached authoritative body"))
    tools.fetch_url(_Ctx(extractor, cache=cache), state)
    assert state.fetched_bodies["r2"] == "cached authoritative body"
    assert extractor.calls == 0


def test_fetch_url_dedups_already_fetched():
    state = _branch_state(max_fetches=2)
    state.fetched_bodies["r2"] = "already"
    state.fetched_urls.add("https://gov.example.com/notice")
    ctx = _Ctx(_FakeExtractor(MockFetchResult(status="ok", body="new body for r1")))
    tools.fetch_url(ctx, state)
    # r2 skipped -> r1 fetched instead.
    assert "r1" in state.fetched_bodies
    assert state.fetched_bodies["r1"] == "new body for r1"


def test_fetch_url_truncates_body():
    state = _branch_state(max_fetches=1)
    big = "x" * 10000
    ctx = _Ctx(_FakeExtractor(MockFetchResult(status="ok", body=big)))
    tools.fetch_url(ctx, state)
    assert len(state.fetched_bodies["r2"]) == tools._FETCH_BODY_MAX_CHARS


def test_fetch_url_degrades_on_empty_body():
    state = _branch_state(max_fetches=1)
    ctx = _Ctx(_FakeExtractor(MockFetchResult(status="error", body=None)))
    tools.fetch_url(ctx, state)
    # No body stored, but url marked so we don't retry the same dead page.
    assert state.fetched_bodies == {}
    assert "https://gov.example.com/notice" in state.fetched_urls


def test_fetch_url_degrades_on_extractor_exception():
    state = _branch_state(max_fetches=1)

    class _Boom:
        def extract(self, url):
            raise RuntimeError("network down")

    tools.fetch_url(_Ctx(_Boom()), state)
    assert state.fetched_bodies == {}
    assert "https://gov.example.com/notice" in state.fetched_urls
