from __future__ import annotations

from dataclasses import replace

from backend.app.core.config import get_settings
from backend.app.models.schemas import AnalyzeRequest, NormalizedEvent
from backend.app.services.agent_reasoner import InvestigationPlan, KimiAgentReasoner
from backend.app.services.analyze_pipeline import AnalyzePipeline
from backend.app.services.retrieval_models import RetrievalBundle, SearchResult


def _result(result_id: str, tier: str, source_name: str, url: str) -> SearchResult:
    return SearchResult(
        case_id="t",
        query="q",
        result_id=result_id,
        title=f"title-{result_id}",
        url=url,
        source_name=source_name,
        published_at="2026-03-15T08:00:00+08:00",
        snippet="snippet",
        source_tier=tier,
    )


def _bundle(results, *, query: str = "q") -> RetrievalBundle:
    ordered = tuple(results)
    return RetrievalBundle(
        query=query,
        canonical_results=ordered,
        raw_results=ordered,
        provider_name="kimi",
    )


def _weak_bundle(query: str = "weak") -> RetrievalBundle:
    return _bundle([_result("c1", "C", "blog.example.com", "https://blog.example.com/1")], query=query)


def _strong_bundle(query: str = "strong") -> RetrievalBundle:
    return _bundle(
        [
            _result("s1", "S", "gov.example.com", "https://gov.example.com/notice"),
            _result("a1", "A", "news.example.com", "https://news.example.com/report"),
        ],
        query=query,
    )


def _event() -> NormalizedEvent:
    return NormalizedEvent(summary="s", input_type="question_only", raw_input="raw")


class FakePlanner:
    enabled = True

    def __init__(self, plans):
        self._plans = list(plans)
        self.calls = 0

    def plan_investigation(self, *, event, retrieval_bundle, round_index):
        self.calls += 1
        if not self._plans:
            return InvestigationPlan(should_continue=False, follow_up_query=None, reason="exhausted")
        return self._plans.pop(0)


class FakeRetriever:
    def __init__(self, bundle):
        self._bundle = bundle
        self.calls = []

    def retrieve_for_event(self, event, *, request_context=None):
        self.calls.append(request_context or {})
        return self._bundle


def _enabled_pipeline(monkeypatch, *, max_rounds: int = 1) -> AnalyzePipeline:
    monkeypatch.setenv("ANALYSIS_PROVIDER", "kimi")
    monkeypatch.setenv("KIMI_API_KEY", "test-key")
    monkeypatch.setenv("LIGHTWEIGHT_AGENT_ENABLED", "true")
    monkeypatch.setenv("AGENT_MAX_EXTRA_ROUNDS", str(max_rounds))
    get_settings.cache_clear()
    return AnalyzePipeline()


# --- planner unit tests -------------------------------------------------------


def test_plan_investigation_returns_none_when_disabled():
    reasoner = KimiAgentReasoner(
        settings=replace(get_settings(), analysis_provider="off", kimi_api_key=None)
    )
    plan = reasoner.plan_investigation(event=_event(), retrieval_bundle=_weak_bundle(), round_index=1)
    assert plan is None


def test_plan_investigation_parses_continue(monkeypatch):
    reasoner = KimiAgentReasoner(
        settings=replace(get_settings(), analysis_provider="kimi", kimi_api_key="k")
    )
    monkeypatch.setattr(
        reasoner,
        "_request_completion",
        lambda **kwargs: '{"should_continue": true, "follow_up_query": "海州 市场监管局 通报 酸奶", "reason": "need official"}',
    )
    plan = reasoner.plan_investigation(event=_event(), retrieval_bundle=_weak_bundle(), round_index=1)
    assert plan is not None
    assert plan.should_continue is True
    assert plan.follow_up_query and "海州" in plan.follow_up_query
    assert plan.reason == "need official"


def test_plan_investigation_parses_stop(monkeypatch):
    reasoner = KimiAgentReasoner(
        settings=replace(get_settings(), analysis_provider="kimi", kimi_api_key="k")
    )
    monkeypatch.setattr(
        reasoner,
        "_request_completion",
        lambda **kwargs: '{"should_continue": false, "follow_up_query": null, "reason": "enough"}',
    )
    plan = reasoner.plan_investigation(event=_event(), retrieval_bundle=_strong_bundle(), round_index=1)
    assert plan is not None
    assert plan.should_continue is False
    assert plan.follow_up_query is None


