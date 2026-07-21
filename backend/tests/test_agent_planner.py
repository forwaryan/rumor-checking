from __future__ import annotations

from dataclasses import replace

from backend.app.agent import planner as planner_mod
from backend.app.agent.planner import LlmPlanner, RulePlanner, legal_actions
from backend.app.agent.state import AgentState
from backend.app.core.config import get_settings
from backend.app.models.schemas import AnalyzeRequest
from backend.app.services.agent_reasoner import NextActionPlan
from backend.app.services.analyze_pipeline import AnalyzePipeline


def _state_after(*done_actions, agent_synthesized=False) -> AgentState:
    state = AgentState(request=AnalyzeRequest(raw_input="x"))
    state.done_actions.extend(done_actions)
    state.agent_synthesized = agent_synthesized
    return state


# --- legal_actions sequencing -------------------------------------------------


def test_legal_actions_forces_early_steps_in_order():
    assert legal_actions(_state_after()) == [planner_mod.NORMALIZE]
    assert legal_actions(_state_after("normalize")) == [planner_mod.SEARCH]
    assert legal_actions(_state_after("normalize", "search_news")) == [planner_mod.RESOLVE]
    assert legal_actions(_state_after("normalize", "search_news", "resolve_question")) == [
        planner_mod.FOLLOW_UP
    ]


def test_legal_actions_branch_point_offers_investigate_or_synthesize():
    state = _state_after("normalize", "search_news", "resolve_question", "follow_up_retrieval")
    assert legal_actions(state) == [planner_mod.INVESTIGATE, planner_mod.SYNTHESIZE]


def test_legal_actions_after_successful_synthesis_short_circuits_to_finalize():
    state = _state_after(
        "normalize", "search_news", "resolve_question", "follow_up_retrieval",
        "investigate", "synthesize",
        agent_synthesized=True,
    )
    assert legal_actions(state) == [planner_mod.FINALIZE]


def test_legal_actions_after_failed_synthesis_runs_fallback_chain():
    state = _state_after(
        "normalize", "search_news", "resolve_question", "follow_up_retrieval",
        "investigate", "synthesize",
        agent_synthesized=False,
    )
    assert legal_actions(state) == [planner_mod.ENRICH]


# --- LlmPlanner arbitration + guard ------------------------------------------


class _FakeReasoner:
    def __init__(self, choice, *, raises=False):
        self._choice = choice
        self._raises = raises
        self.calls = 0

    def plan_next_action(self, *, evidence_snapshot, allowed_actions):
        self.calls += 1
        if self._raises:
            raise RuntimeError("planner boom")
        if self._choice is None:
            return None
        return NextActionPlan(next_action=self._choice, reason="fake")


def _branch_state() -> AgentState:
    return _state_after("normalize", "search_news", "resolve_question", "follow_up_retrieval")


def test_llm_planner_honors_legal_choice():
    reasoner = _FakeReasoner(planner_mod.SYNTHESIZE)
    planner = LlmPlanner(reasoner)
    assert planner.next_action(_branch_state()) == planner_mod.SYNTHESIZE
    assert reasoner.calls == 1


def test_llm_planner_does_not_call_llm_on_forced_step():
    reasoner = _FakeReasoner(planner_mod.SYNTHESIZE)
    planner = LlmPlanner(reasoner)
    # Only NORMALIZE is legal here -> no LLM call, deterministic.
    assert planner.next_action(_state_after()) == planner_mod.NORMALIZE
    assert reasoner.calls == 0


def test_llm_planner_defers_to_rule_on_none():
    reasoner = _FakeReasoner(None)
    planner = LlmPlanner(reasoner)
    # RulePlanner takes the first legal option at the branch point.
    assert planner.next_action(_branch_state()) == planner_mod.INVESTIGATE


def test_llm_planner_defers_to_rule_on_exception():
    reasoner = _FakeReasoner(None, raises=True)
    planner = LlmPlanner(reasoner)
    assert planner.next_action(_branch_state()) == planner_mod.INVESTIGATE


def test_llm_planner_that_always_defers_matches_rule_planner():
    reasoner = _FakeReasoner(None)  # always None -> always defers
    llm = LlmPlanner(reasoner)
    rule = RulePlanner()
    for done in [
        (),
        ("normalize",),
        ("normalize", "search_news", "resolve_question", "follow_up_retrieval"),
    ]:
        state = _state_after(*done)
        assert llm.next_action(state) == rule.next_action(state)


# --- full run with an LLM planner still yields a valid Report -----------------


class _SynthesizeNowReasoner:
    """Enabled reasoner whose planner always picks synthesize; synthesize itself
    returns None (no real LLM), so the runner takes the rule fallback chain."""

    enabled = True

    def resolve_question(self, *, event, retrieval_bundle):
        return None

    def synthesize(self, *, request, event, retrieval_bundle):
        return None

    def plan_next_action(self, *, evidence_snapshot, allowed_actions):
        return NextActionPlan(next_action=planner_mod.SYNTHESIZE, reason="commit")


def test_full_run_with_llm_planner_produces_report(monkeypatch):
    monkeypatch.setenv("AGENT_ORCHESTRATOR_ENABLED", "true")
    get_settings.cache_clear()
    pipeline = AnalyzePipeline()
    pipeline.agent_reasoner = _SynthesizeNowReasoner()

    from backend.app.agent.planner import LlmPlanner
    from backend.app.agent.runner import AgentRunner
    from backend.app.agent_tools.base import ToolContext

    ctx = ToolContext(
        settings=get_settings(),
        input_normalizer=pipeline.input_normalizer,
        retriever=pipeline.retriever,
        url_content_extractor=pipeline.input_normalizer.url_content_extractor,
        question_resolver=pipeline.question_resolver,
        agent_reasoner=pipeline.agent_reasoner,
        provider_enricher=pipeline.provider_enricher,
        claim_extractor=pipeline.claim_extractor,
        verdict_engine=pipeline.verdict_engine,
        timeline_builder=pipeline.timeline_builder,
        report_builder=pipeline.report_builder,
        content_check_builder=pipeline.content_check_builder,
        pipeline_trace_builder=pipeline.pipeline_trace_builder,
    )
    report = AgentRunner(ctx, planner=LlmPlanner(pipeline.agent_reasoner)).run(
        AnalyzeRequest(raw_input="晨星生物裁员40%是真的吗？", input_type="question")
    )
    assert report.mode in {"safe_mode", "partial_mode", "complete_mode"}
    assert report.provenance is not None
    assert report.claim_results
