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


def test_time_exhausted_forces_shortest_path_to_synthesize():
    """When the wall-clock deadline has passed, the planner skips optional
    evidence-gathering (investigate) and heads straight to synthesize — the same
    soft-landing the token-budget fast-path takes."""
    state = _state_after("normalize", "search_news", "resolve_question", "follow_up_retrieval")
    state.time_exhausted = True
    assert legal_actions(state) == [planner_mod.SYNTHESIZE]


def test_time_exhausted_still_produces_report_via_fallback_chain():
    """Even if synthesis didn't structure a result, time-exhausted planning walks
    the rule fallback chain to a finalize (never stalls)."""
    state = _state_after(
        "normalize", "search_news", "resolve_question", "follow_up_retrieval", "synthesize",
        agent_synthesized=False,
    )
    state.time_exhausted = True
    # Not agent_synthesized → fast-path continues down enrich→extract→…→finalize.
    assert legal_actions(state) == [planner_mod.ENRICH]


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


# --- counter-driven per-claim search→re-judge loop ---------------------------


def _weak_verdict():
    from backend.app.models.schemas import ClaimResult
    from backend.app.services.verdict_engine import VerdictEvaluation

    return VerdictEvaluation(
        claim_results=[
            ClaimResult(claim="c", claim_type="fact", verdict="insufficient", confidence="low", notes="")
        ],
        evidence=[],
        evidence_grade="D",
        evidence_source="retrieval_live",
    )


def _judged_state(**counters) -> AgentState:
    state = _state_after(
        "normalize", "search_news", "resolve_question", "follow_up_retrieval",
        "investigate", "synthesize", "enrich", "extract_claims", "judge_claims",
    )
    state.verdict = _weak_verdict()
    for key, value in counters.items():
        setattr(state, key, value)
    return state


def test_loop_reentry_is_counter_driven_not_done_actions():
    # A fresh round with a weak verdict offers a per-claim search.
    fresh = _judged_state(per_claim_searches=0, per_claim_iterations=0)
    assert legal_actions(fresh) == [planner_mod.PER_CLAIM_SEARCH]

    # Search fired (counter leads by 1) -> re-judge is the only legal next step,
    # even though PER_CLAIM_SEARCH is already in done_actions.
    searched = _judged_state(per_claim_searches=1, per_claim_iterations=0)
    searched.done_actions.append("per_claim_search")
    assert legal_actions(searched) == [planner_mod.RE_JUDGE]

    # Re-judge closed the gap; still weak and under cap -> a fresh round is
    # offered again alongside the early-stop option.
    reentered = _judged_state(per_claim_searches=1, per_claim_iterations=1)
    reentered.done_actions.extend(["per_claim_search", "re_judge_claims"])
    assert legal_actions(reentered) == [planner_mod.PER_CLAIM_SEARCH, planner_mod.TIMELINE]


def test_loop_closes_at_iteration_cap():
    capped = _judged_state(per_claim_searches=3, per_claim_iterations=3)
    assert legal_actions(capped) == [planner_mod.TIMELINE]


def test_loop_closes_once_timeline_ran_even_with_weak_claims():
    # The planner may pick TIMELINE to stop early; once it has run, the loop must
    # not re-open even though weak claims and iteration budget remain.
    stopped = _judged_state(per_claim_searches=1, per_claim_iterations=1)
    stopped.done_actions.extend(["per_claim_search", "re_judge_claims", "build_timeline"])
    assert legal_actions(stopped) == [planner_mod.FINALIZE]


# --- rich observation snapshot -----------------------------------------------


def _bundle_with(*results):
    from backend.app.services.retrieval_models import RetrievalBundle

    return RetrievalBundle(query="q", provider_name="live", canonical_results=tuple(results))


def _result(result_id, *, tier, source, title, snippet, high_trust_ok=True):
    from backend.app.services.retrieval_models import SearchResult

    return SearchResult(
        case_id="c", query="q", result_id=result_id, title=title,
        url=f"https://example.com/{result_id}", source_name=source,
        published_at="2026-07-01", snippet=snippet, source_tier=tier,
    )


