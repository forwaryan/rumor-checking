from __future__ import annotations

from backend.app.agent import planner as planner_mod
from backend.app.agent.planner import Planner, RulePlanner
from backend.app.agent.state import AgentState
from backend.app.agent_tools import tools
from backend.app.agent_tools.base import ToolContext
from backend.app.models.schemas import AnalyzeRequest, Report

# Actions with no return value that just mutate state.
_SIMPLE_TOOLS = {
    planner_mod.NORMALIZE: tools.normalize,
    planner_mod.SEARCH: tools.search_news,
    planner_mod.RESOLVE: tools.resolve_question,
    planner_mod.FOLLOW_UP: tools.follow_up_retrieval,
    planner_mod.INVESTIGATE: tools.investigate,
    planner_mod.FETCH_URL: tools.fetch_url,
    planner_mod.ENRICH: tools.enrich,
    planner_mod.EXTRACT: tools.extract_claims,
    planner_mod.JUDGE: tools.judge_claims,
    planner_mod.TIMELINE: tools.build_timeline,
    planner_mod.FINALIZE: tools.finalize_report,
}

# Hard ceiling on loop iterations; the real stop condition is planner -> DONE.
_MAX_STEPS = 24


class AgentRunner:
    """Agent loop that orchestrates the rumor-check tools.

    The planner decides the next action from current state; the runner dispatches
    it to the matching tool, which reads/writes the shared AgentState. This is the
    same set of operations the legacy pipeline ran, but sequencing is now a
    first-class, pluggable decision rather than hard-coded control flow.
    """

    def __init__(self, ctx: ToolContext, planner: Planner | None = None) -> None:
        self.ctx = ctx
        self.planner = planner or RulePlanner()

    def run(self, request: AnalyzeRequest) -> Report:
        state = AgentState(request=request)
        state.max_url_fetches = int(getattr(self.ctx.settings, "agent_max_url_fetches", 0) or 0)
        for _ in range(_MAX_STEPS):
            action = self.planner.next_action(state)
            if action == planner_mod.DONE:
                break
            self._dispatch(action, state)
            state.done_actions.append(action)

        if state.report is None:
            raise RuntimeError("agent_runner_finished_without_report")
        return state.report

    def _dispatch(self, action: str, state: AgentState) -> None:
        if action == planner_mod.SYNTHESIZE:
            # synthesize signals success/failure via its return; state already
            # records agent_synthesized, which the planner branches on.
            tools.synthesize(self.ctx, state)
            return
        tool = _SIMPLE_TOOLS.get(action)
        if tool is None:
            raise RuntimeError(f"unknown_agent_action:{action}")
        tool(self.ctx, state)
