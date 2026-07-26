from __future__ import annotations

from typing import List, Protocol

from backend.app.agent.state import AgentState


# Action names the runner knows how to dispatch (see runner._SIMPLE_TOOLS).
NORMALIZE = "normalize"
SEARCH = "search_news"
RESOLVE = "resolve_question"
FOLLOW_UP = "follow_up_retrieval"
INVESTIGATE = "investigate"
FETCH_URL = "fetch_url"
SYNTHESIZE = "synthesize"
ENRICH = "enrich"
EXTRACT = "extract_claims"
JUDGE = "judge_claims"
PER_CLAIM_SEARCH = "per_claim_search"
RE_JUDGE = "re_judge_claims"
TIMELINE = "build_timeline"
FINALIZE = "finalize_report"
DONE = "done"

# Actions the LLM planner is allowed to arbitrate between. Everything else is a
# forced data-dependency step (e.g. cannot judge before extracting), so we never
# spend an LLM call on it — only genuine branch points are delegated.
_LLM_DECIDABLE = {INVESTIGATE, FETCH_URL, SYNTHESIZE, PER_CLAIM_SEARCH, TIMELINE}


def legal_actions(state: AgentState) -> List[str]:
    """Actions that are valid to run next given current progress.

    This is the single source of truth for sequencing. RulePlanner takes the
    first entry (reproducing the legacy fixed order); LlmPlanner may choose among
    entries when more than one is an LLM-decidable branch point.
    """
    done = state.done_actions

    if NORMALIZE not in done:
        return [NORMALIZE]
    if SEARCH not in done:
        return [SEARCH]
    if RESOLVE not in done:
        return [RESOLVE]
    if FOLLOW_UP not in done:
        return [FOLLOW_UP]

    # Branch point: gather more evidence, or commit to synthesis. Both legal.
    # fetch_url is offered as an extra option but always AFTER the rule-path
    # default, so RulePlanner (takes index 0) never picks it -> parity holds.
    if INVESTIGATE not in done and SYNTHESIZE not in done:
        if _can_fetch(state):
            return [INVESTIGATE, FETCH_URL, SYNTHESIZE]
        return [INVESTIGATE, SYNTHESIZE]
    if SYNTHESIZE not in done:
        # After investigate: rule path goes straight to synthesize; the LLM may
        # instead fetch a page first (FETCH_URL after SYNTHESIZE keeps parity).
        if _can_fetch(state):
            return [SYNTHESIZE, FETCH_URL]
        return [SYNTHESIZE]

    # After synthesize: structured result short-circuits to finalize; otherwise
    # walk the rule fallback chain.
    if state.agent_synthesized:
        return [FINALIZE] if FINALIZE not in done else [DONE]

    if ENRICH not in done:
        return [ENRICH]
    if EXTRACT not in done:
        return [EXTRACT]
    if JUDGE not in done:
        return [JUDGE]
    # After judging: if weak claims exist AND we haven't exhausted iterations,
    # do per-claim targeted retrieval then re-judge; repeat until convergence or
    # max iterations reached. Re-entry is driven by two counters (never by
    # mutating done_actions): a search leads its re-judge by exactly one, so
    #   searches >  iterations  -> this round's search fired, re-judge is due
    #   searches == iterations  -> a fresh round may start (offer PER_CLAIM_SEARCH)
    # The whole loop is gated on TIMELINE not yet run: once the planner picks
    # TIMELINE to stop early (or the rule path reaches it), the loop is closed.
    if TIMELINE not in done:
        if state.per_claim_searches > state.per_claim_iterations:
            return [RE_JUDGE]
        if _has_weak_claims(state) and _can_iterate(state):
            # After at least one completed iteration, let the planner stop early.
            if state.per_claim_iterations > 0:
                return [PER_CLAIM_SEARCH, TIMELINE]
            return [PER_CLAIM_SEARCH]
        return [TIMELINE]
    if FINALIZE not in done:
        return [FINALIZE]
    return [DONE]


class Planner(Protocol):
    def next_action(self, state: AgentState) -> str:
        ...


def _can_fetch(state: AgentState) -> bool:
    """True when the fetch_url action is available: budget remains AND the
    current bundle has a canonical result whose body hasn't been fetched yet."""
    if len(state.fetched_bodies) >= state.max_url_fetches:
        return False
    bundle = state.retrieval_bundle
    if bundle is None:
        return False
    return any(
        r.url and r.result_id not in state.fetched_bodies and r.url not in state.fetched_urls
        for r in bundle.canonical_results
    )


def _has_weak_claims(state: AgentState) -> bool:
    """True when there are fact claims with insufficient evidence after judging."""
    if state.verdict is None:
        return False
    weak = sum(
        1 for cr in state.verdict.claim_results
        if cr.claim_type == "fact" and cr.verdict == "insufficient"
    )
    return weak > 0


def _can_iterate(state: AgentState) -> bool:
    """True when the per-claim search loop hasn't reached its iteration cap."""
    return state.per_claim_iterations < state.max_per_claim_iterations


class RulePlanner:
    """Deterministic planner: always takes the first legal action.

    This reproduces the legacy AnalyzePipeline.analyze() order exactly, so the
    agent runner on the zero-key off+mock path yields byte-identical Reports.
    """

    def next_action(self, state: AgentState) -> str:
        return legal_actions(state)[0]


