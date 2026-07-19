from __future__ import annotations

from typing import List, Protocol

from backend.app.agent.state import AgentState


# Action names the runner knows how to dispatch (see runner._SIMPLE_TOOLS).
NORMALIZE = "normalize"
SEARCH = "search_news"
RESOLVE = "resolve_question"
FOLLOW_UP = "follow_up_retrieval"
INVESTIGATE = "investigate"
SYNTHESIZE = "synthesize"
ENRICH = "enrich"
EXTRACT = "extract_claims"
JUDGE = "judge_claims"
TIMELINE = "build_timeline"
FINALIZE = "finalize_report"
DONE = "done"

# Actions the LLM planner is allowed to arbitrate between. Everything else is a
# forced data-dependency step (e.g. cannot judge before extracting), so we never
# spend an LLM call on it — only genuine branch points are delegated.
_LLM_DECIDABLE = {INVESTIGATE, SYNTHESIZE}


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
    if INVESTIGATE not in done and SYNTHESIZE not in done:
        return [INVESTIGATE, SYNTHESIZE]
    if SYNTHESIZE not in done:
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
    if TIMELINE not in done:
        return [TIMELINE]
    if FINALIZE not in done:
        return [FINALIZE]
    return [DONE]


class Planner(Protocol):
    def next_action(self, state: AgentState) -> str:
        ...


class RulePlanner:
    """Deterministic planner: always takes the first legal action.

    This reproduces the legacy AnalyzePipeline.analyze() order exactly, so the
    agent runner on the zero-key off+mock path yields byte-identical Reports.
    """

    def next_action(self, state: AgentState) -> str:
        return legal_actions(state)[0]


class LlmPlanner:
    """Model-driven planner for the agent-first path.

    At genuine branch points (more than one legal action, all LLM-decidable) it
    asks the reasoner to choose. Everything else — forced data-dependency steps —
    advances deterministically. Any missing/illegal LLM choice defers to the
    wrapped RulePlanner, so the loop can never stall or pick an impossible step.
    """

    def __init__(self, agent_reasoner, fallback: Planner | None = None) -> None:
        self.agent_reasoner = agent_reasoner
        self.fallback = fallback or RulePlanner()

    def next_action(self, state: AgentState) -> str:
        options = legal_actions(state)
        if len(options) <= 1:
            return options[0]
        if not all(action in _LLM_DECIDABLE for action in options):
            return self.fallback.next_action(state)

        plan = None
        try:
            plan = self.agent_reasoner.plan_next_action(
                evidence_snapshot=_evidence_snapshot(state),
                allowed_actions=options,
            )
        except Exception:
            plan = None
        if plan is not None and plan.next_action in options:
            return plan.next_action
        return self.fallback.next_action(state)


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
        }
    return snapshot
