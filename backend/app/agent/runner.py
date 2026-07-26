from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from backend.app.agent import planner as planner_mod
from backend.app.agent.planner import Planner, RulePlanner
from backend.app.agent.state import AgentState, StepOutcome
from backend.app.agent_tools import tools
from backend.app.agent_tools.base import HookContext, HookRegistry, ToolContext, get_tool_spec
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

# Per-tool retry policy: how many times to retry a failed tool before giving up.
# Critical actions get more attempts since their failure is terminal.
_RETRY_POLICY: dict[str, int] = {
    planner_mod.NORMALIZE: 2,
    planner_mod.SEARCH: 2,
    planner_mod.FINALIZE: 2,
    planner_mod.JUDGE: 1,
    planner_mod.RE_JUDGE: 1,
    planner_mod.INVESTIGATE: 1,
    planner_mod.FETCH_URL: 1,
}
_DEFAULT_RETRIES = 0

# Backoff base delay (seconds) between retries. Actual delay = base * 2^attempt.
_RETRY_BACKOFF_BASE = 0.5


class AgentRunner:
    """Agent loop that orchestrates the rumor-check tools.

    The planner decides the next action from current state; the runner dispatches
    it to the matching tool, which reads/writes the shared AgentState. This is the
    same set of operations the legacy pipeline ran, but sequencing is now a
    first-class, pluggable decision rather than hard-coded control flow.
    """

    def __init__(self, ctx: ToolContext, planner: Planner | None = None, hooks: HookRegistry | None = None) -> None:
        self.ctx = ctx
        self.planner = planner or RulePlanner()
        self.hooks = hooks or HookRegistry()
        self._state: Optional[AgentState] = None

    def cancel(self) -> None:
        """Set the cooperative cancellation flag. The loop checks it before each step."""
        if self._state is not None:
            self._state.cancelled = True

    def run(self, request: AnalyzeRequest) -> Report:
        state = AgentState(request=request)
        state.max_url_fetches = int(getattr(self.ctx.settings, "agent_max_url_fetches", 0) or 0)
        state.max_token_budget = int(getattr(self.ctx.settings, "agent_max_token_budget", 0) or 0)
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

            outcome = self._dispatch_with_retry(action, state)
            state.last_step_outcome = outcome

            if outcome.success:
                state.done_actions.append(action)
                if action == planner_mod.PER_CLAIM_SEARCH:
                    state.per_claim_searches += 1
                elif action == planner_mod.RE_JUDGE:
                    state.per_claim_iterations += 1
            else:
                if action in _CRITICAL_ACTIONS:
                    raise RuntimeError(
                        f"critical_action_failed:{action} error={outcome.error_type}: {outcome.error_message}"
                    )
                state.done_actions.append(action)

        if state.report is None:
            raise RuntimeError("agent_runner_finished_without_report")
        return state.report

    def run_parallel(self, actions: list[str], state: AgentState) -> list[StepOutcome]:
        """Execute multiple independent actions in parallel.

        Used for fan-out patterns (e.g. per-claim search). Each action runs in its
        own thread against the shared state. Returns outcomes in input order.
        Non-critical failures do not crash the run.

        IMPORTANT: callers must ensure the actions are truly independent — they
        must not read/write the same state fields. Use this only for parallelizable
        operations (e.g. multiple HTTP fetches writing to disjoint dict keys).
        """
        max_retries = int(getattr(self.ctx.settings, "agent_tool_max_retries", 0) or 0)
        state_lock = threading.Lock()

        def _run_one(action: str) -> tuple[str, StepOutcome]:
            retries = min(_RETRY_POLICY.get(action, _DEFAULT_RETRIES), max_retries) if max_retries > 0 else _RETRY_POLICY.get(action, _DEFAULT_RETRIES)
            outcome = self._dispatch_with_retry(action, state, max_retries=retries)
            return action, outcome

        outcomes: list[StepOutcome] = [StepOutcome(action=a, success=False, summary="not_started") for a in actions]
        with ThreadPoolExecutor(max_workers=min(len(actions), 4)) as pool:
            futures = {pool.submit(_run_one, a): i for i, a in enumerate(actions)}
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    _, outcome = future.result()
                except Exception as exc:
                    outcome = StepOutcome(
                        action=actions[idx], success=False,
                        summary=f"parallel dispatch error: {exc.__class__.__name__}",
                        error_type=exc.__class__.__name__,
                        error_message=str(exc)[:200],
                    )
                outcomes[idx] = outcome
        return outcomes

    def _dispatch_with_retry(self, action: str, state: AgentState, max_retries: int | None = None) -> StepOutcome:
        """Dispatch with configurable retry and exponential backoff.

        Retry count resolution:
        - Explicit max_retries argument wins (used by run_parallel).
        - Otherwise: if AGENT_TOOL_MAX_RETRIES > 0, use min(declared, settings_max).
        - If AGENT_TOOL_MAX_RETRIES == 0 (default), no retries — matches original behavior.
        """
        settings_max = int(getattr(self.ctx.settings, "agent_tool_max_retries", 0) or 0)
        if max_retries is None:
            if settings_max <= 0:
                max_retries = 0
            else:
                spec = get_tool_spec(action)
                declared = spec.retries if spec else _RETRY_POLICY.get(action, _DEFAULT_RETRIES)
                max_retries = min(declared, settings_max)

        last_outcome: StepOutcome | None = None
        for attempt in range(max_retries + 1):
            if attempt > 0:
                delay = _RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                time.sleep(delay)
                emit_log(
                    stage_key="agent_runner",
                    level="info",
                    title=f"重试 {action}",
                    summary=f"第 {attempt} 次重试（共 {max_retries} 次可用），退避 {delay:.1f}s。",
                    details=[f"prev_error={last_outcome.error_type if last_outcome else 'unknown'}"],
                )
            outcome = self._safe_dispatch(action, state)
            if outcome.success:
                return outcome
            last_outcome = outcome

        return last_outcome or StepOutcome(action=action, success=False, summary="retry exhausted")

    def _safe_dispatch(self, action: str, state: AgentState) -> StepOutcome:
        """Dispatch with try/except — non-critical failures become StepOutcome.success=False."""
        hook_ctx = HookContext(action=action, state=state, ctx=self.ctx)
        self.hooks.fire_pre(hook_ctx)
        try:
            self._dispatch(action, state)
            outcome = StepOutcome(action=action, success=True, summary=f"{action} completed")
            hook_ctx.outcome = outcome
            self.hooks.fire_post(hook_ctx)
            return outcome
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
            outcome = StepOutcome(
                action=action,
                success=False,
                summary=f"{action} failed: {exc.__class__.__name__}",
                error_type=exc.__class__.__name__,
                error_message=str(exc)[:200],
            )
            hook_ctx.outcome = outcome
            hook_ctx.error = exc
            self.hooks.fire_post(hook_ctx)
            return outcome

    def _dispatch(self, action: str, state: AgentState) -> None:
        if action == planner_mod.SYNTHESIZE:
            tools.synthesize(self.ctx, state)
            return
        tool = _SIMPLE_TOOLS.get(action)
        if tool is None:
            raise RuntimeError(f"unknown_agent_action:{action}")
        tool(self.ctx, state)
