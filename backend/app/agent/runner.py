from __future__ import annotations

import logging
import time

from backend.app.agent import planner as planner_mod
from backend.app.agent.checkpoint import (
    CheckpointStore,
    restore_state,
    snapshot_state,
)
from backend.app.agent.planner import Planner, RulePlanner
from backend.app.agent.state import AgentState, StepOutcome
from backend.app.agent_tools import tools  # noqa: F401 — import triggers @tool registration
from backend.app.agent_tools.base import (
    HookContext,
    HookRegistry,
    PermissionGate,
    ToolContext,
    get_tool_fn,
    get_tool_spec,
)
from backend.app.models.schemas import AnalyzeRequest, Report
from backend.app.services.progress import emit_log

logger = logging.getLogger(__name__)

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

    def __init__(self, ctx: ToolContext, planner: Planner | None = None, hooks: HookRegistry | None = None, checkpoint_store: CheckpointStore | None = None, permission_gate: PermissionGate | None = None) -> None:
        self.ctx = ctx
        self.planner = planner or RulePlanner()
        self.hooks = hooks or HookRegistry()
        self.checkpoint_store = checkpoint_store
        self.permission_gate = permission_gate or PermissionGate()
        self._state: AgentState | None = None

    def cancel(self) -> None:
        """Set the cooperative cancellation flag. The loop checks it before each step."""
        if self._state is not None:
            self._state.cancelled = True

    def run(self, request: AnalyzeRequest, run_id: str | None = None) -> Report:
        state = AgentState(request=request)
        state.max_url_fetches = int(getattr(self.ctx.settings, "agent_max_url_fetches", 0) or 0)
        state.max_token_budget = int(getattr(self.ctx.settings, "agent_max_token_budget", 0) or 0)
        self._state = state

        # Wire token usage tracking: the agent reasoner's streaming layer reports
        # usage per call; we accumulate it into state for trace/cost visibility.
        reasoner = self.ctx.agent_reasoner
        if hasattr(reasoner, "_on_token_usage"):
            reasoner._on_token_usage = lambda p, c, t: state.token_usage.add(prompt=p, completion=c, total=t)

        return self._run_loop(state, run_id=run_id, step_offset=0)

    def resume(self, run_id: str) -> Report:
        """Resume a previously checkpointed run from its last successful step.

        Raises RuntimeError if no checkpoint exists for the given run_id.
        """
        if self.checkpoint_store is None:
            raise RuntimeError("cannot resume without a checkpoint store")
        checkpoint = self.checkpoint_store.latest(run_id)
        if checkpoint is None:
            raise RuntimeError(f"no checkpoint found for run_id={run_id}")

        state = restore_state(checkpoint)
        state.cancelled = False
        self._state = state

        reasoner = self.ctx.agent_reasoner
        if hasattr(reasoner, "_on_token_usage"):
            reasoner._on_token_usage = lambda p, c, t: state.token_usage.add(prompt=p, completion=c, total=t)

        emit_log(
            stage_key="agent_runner",
            level="info",
            title="从检查点恢复",
            summary=f"恢复自步骤 {checkpoint.step_index}（{checkpoint.action}），继续后续分析。",
            details=[f"run_id={run_id}", f"done_actions={','.join(state.done_actions)}"],
        )
        return self._run_loop(state, run_id=run_id, step_offset=checkpoint.step_index + 1)

    def _run_loop(self, state: AgentState, run_id: str | None, step_offset: int) -> Report:
        # Overall wall-clock budget across the whole loop. Per-call timeouts only
        # bound one step; without this, 32 slow steps accumulate into the chronic
        # deep-path timeout. When it passes we don't abort — we set time_exhausted
        # so the planner forces the shortest path to a report (soft landing).
        wall_clock = float(getattr(self.ctx.settings, "agent_wall_clock_seconds", 0.0) or 0.0)
        deadline = time.monotonic() + wall_clock if wall_clock > 0 else None
        for step_idx in range(step_offset, step_offset + _MAX_STEPS):
            if state.cancelled:
                emit_log(
                    stage_key="agent_runner",
                    level="warning",
                    title="分析已取消",
                    summary="收到取消信号，提前终止 agent loop。",
                    details=[f"done_actions={','.join(state.done_actions)}"],
                )
                break

            if deadline is not None and not state.time_exhausted and time.monotonic() >= deadline:
                state.time_exhausted = True
                emit_log(
                    stage_key="agent_runner",
                    level="warning",
                    title="分析超时软着陆",
                    summary=f"已超过整体时限 {wall_clock:.0f}s，跳过剩余取证，直接用现有证据出结论。",
                    details=[f"done_actions={','.join(state.done_actions)}"],
                )

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
                # Checkpoint after each successful step
                if self.checkpoint_store is not None and run_id is not None:
                    try:
                        cp = snapshot_state(state, action, step_idx)
                        self.checkpoint_store.save(run_id, cp)
                    except Exception as exc:
                        logger.warning("checkpoint_save_failed step=%s error=%s", action, str(exc)[:100])
            else:
                if action in _CRITICAL_ACTIONS:
                    raise RuntimeError(
                        f"critical_action_failed:{action} error={outcome.error_type}: {outcome.error_message}"
                    )
                state.done_actions.append(action)

        if state.report is None:
            raise RuntimeError("agent_runner_finished_without_report")
        return state.report

    def _dispatch_with_retry(self, action: str, state: AgentState, max_retries: int | None = None) -> StepOutcome:
        """Dispatch with configurable retry and exponential backoff.

        Retry count resolution:
        - Explicit max_retries argument wins when provided by the caller.
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
        # Permission check: if the tool requires permission and is denied, skip it.
        spec = get_tool_spec(action)
        if spec and not self.permission_gate.check(spec):
            emit_log(
                stage_key="agent_runner",
                level="warning",
                title=f"步骤 {action} 被拒绝",
                summary=f"{action} 需要授权但被拒绝，跳过。",
                details=[],
            )
            return StepOutcome(
                action=action, success=False,
                summary=f"{action} denied by permission gate",
                error_type="PermissionDenied",
                error_message="Tool requires permission but was denied",
            )

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
        tool_fn = get_tool_fn(action)
        if tool_fn is None:
            raise RuntimeError(f"unknown_agent_action:{action}")
        tool_fn(self.ctx, state)