def test_plan_investigation_continue_without_query_is_downgraded(monkeypatch):
    reasoner = KimiAgentReasoner(
        settings=replace(get_settings(), analysis_provider="kimi", kimi_api_key="k")
    )
    monkeypatch.setattr(
        reasoner,
        "_request_completion",
        lambda **kwargs: '{"should_continue": true, "follow_up_query": null, "reason": "wants more but no query"}',
    )
    plan = reasoner.plan_investigation(event=_event(), retrieval_bundle=_weak_bundle(), round_index=1)
    assert plan is not None
    assert plan.should_continue is False
    assert plan.follow_up_query is None


# --- pipeline gate tests ------------------------------------------------------


def test_investigation_gate_skipped_when_disabled():
    # Runs under the autouse off+mock fixture: gate must stay inert.
    pipeline = AnalyzePipeline()
    retriever = FakeRetriever(_strong_bundle())
    pipeline.retriever = retriever
    original = _weak_bundle(query="q0")

    result = pipeline._run_investigation(
        request=AnalyzeRequest(raw_input="x"),
        event=_event(),
        retrieval_bundle=original,
    )

    assert result is original
    assert retriever.calls == []


def test_investigation_gate_adopts_stronger_bundle(monkeypatch):
    pipeline = _enabled_pipeline(monkeypatch)
    pipeline.agent_reasoner = FakePlanner(
        [InvestigationPlan(should_continue=True, follow_up_query="q2", reason="weak")]
    )
    retriever = FakeRetriever(_strong_bundle(query="q2-bundle"))
    pipeline.retriever = retriever

    result = pipeline._run_investigation(
        request=AnalyzeRequest(raw_input="x"),
        event=_event(),
        retrieval_bundle=_weak_bundle(query="q0"),
    )

    assert result.query == "q2-bundle"
    assert result.evidence_grade == "A"
    assert len(retriever.calls) == 1
    assert retriever.calls[0].get("force_retrieval_query") == "q2"


def test_investigation_gate_keeps_original_when_not_better(monkeypatch):
    pipeline = _enabled_pipeline(monkeypatch)
    pipeline.agent_reasoner = FakePlanner(
        [InvestigationPlan(should_continue=True, follow_up_query="q2", reason="weak")]
    )
    # Candidate is a *different* weak bundle with the same evidence quality.
    retriever = FakeRetriever(_weak_bundle(query="q_candidate"))
    pipeline.retriever = retriever

    original = _weak_bundle(query="q0")
    result = pipeline._run_investigation(
        request=AnalyzeRequest(raw_input="x"),
        event=_event(),
        retrieval_bundle=original,
    )

    assert result is original
    assert len(retriever.calls) == 1


def test_investigation_gate_stops_when_planner_says_stop(monkeypatch):
    pipeline = _enabled_pipeline(monkeypatch)
    pipeline.agent_reasoner = FakePlanner(
        [InvestigationPlan(should_continue=False, follow_up_query=None, reason="enough")]
    )
    retriever = FakeRetriever(_strong_bundle())
    pipeline.retriever = retriever

    original = _weak_bundle(query="q0")
    result = pipeline._run_investigation(
        request=AnalyzeRequest(raw_input="x"),
        event=_event(),
        retrieval_bundle=original,
    )

    assert result is original
    assert retriever.calls == []


def test_investigation_gate_respects_max_rounds(monkeypatch):
    pipeline = _enabled_pipeline(monkeypatch, max_rounds=1)
    # Two "continue" plans queued, but the cap is 1 round.
    planner = FakePlanner(
        [
            InvestigationPlan(should_continue=True, follow_up_query="q2", reason="r1"),
            InvestigationPlan(should_continue=True, follow_up_query="q3", reason="r2"),
        ]
    )
    pipeline.agent_reasoner = planner
    retriever = FakeRetriever(_strong_bundle(query="q2-bundle"))
    pipeline.retriever = retriever

    pipeline._run_investigation(
        request=AnalyzeRequest(raw_input="x"),
        event=_event(),
        retrieval_bundle=_weak_bundle(query="q0"),
    )

    assert planner.calls == 1
    assert len(retriever.calls) == 1
