from __future__ import annotations

import logging
from typing import Optional

from backend.app.agent import planner as planner_mod
from backend.app.agent.planner import Planner, RulePlanner
from backend.app.agent.state import AgentState, StepOutcome
from backend.app.agent_tools import tools
from backend.app.agent_tools.base import ToolContext
from backend.app.models.schemas import AnalyzeRequest, Report
from backend.app.services.progress import emit_log

logger = logging.getLogger(__name__)

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
    planner_mod.PER_CLAIM_SEARCH: tools.per_claim_search,
    planner_mod.RE_JUDGE: tools.re_judge_claims,
    planner_mod.TIMELINE: tools.build_timeline,
    planner_mod.FINALIZE: tools.finalize_report,
}

# Hard ceiling on loop iterations; the real stop condition is planner -> DONE.
_MAX_STEPS = 32

# Actions that are critical enough that failure should stop the run (no retry).
# All others degrade gracefully: the planner sees the failure and can skip/re-plan.
_CRITICAL_ACTIONS = frozenset({planner_mod.NORMALIZE, planner_mod.SEARCH, planner_mod.FINALIZE})


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
        self._state: Optional[AgentState] = None

    def cancel(self) -> None:
        """Set the cooperative cancellation flag. The loop checks it before each step."""
        if self._state is not None:
            self._state.cancelled = True

    def run(self, request: AnalyzeRequest) -> Report:
        state = AgentState(request=request)
        state.max_url_fetches = int(getattr(self.ctx.settings, "agent_max_url_fetches", 0) or 0)
        self._state = state

        # Wire token usage tracking: the agent reasoner's streaming layer reports
        # usage per call; we accumulate it into state for trace/cost visibility.
        reasoner = self.ctx.agent_reasoner
        if hasattr(reasoner, "_on_token_usage"):
            reasoner._on_token_usage = lambda p, c, t: state.token_usage.add(prompt=p, completion=c, total=t)

        for _ in range(_MAX_STEPS):
            if state.cancelled:
                emit_log(
                    stage_key="agent_runner",
                    level="warning",
                    title="分析已取消",
                    summary="收到取消信号，提前终止 agent loop。",
                    details=[f"done_actions={','.join(state.done_actions)}"],
                )
                break

            action = self.planner.next_action(state)
            if action == planner_mod.DONE:
                break

            outcome = self._safe_dispatch(action, state)
            state.last_step_outcome = outcome

            if outcome.success:
                state.done_actions.append(action)
                if action == planner_mod.PER_CLAIM_SEARCH:
                    state.per_claim_searches += 1
                elif action == planner_mod.RE_JUDGE:
                    state.per_claim_iterations += 1
            else:
                # Critical actions crash the run (normalize/search/finalize are
                # prerequisites with no meaningful fallback). Non-critical actions
                # log the failure and mark as done so the planner moves past them.
                if action in _CRITICAL_ACTIONS:
                    raise RuntimeError(
                        f"critical_action_failed:{action} error={outcome.error_type}: {outcome.error_message}"
                    )
                state.done_actions.append(action)

        if state.report is None:
            raise RuntimeError("agent_runner_finished_without_report")
        return state.report

    def _safe_dispatch(self, action: str, state: AgentState) -> StepOutcome:
        """Dispatch with try/except — non-critical failures become StepOutcome.success=False."""
        try:
            self._dispatch(action, state)
            return StepOutcome(action=action, success=True, summary=f"{action} completed")
        except Exception as exc:
            logger.warning(
                "agent_step_failed action=%s error_type=%s error=%s",
                action, exc.__class__.__name__, str(exc)[:200],
            )
            emit_log(
                stage_key="agent_runner",
                level="warning",
                title=f"步骤 {action} 失败",
                summary=f"{action} 抛出异常，{('终止运行' if action in _CRITICAL_ACTIONS else '跳过继续')}。",
                details=[
                    f"error_type={exc.__class__.__name__}",
                    f"error={str(exc)[:200]}",
                ],
            )
            return StepOutcome(
                action=action,
                success=False,
                summary=f"{action} failed: {exc.__class__.__name__}",
                error_type=exc.__class__.__name__,
                error_message=str(exc)[:200],
            )

    def _dispatch(self, action: str, state: AgentState) -> None:
        if action == planner_mod.SYNTHESIZE:
            tools.synthesize(self.ctx, state)
            return
        tool = _SIMPLE_TOOLS.get(action)
        if tool is None:
            raise RuntimeError(f"unknown_agent_action:{action}")
        tool(self.ctx, state)