def test_snapshot_includes_ranked_trimmed_top_results():
    from backend.app.agent.planner import _evidence_snapshot

    weak = _result("r2", tier="C", source="微博", title="网友爆料", snippet="有人说")
    strong = _result("r1", tier="S", source="新华社", title="官方通报", snippet="确认。" * 100)
    state = _state_after("normalize", "search_news")
    state.retrieval_bundle = _bundle_with(weak, strong)

    top = _evidence_snapshot(state)["evidence"]["top_results"]
    # High-trust S-tier ranks ahead of the low-trust C-tier hit.
    assert top[0]["source_name"] == "新华社"
    assert top[0]["high_trust"] is True
    # Long snippets are trimmed with an ellipsis so the prompt stays bounded.
    assert top[0]["snippet"].endswith("…")
    assert len(top[0]["snippet"]) <= 161


def test_snapshot_without_bundle_has_no_evidence_key():
    from backend.app.agent.planner import _evidence_snapshot

    snapshot = _evidence_snapshot(_state_after("normalize"))
    assert "evidence" not in snapshot
    assert snapshot["done_actions"] == ["normalize"]


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


# --- LlmPlanner sequence proposal + legality gate ----------------------------


class _SequenceReasoner:
    """Reasoner that proposes a fixed action sequence once, then records reuse."""

    def __init__(self, actions):
        from backend.app.services.agent_reasoner import ActionSequencePlan

        self._actions = actions
        self._plan_cls = ActionSequencePlan
        self.calls = 0

    def plan_action_sequence(self, *, evidence_snapshot, allowed_actions):
        self.calls += 1
        if self._actions is None:
            return None
        return self._plan_cls(actions=list(self._actions), reason="seq")


def test_llm_planner_consumes_cached_sequence_without_re_asking():
    # Propose [investigate, synthesize]. At the first branch (investigate/synthesize)
    # the head 'investigate' runs; the plan is cached so the next branch reuses
    # 'synthesize' with NO second LLM call.
    reasoner = _SequenceReasoner([planner_mod.INVESTIGATE, planner_mod.SYNTHESIZE])
    planner = LlmPlanner(reasoner)

    branch = _branch_state()
    assert planner.next_action(branch) == planner_mod.INVESTIGATE
    assert reasoner.calls == 1

    # After investigate, the branch offers [synthesize, ...]; cached head is used.
    after_investigate = _state_after(
        "normalize", "search_news", "resolve_question", "follow_up_retrieval", "investigate"
    )
    assert planner.next_action(after_investigate) == planner_mod.SYNTHESIZE
    assert reasoner.calls == 1  # no re-plan; served from cache


def test_llm_planner_discards_plan_when_head_becomes_illegal():
    # A cached plan whose head is not among the current branch options must be
    # discarded and a fresh sequence requested (rather than served from cache).
    reasoner = _SequenceReasoner([planner_mod.INVESTIGATE, planner_mod.SYNTHESIZE])
    planner = LlmPlanner(reasoner)
    # Prime a stale tail whose head (fetch_url) is illegal at this branch, which
    # offers only [investigate, synthesize].
    planner._plan = [planner_mod.FETCH_URL, planner_mod.SYNTHESIZE]

    result = planner.next_action(_branch_state())
    assert result == planner_mod.INVESTIGATE  # head of the freshly requested plan
    assert reasoner.calls == 1  # stale plan discarded -> one re-plan happened


def test_llm_planner_rejects_sequence_with_illegal_first_step():
    # A proposed head not in the branch options is rejected; with no single-step
    # method available the planner defers to the rule fallback (INVESTIGATE).
    reasoner = _SequenceReasoner([planner_mod.FINALIZE, planner_mod.SYNTHESIZE])
    planner = LlmPlanner(reasoner)
    assert planner.next_action(_branch_state()) == planner_mod.INVESTIGATE


def test_llm_planner_forced_step_clears_stale_plan():
    reasoner = _SequenceReasoner([planner_mod.SYNTHESIZE])
    planner = LlmPlanner(reasoner)
    planner._plan = [planner_mod.SYNTHESIZE]  # simulate a leftover plan tail
    # A forced single-option step must clear the cached plan.
    assert planner.next_action(_state_after()) == planner_mod.NORMALIZE
    assert planner._plan == []


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