class LlmPlanner:
    """Model-driven planner for the agent-first path.

    At a genuine branch point (more than one legal action, all LLM-decidable) it
    asks the reasoner to propose an ORDERED plan of intended actions, caches it,
    and consumes the head each step while that head is still legal. The cached plan
    is a forward-looking *intent*, not an authority: every head is re-checked
    against legal_actions before it runs, and the moment the plan diverges (head
    illegal, or plan exhausted) it is discarded and a fresh one is requested. So
    the model gets real plan-ahead leverage while legal_actions stays the absolute
    safety gate. Any missing/illegal LLM output defers to the wrapped RulePlanner,
    so the loop can never stall or pick an impossible step.
    """

    def __init__(self, agent_reasoner, fallback: Planner | None = None) -> None:
        self.agent_reasoner = agent_reasoner
        self.fallback = fallback or RulePlanner()
        # The remaining tail of the current proposed plan (heads already consumed).
        self._plan: list[str] = []

    def next_action(self, state: AgentState) -> str:
        options = legal_actions(state)
        if len(options) <= 1:
            # A forced (data-dependency) step means the branch context is gone;
            # drop any stale plan so we re-plan at the next real branch point.
            self._plan = []
            return options[0]
        if not all(action in _LLM_DECIDABLE for action in options):
            self._plan = []
            return self.fallback.next_action(state)

        # 1. Consume the cached plan while its head is a legal option.
        while self._plan:
            head = self._plan.pop(0)
            if head in options:
                return head
            # Divergence: the cached plan no longer fits reality. Discard and re-plan.
            self._plan = []
            break

        # 2. No usable cached plan — ask the reasoner for a fresh sequence.
        plan = self._request_sequence(state, options)
        if plan is not None and plan.actions and plan.actions[0] in options:
            self._plan = list(plan.actions[1:])
            return plan.actions[0]

        # 3. Sequence planning unavailable — fall back to a single-step choice
        #    (keeps reasoners that only implement plan_next_action working).
        choice = self._request_single_step(state, options)
        if choice is not None and choice in options:
            return choice

        # 4. Nothing usable from the LLM — defer to the deterministic rule path.
        return self.fallback.next_action(state)

    def _request_sequence(self, state: AgentState, options: list[str]):
        planner = getattr(self.agent_reasoner, "plan_action_sequence", None)
        if planner is None:
            return None
        try:
            return planner(
                evidence_snapshot=_evidence_snapshot(state),
                allowed_actions=options,
            )
        except Exception:
            return None

    def _request_single_step(self, state: AgentState, options: list[str]) -> str | None:
        planner = getattr(self.agent_reasoner, "plan_next_action", None)
        if planner is None:
            return None
        try:
            plan = planner(
                evidence_snapshot=_evidence_snapshot(state),
                allowed_actions=options,
            )
        except Exception:
            return None
        return plan.next_action if plan is not None else None


def _evidence_snapshot(state: AgentState) -> dict:
    bundle = state.retrieval_bundle
    event = state.resolved_event or state.normalized_event
    snapshot: dict = {
        "done_actions": list(state.done_actions),
        "investigation_rounds": state.investigation_rounds,
        "event_title": getattr(event, "title", None),
        "input_type": getattr(event, "input_type", None),
    }
    if bundle is not None:
        snapshot["evidence"] = {
            "evidence_grade": bundle.evidence_grade,
            "canonical_result_count": len(bundle.canonical_results),
            "high_trust_result_count": bundle.high_trust_result_count,
            "independent_high_trust_source_count": bundle.independent_high_trust_source_count,
            "conflict_signals": list(bundle.conflict_signals),
            # Top results by content, not just counts: the planner needs to judge
            # whether the *substance* of what was found actually settles the claim
            # before it decides to search again vs. commit to synthesis.
            "top_results": _top_result_previews(bundle),
        }
    return snapshot


# How many evidence previews to include, and how much of each snippet, in the
# planner snapshot. Bounded so the planner prompt stays small and fast.
_SNAPSHOT_MAX_RESULTS = 5
_SNAPSHOT_SNIPPET_CHARS = 160


def _top_result_previews(bundle) -> list[dict]:
    """Compact, content-bearing previews of the strongest canonical results.

    Ranks high-trust, non-aggregator, higher-tier sources first (the same shape
    fetch_url uses) so the planner sees the most decision-relevant evidence, then
    trims each to a bounded preview so the prompt stays cheap."""
    def rank(result):
        return (
            1 if result.is_high_trust else 0,
            0 if result.is_aggregator_source else 1,
            result.tier_weight,
        )

    ranked = sorted(bundle.canonical_results, key=rank, reverse=True)
    previews: list[dict] = []
    for result in ranked[:_SNAPSHOT_MAX_RESULTS]:
        snippet = (result.snippet or "").strip()
        if len(snippet) > _SNAPSHOT_SNIPPET_CHARS:
            snippet = snippet[:_SNAPSHOT_SNIPPET_CHARS].rstrip() + "…"
        previews.append(
            {
                "source_name": result.source_name or "未知来源",
                "source_tier": result.source_tier,
                "high_trust": result.is_high_trust,
                "published_at": result.published_at or None,
                "title": (result.title or "").strip() or None,
                "snippet": snippet or None,
            }
        )
    return previews
