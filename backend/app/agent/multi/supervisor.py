"""Supervisor: multi-agent orchestrator for the fact-checking pipeline.

The Supervisor owns the execution lifecycle of all sub-agents. It:
1. Resolves the dependency graph to determine execution order
2. Runs independent agents in parallel (via ThreadPoolExecutor)
3. Manages shared state access (agents mutate disjoint slices)
4. Handles failures with graceful degradation
5. Enforces wall-clock and token budgets across all agents
6. Emits progress events for the streaming frontend

Execution model:
  RetrievalAgent (no deps)
       |
  AnalysisAgent (depends on Retrieval)
       |
  CriticAgent (depends on Analysis)
       |
  ReportAgent (depends on Critic)

Future: when agents have non-overlapping deps, they can run in parallel.
The supervisor already supports this — it fans out all agents whose deps
are satisfied at each tick.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout, wait
from contextvars import copy_context
from typing import Dict, List, Optional

from backend.app.agent.multi import AgentRole, AgentStatus, SubAgent, SubAgentResult
from backend.app.agent.checkpoint import (
    Checkpoint,
    DiskCheckpointStore,
    MemoryCheckpointStore,
    restore_state,
    snapshot_state,
)
from backend.app.agent.multi.analysis_agent import AnalysisAgent
from backend.app.agent.multi.critic_agent import CriticAgent
from backend.app.agent.multi.merge_agent import MergeAgent
from backend.app.agent.multi.normalize_agent import NormalizeAgent
from backend.app.agent.multi.report_agent import ReportAgent
from backend.app.agent.multi.retrieval_agent import RetrievalAgent
from backend.app.agent.multi.source_agents import SOURCE_ROLES, build_source_agents
from backend.app.agent.state import AgentState
from backend.app.agent_tools.base import ToolContext
from backend.app.agent_tools import tools as _tools  # noqa: F401 — triggers @tool registration
from backend.app.models.schemas import AnalyzeRequest, Report
from backend.app.services.progress import (
    emit_log,
    emit_progress,
    get_progress_callback,
    reset_progress_callback,
    set_progress_callback,
)

logger = logging.getLogger(__name__)

_STAGE_KEY = "supervisor"


class Supervisor:
    """Multi-agent orchestrator.

    Manages a set of sub-agents, resolves their dependency graph, and executes
    them in topological order with parallel fan-out where possible.

    Each agent can run with a different LLM model. The supervisor saves/restores
    the reasoner's model_override before and after each agent runs to prevent
    bleed-through.
    """

    def __init__(
        self,
        ctx: ToolContext,
        agents: Optional[List[SubAgent]] = None,
        agent_configs: Optional[Dict[AgentRole, "AgentConfig"]] = None,
        max_parallel: int = 2,
        retrieval_mode: Optional[str] = None,
    ) -> None:
        self.ctx = ctx
        self.max_parallel = max_parallel
        self._results: Dict[AgentRole, SubAgentResult] = {}
        self.retrieval_mode = (
            retrieval_mode
            or getattr(ctx, "settings", None)
            and getattr(ctx.settings, "multi_agent_retrieval_mode", "parallel")
            or "parallel"
        )

        if agents:
            self.agents: List[SubAgent] = agents
        else:
            from backend.app.agent.multi import AgentConfig
            configs = agent_configs or self._load_configs_from_settings()
            self.agents = self._default_agents(configs, mode=self.retrieval_mode)

        # Retrieval-segment roles present in the active DAG — used by loop-back to
        # reset the right agents regardless of which topology is running.
        self._retrieval_roles = [
            a.role
            for a in self.agents
            if a.role in {AgentRole.RETRIEVAL, AgentRole.NORMALIZE, AgentRole.RETRIEVAL_MERGE, *SOURCE_ROLES}
        ]

    def run(self, request: AnalyzeRequest, run_id: Optional[str] = None) -> Report:
        checkpoint_enabled = getattr(self.ctx.settings, "agent_checkpoint_enabled", False)
        checkpoint_store = None
        if checkpoint_enabled:
            checkpoint_dir = getattr(self.ctx.settings, "agent_checkpoint_dir", None)
            if checkpoint_dir:
                checkpoint_store = DiskCheckpointStore(checkpoint_dir)
            else:
                checkpoint_store = MemoryCheckpointStore()

        # Attempt resume from checkpoint
        state = None
        completed: set[AgentRole] = set()
        if run_id and checkpoint_store:
            latest = checkpoint_store.latest(run_id)
            if latest is not None:
                try:
                    state = restore_state(latest)
                    completed = {
                        AgentRole(a) for a in state.done_actions
                        if any(a == role.value for role in AgentRole)
                    }
                    emit_log(
                        stage_key=_STAGE_KEY,
                        title="Supervisor 从检查点恢复",
                        summary=f"恢复到步骤 {latest.step_index}（{latest.action}），跳过已完成 Agent。",
                    )
                except Exception as exc:
                    logger.warning("checkpoint_restore_failed run_id=%s error=%s", run_id, exc)
                    state = None
                    completed = set()

        if state is None:
            state = AgentState(request=request)

        state.max_url_fetches = int(getattr(self.ctx.settings, "agent_max_url_fetches", 0) or 0)
        state.max_token_budget = int(getattr(self.ctx.settings, "agent_max_token_budget", 0) or 0)

        # Per-request agent model overrides from request_context
        self._apply_request_model_overrides(request)

        reasoner = self.ctx.agent_reasoner
        if hasattr(reasoner, "_on_token_usage"):
            reasoner._on_token_usage = lambda p, c, t: state.token_usage.add(prompt=p, completion=c, total=t)

        wall_clock = float(getattr(self.ctx.settings, "agent_wall_clock_seconds", 0.0) or 0.0)
        if wall_clock <= 0:
            wall_clock = 120.0
        run_start = time.monotonic()
        deadline = run_start + wall_clock

        emit_log(
            stage_key=_STAGE_KEY,
            title="Supervisor 启动",
            summary=f"多 Agent 协作模式，共 {len(self.agents)} 个子 Agent。",
            details=[f"agents={','.join(a.role.value for a in self.agents)}"],
        )

        agent_map = {a.role: a for a in self.agents}
        failed: set[AgentRole] = set()
        iteration = 0
        max_iterations = 3
        step_index = 0

        while True:
            iteration += 1
            if iteration > max_iterations * len(self.agents):
                emit_log(
                    stage_key=_STAGE_KEY,
                    level="warning",
                    title="Supervisor 迭代上限",
                    summary=f"已达最大迭代数 {max_iterations}，停止循环。",
                )
                break

            if deadline is not None and time.monotonic() >= deadline:
                state.time_exhausted = True
                emit_log(
                    stage_key=_STAGE_KEY,
                    level="warning",
                    title="Supervisor 超时",
                    summary="已超过整体时限，跳过剩余 Agent 直接出报告。",
                )
                break

            if state.cancelled:
                emit_log(
                    stage_key=_STAGE_KEY,
                    level="warning",
                    title="Supervisor 取消",
                    summary="收到取消信号。",
                )
                break

            ready = self._ready_agents(agent_map, completed, failed)
            if not ready:
                break

            results = self._execute_batch(ready, state, deadline)

            for result in results:
                self._results[result.role] = result
                if result.status == AgentStatus.COMPLETED:
                    completed.add(result.role)
                elif result.status == AgentStatus.SKIPPED:
                    completed.add(result.role)
                else:
                    failed.add(result.role)
                    # The DAG entry point (sequential: RETRIEVAL; parallel:
                    # NORMALIZE) is critical — nothing downstream can run without
                    # it, so abort to the fixed-pipeline fallback. Individual
                    # source agents are NOT critical (they degrade to empty slots).
                    if result.role in (AgentRole.RETRIEVAL, AgentRole.NORMALIZE):
                        raise RuntimeError(
                            f"critical_agent_failed:{result.role.value} error={result.error}"
                        )

            # Checkpoint after each batch
            if checkpoint_store and run_id:
                step_index += 1
                batch_roles = ",".join(r.role.value for r in results)
                try:
                    cp = snapshot_state(state, action=batch_roles, step_index=step_index)
                    checkpoint_store.save(run_id, cp)
                except Exception as exc:
                    logger.warning("checkpoint_save_failed step=%d error=%s", step_index, exc)

            # Conditional routing: after the critic runs, decide whether to loop
            # back to retrieval for another evidence round. An LLM router decides
            # when enabled; otherwise a rule threshold. Either way, loop-back only
            # fires once (guarded by done_actions) so we can't spin forever.
            if AgentRole.CRITIC in completed and self._should_loop_back(state):
                emit_log(
                    stage_key=_STAGE_KEY,
                    title="条件路由: 回到检索",
                    summary="判定证据不足，触发重新检索。",
                )
                # Re-run the whole retrieval segment for the active DAG (sequential:
                # RETRIEVAL; parallel: normalize + sources + merge) plus analysis and
                # critic. Discard only roles that exist so this is DAG-agnostic.
                for role in (*self._retrieval_roles, AgentRole.ANALYSIS, AgentRole.CRITIC):
                    completed.discard(role)
                state.per_claim_iterations = 0
                state.per_claim_searches = 0
                state.done_actions.append("supervisor_loop_back")

            # Debate loop: after critic downgrades claims, re-run Analysis + Critic
            # on just the downgraded claims for up to N rounds. Converges when the
            # critic no longer downgrades anything or the round limit is reached.
            elif AgentRole.CRITIC in completed and self._should_debate(state):
                critic_result = self._results.get(AgentRole.CRITIC)
                downgraded = getattr(critic_result, "downgraded_indices", None) or set()
                debate_round = state.debate_rounds + 1
                emit_log(
                    stage_key=_STAGE_KEY,
                    title=f"辩论轮次 {debate_round}",
                    summary=f"Critic 降级了 {len(downgraded)} 条 claim，触发 Analysis 重判。",
                    details=[f"debate_round={debate_round}", f"downgraded={sorted(downgraded)}"],
                )
                state.debate_rounds = debate_round
                state.debate_focus_indices = downgraded
                # Re-run only Analysis + Critic (no re-retrieval — evidence is kept)
                completed.discard(AgentRole.ANALYSIS)
                completed.discard(AgentRole.CRITIC)
                state.per_claim_iterations = 0
                state.per_claim_searches = 0

        if state.report is None:
            self._force_finalize(state, completed)

        if state.report is None:
            raise RuntimeError("supervisor_finished_without_report")

        self._emit_run_summary(state, completed, failed, run_start)

        return state.report

    def _emit_run_summary(
        self,
        state: AgentState,
        completed: set[AgentRole],
        failed: set[AgentRole],
        run_start: float,
    ) -> None:
        """Emit an end-of-run observability summary: per-agent status/timing,
        token usage, per-source contribution, and the DAG topology used.

        Emitted twice — a human-readable `log` event for the trace panel and a
        machine-readable `metrics` event for programmatic consumers. Best-effort:
        any failure here must never break a run that already produced a report."""
        try:
            total_ms = int((time.monotonic() - run_start) * 1000)
            agents_detail = []
            for role in (a.role for a in self.agents):
                res = self._results.get(role)
                if res is None:
                    continue
                agents_detail.append({
                    "role": role.value,
                    "status": res.status.value,
                    "elapsed_ms": res.elapsed_ms,
                    "actions": list(res.actions_taken),
                    "model": res.model_used,
                    "error": res.error,
                })

            source_hits = {
                key: len(bundle.canonical_results)
                for key, bundle in sorted(state.source_bundles.items())
                if bundle is not None
            }

            usage = state.token_usage
            metrics = {
                "mode": self.retrieval_mode,
                "total_ms": total_ms,
                "time_exhausted": state.time_exhausted,
                "looped_back": "supervisor_loop_back" in state.done_actions,
                "completed": sorted(r.value for r in completed),
                "failed": sorted(r.value for r in failed),
                "agents": agents_detail,
                "source_hits": source_hits,
                "tokens": {
                    "prompt": usage.prompt_tokens,
                    "completion": usage.completion_tokens,
                    "total": usage.total_tokens,
                    "llm_calls": usage.call_count,
                },
            }
            emit_progress("metrics", stage_key=_STAGE_KEY, metrics=metrics)

            slowest = sorted(agents_detail, key=lambda a: a["elapsed_ms"], reverse=True)[:3]
            details = [
                f"mode={self.retrieval_mode} total={total_ms}ms",
                f"tokens={usage.total_tokens}(calls={usage.call_count})",
            ]
            if source_hits:
                details.append("source_hits=" + ", ".join(f"{k}:{v}" for k, v in source_hits.items()))
            if slowest:
                details.append("slowest=" + ", ".join(f"{a['role']}:{a['elapsed_ms']}ms" for a in slowest))
            if failed:
                details.append("failed=" + ",".join(sorted(r.value for r in failed)))
            emit_log(
                stage_key=_STAGE_KEY,
                title="Supervisor 完成",
                summary=f"已完成 {len(completed)} 个 Agent，失败 {len(failed)} 个，总耗时 {total_ms}ms。",
                details=details,
            )
        except Exception as exc:  # observability must never break a successful run
            logger.warning("supervisor_run_summary_failed error=%s", exc)

    def _should_loop_back(self, state: AgentState) -> bool:
        """Conditional edge: should we loop back to retrieval for another round?

        Loop-back fires at most once (guarded by the `supervisor_loop_back` marker
        the caller appends). When LLM routing is enabled and available, the model
        decides from an evidence snapshot; otherwise a rule threshold (>70% of fact
        claims insufficient) decides. The LLM path degrades to the rule path on any
        failure, so routing never stalls the run."""
        if state.verdict is None:
            return False
        if "supervisor_loop_back" in state.done_actions:
            return False
        fact_claims = [cr for cr in state.verdict.claim_results if cr.claim_type == "fact"]
        if not fact_claims:
            return False

        llm_choice = self._llm_route_loop_back(state, fact_claims)
        if llm_choice is not None:
            return llm_choice

        insufficient_ratio = sum(1 for cr in fact_claims if cr.verdict == "insufficient") / len(fact_claims)
        return insufficient_ratio > 0.7

    def _should_debate(self, state: AgentState) -> bool:
        """Should we enter (or continue) a debate round between Analysis and Critic?

        A debate round fires when:
        1. The critic actually downgraded at least one claim (not just skipped)
        2. We haven't exceeded the max debate rounds (default 2)
        3. The loop-back didn't already fire (debate is a lighter mechanism)
        """
        max_debate_rounds = max(int(getattr(self.ctx.settings, "multi_agent_debate_rounds", 2) or 2), 0)
        if state.debate_rounds >= max_debate_rounds:
            return False
        if "supervisor_loop_back" in state.done_actions:
            return False
        critic_result = self._results.get(AgentRole.CRITIC)
        if critic_result is None:
            return False
        downgraded = getattr(critic_result, "downgraded_indices", None)
        return bool(downgraded)

    def _llm_route_loop_back(self, state: AgentState, fact_claims: list) -> Optional[bool]:
        """LLM router: choose 'loop_back' vs 'finalize' from an evidence snapshot.

        Returns None (→ rule fallback) when routing is disabled, the reasoner is
        unavailable, or the call fails / returns an illegal action. Reuses the
        reasoner's plan_next_action, which is contractually guaranteed to return an
        action from allowed_actions or None."""
        if not getattr(self.ctx.settings, "multi_agent_llm_routing_enabled", False):
            return None
        reasoner = getattr(self.ctx, "agent_reasoner", None)
        if reasoner is None or not getattr(reasoner, "enabled", False):
            return None
        if not hasattr(reasoner, "plan_next_action"):
            return None

        insufficient = sum(1 for cr in fact_claims if cr.verdict == "insufficient")
        bundle = state.retrieval_bundle
        snapshot = {
            "fact_claims": len(fact_claims),
            "insufficient_claims": insufficient,
            "evidence_grade": getattr(bundle, "evidence_grade", None) if bundle else None,
            "total_results": len(getattr(bundle, "canonical_results", []) or []) if bundle else 0,
            "already_investigated": "investigate" in state.done_actions,
        }
        try:
            plan = reasoner.plan_next_action(
                evidence_snapshot=snapshot,
                allowed_actions=["loop_back", "finalize"],
            )
        except Exception as exc:
            logger.warning("supervisor_llm_route_failed error=%s", exc)
            return None
        if plan is None:
            return None
        decision = plan.next_action == "loop_back"
        emit_log(
            stage_key=_STAGE_KEY,
            title="LLM 路由决策",
            summary=f"路由器选择: {plan.next_action}。{plan.reason}",
        )
        return decision

    def _apply_request_model_overrides(self, request: AnalyzeRequest) -> None:
        """Apply per-request agent model overrides from request_context.

        Frontend can pass:
          request_context: {
            "agent_models": {
              "retrieval": "GLM-4-Flash",
              "analysis": "DeepSeek-R1",
              "critic": "GLM-5.2"
            }
          }
        """
        agent_models = request.request_context.get("agent_models")
        if not isinstance(agent_models, dict):
            return

        role_map = {a.role.value: a for a in self.agents}
        for role_str, model in agent_models.items():
            if not isinstance(model, str) or not model.strip():
                continue
            agent = role_map.get(role_str)
            if agent and hasattr(agent, "config"):
                agent.config.model = model.strip()

    def _ready_agents(
        self,
        agent_map: Dict[AgentRole, SubAgent],
        completed: set[AgentRole],
        failed: set[AgentRole],
    ) -> List[SubAgent]:
        """Find agents whose dependencies are all satisfied and haven't run yet."""
        done = completed | failed
        ready = []
        for agent in self.agents:
            if agent.role in done:
                continue
            deps_met = all(d in completed for d in agent.dependencies)
            deps_failed = any(d in failed for d in agent.dependencies)
            if deps_failed:
                self._results[agent.role] = SubAgentResult(
                    role=agent.role,
                    status=AgentStatus.SKIPPED,
                    error="dependency_failed",
                )
                done.add(agent.role)
                continue
            if deps_met:
                ready.append(agent)
        return ready

    def _execute_batch(
        self,
        agents: List[SubAgent],
        state: AgentState,
        deadline: Optional[float],
    ) -> List[SubAgentResult]:
        """Execute a batch of ready agents. Parallel if >1 and max_parallel allows."""
        if len(agents) == 1 or self.max_parallel <= 1:
            results = []
            for agent in agents:
                result = self._run_agent(agent, state, deadline)
                results.append(result)
            return results

        # Parallel fan-out. Agents on parallel threads must NOT mutate the shared
        # reasoner's model_override (its save/restore in _run_agent is not thread
        # safe), so batched agents are required to declare no model override. The
        # source agents satisfy this by construction; assert to catch regressions.
        offenders = [a.role.value for a in agents if getattr(getattr(a, "config", None), "model", None)]
        if offenders:
            raise RuntimeError(f"parallel_batch_declares_model_override:{','.join(offenders)}")

        results: List[SubAgentResult] = []
        with ThreadPoolExecutor(max_workers=min(len(agents), self.max_parallel)) as pool:
            # ContextVars (progress callback, retrieval stage key) do NOT cross into
            # pool threads — on 3.12 submit() runs the callable with a fresh empty
            # context, so a naive submit makes every source-agent emit_log/emit_api_call
            # silently no-op and the whole parallel retrieval phase vanishes from the
            # trace UI. Snapshot the parent context and run each worker inside a copy,
            # mirroring the rebinding retrieval_service._run_fetch already does.
            futures = {
                pool.submit(copy_context().run, self._run_agent, agent, state, deadline): agent
                for agent in agents
            }
            # Bound the wait by the supervisor deadline so one hung agent can't
            # block the whole batch past the wall-clock budget. Providers already
            # have their own IO timeouts; this is the supervisor-level backstop.
            timeout = max(deadline - time.monotonic(), 0.0) if deadline is not None else None
            done, not_done = wait(futures, timeout=timeout)
            for future in done:
                results.append(future.result())
            for future in not_done:
                agent = futures[future]
                future.cancel()
                logger.warning("supervisor_agent_timed_out role=%s", agent.role.value)
                results.append(
                    SubAgentResult(
                        role=agent.role,
                        status=AgentStatus.FAILED,
                        error="batch_deadline_exceeded",
                    )
                )
        return results

    def _run_agent(
        self,
        agent: SubAgent,
        state: AgentState,
        deadline: Optional[float],
    ) -> SubAgentResult:
        """Run a single sub-agent with error containment, model isolation, and retry."""
        config = agent.config if hasattr(agent, "config") else None
        model_name = getattr(config, "model", None)

        # Conditional routing: skip this agent if its skip_when condition is met
        skip_fn = getattr(config, "skip_when", None) if config else None
        if skip_fn is not None:
            try:
                if skip_fn(state):
                    emit_log(
                        stage_key=_STAGE_KEY,
                        title=f"跳过 {agent.role.value} Agent",
                        summary="条件路由判定该 Agent 无需执行。",
                    )
                    return SubAgentResult(
                        role=agent.role,
                        status=AgentStatus.SKIPPED,
                    )
            except Exception:
                pass

        emit_log(
            stage_key=_STAGE_KEY,
            title=f"调度 {agent.role.value} Agent",
            summary=f"{agent.description} [model={model_name or 'default'}]",
        )
        t0 = time.monotonic()

        max_retries = getattr(config, "max_retries", 1) if config else 1
        timeout_seconds = getattr(config, "timeout_seconds", None) if config else None
        result: Optional[SubAgentResult] = None

        for attempt in range(max_retries + 1):
            if attempt > 0:
                backoff = 0.5 * (2 ** (attempt - 1))
                time.sleep(backoff)
                emit_log(
                    stage_key=_STAGE_KEY,
                    level="info",
                    title=f"重试 {agent.role.value} Agent",
                    summary=f"第 {attempt} 次重试，退避 {backoff:.1f}s。",
                )

            # Save and restore the reasoner's model_override to isolate per-agent model choice
            reasoner = self.ctx.agent_reasoner
            prev_model = getattr(reasoner, "model_override", None) if reasoner else None
            try:
                result = self._invoke_agent(agent, state, timeout_seconds)
            except TimeoutError:
                logger.warning("supervisor_agent_timeout role=%s attempt=%d limit=%ss", agent.role.value, attempt, timeout_seconds)
                result = SubAgentResult(
                    role=agent.role,
                    status=AgentStatus.FAILED,
                    error=f"agent_timeout:{timeout_seconds}s",
                )
            except Exception as exc:
                logger.error("supervisor_agent_crashed role=%s attempt=%d error=%s", agent.role.value, attempt, exc)
                result = SubAgentResult(
                    role=agent.role,
                    status=AgentStatus.FAILED,
                    error=str(exc)[:200],
                )
            finally:
                if reasoner and hasattr(reasoner, "model_override"):
                    reasoner.model_override = prev_model

            if result and result.status in (AgentStatus.COMPLETED, AgentStatus.SKIPPED):
                break

        elapsed = time.monotonic() - t0
        result.elapsed_ms = int(elapsed * 1000)
        emit_log(
            stage_key=_STAGE_KEY,
            title=f"{agent.role.value} Agent 返回",
            summary=f"状态={result.status.value}，耗时={elapsed:.1f}s，model={result.model_used or 'default'}",
            details=[
                f"actions={','.join(result.actions_taken)}",
                f"error={result.error}" if result.error else "",
            ],
        )
        return result

    def _invoke_agent(
        self,
        agent: SubAgent,
        state: AgentState,
        timeout_seconds: Optional[float],
    ) -> SubAgentResult:
        """Run agent.run, optionally bounded by a per-agent timeout.

        With no timeout, runs inline. With a timeout, runs on a worker thread and
        raises TimeoutError if it overruns; the progress ContextVar is rebound in
        the worker since ContextVars don't cross threads. An overrun leaves the
        worker orphaned, but every provider has its own IO timeout so it cannot
        run unbounded — this is a supervisor-level backstop, not the only guard."""
        if not timeout_seconds or timeout_seconds <= 0:
            return agent.run(state, self.ctx)

        parent_callback = get_progress_callback()

        def _worker() -> SubAgentResult:
            token = set_progress_callback(parent_callback) if parent_callback is not None else None
            try:
                return agent.run(state, self.ctx)
            finally:
                if token is not None:
                    reset_progress_callback(token)

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_worker)
            try:
                return future.result(timeout=timeout_seconds)
            except FuturesTimeout as exc:
                future.cancel()
                raise TimeoutError(str(timeout_seconds)) from exc

    def _force_finalize(self, state: AgentState, completed: set[AgentRole]) -> None:
        """Last-resort: force report generation with whatever state we have."""
        emit_log(
            stage_key=_STAGE_KEY,
            level="warning",
            title="强制生成报告",
            summary="部分 Agent 未完成，用现有状态强制出报告。",
        )
        try:
            from backend.app.agent_tools.base import get_tool_fn

            if "build_timeline" not in state.done_actions and not state.agent_synthesized:
                timeline_fn = get_tool_fn("build_timeline")
                if timeline_fn:
                    try:
                        timeline_fn(self.ctx, state)
                        state.done_actions.append("build_timeline")
                    except Exception:
                        pass

            finalize_fn = get_tool_fn("finalize_report")
            if finalize_fn:
                finalize_fn(self.ctx, state)
                state.done_actions.append("finalize_report")
        except Exception as exc:
            logger.error("supervisor_force_finalize_failed error=%s", exc)

    @staticmethod
    def _default_agents(
        configs: Optional[Dict[AgentRole, "AgentConfig"]] = None,
        *,
        mode: str = "parallel",
    ) -> List[SubAgent]:
        from backend.app.agent.multi import AgentConfig
        configs = configs or {}

        default_configs = {
            AgentRole.RETRIEVAL: AgentConfig(
                goal="标准化输入并从多源收集高质量证据。",
                tools=["normalize", "search_news", "resolve_question", "follow_up_retrieval", "investigate", "fetch_url"],
                max_retries=2,
            ),
            AgentRole.NORMALIZE: AgentConfig(
                goal="标准化输入并预计算共享检索 query。",
                tools=["normalize"],
                max_retries=2,
            ),
            AgentRole.RETRIEVAL_MERGE: AgentConfig(
                goal="合并多源检索结果并执行检索精炼。",
                tools=["resolve_question", "follow_up_retrieval", "investigate", "fetch_url"],
                max_retries=1,
            ),
            AgentRole.ANALYSIS: AgentConfig(
                goal="基于证据对每条事实声明做出准确的真假判定。",
                tools=["synthesize", "enrich", "extract_claims", "judge_claims", "per_claim_search", "re_judge_claims"],
                max_retries=1,
            ),
            AgentRole.CRITIC: AgentConfig(
                goal="对抗性审视判定结论：如果证据不够强，降级到 insufficient。",
                tools=[],
                max_retries=0,
                skip_when=lambda state: state.verdict is None and not state.agent_synthesized,
            ),
            AgentRole.REPORT: AgentConfig(
                goal="组装时间线和最终验证报告。",
                tools=["build_timeline", "finalize_report"],
                max_retries=2,
            ),
        }

        def cfg(role: AgentRole) -> AgentConfig:
            """Merge an optional per-role override over that role's default."""
            base = default_configs.get(role, AgentConfig())
            override = configs.get(role)
            if override is None:
                return base
            return AgentConfig(
                model=override.model or base.model,
                max_retries=override.max_retries,
                timeout_seconds=override.timeout_seconds or base.timeout_seconds,
                goal=override.goal or base.goal,
                tools=override.tools or base.tools,
                skip_when=override.skip_when or base.skip_when,
            )

        analysis_upstream = AgentRole.RETRIEVAL if mode == "sequential" else AgentRole.RETRIEVAL_MERGE
        analysis_chain: List[SubAgent] = [
            AnalysisAgent(config=cfg(AgentRole.ANALYSIS), depends_on=[analysis_upstream]),
            CriticAgent(config=cfg(AgentRole.CRITIC)),
            ReportAgent(config=cfg(AgentRole.REPORT)),
        ]

        if mode == "sequential":
            return [RetrievalAgent(config=cfg(AgentRole.RETRIEVAL)), *analysis_chain]

        # parallel: normalize -> {4 source agents in parallel} -> merge -> analysis.
        # Source agents keep model=None by construction (build_source_agents) so the
        # parallel batch never races on reasoner.model_override.
        return [
            NormalizeAgent(config=cfg(AgentRole.NORMALIZE)),
            *build_source_agents(),
            MergeAgent(config=cfg(AgentRole.RETRIEVAL_MERGE)),
            *analysis_chain,
        ]

    def _load_configs_from_settings(self) -> Dict[AgentRole, "AgentConfig"]:
        """Load per-agent model configs from environment/settings.

        Env vars:
          MULTI_AGENT_RETRIEVAL_MODEL=model-name
          MULTI_AGENT_ANALYSIS_MODEL=model-name
          MULTI_AGENT_CRITIC_MODEL=model-name
          MULTI_AGENT_REPORT_MODEL=model-name
        """
        import os
        from backend.app.agent.multi import AgentConfig

        configs: Dict[AgentRole, AgentConfig] = {}
        for role in AgentRole:
            env_key = f"MULTI_AGENT_{role.value.upper()}_MODEL"
            model = os.environ.get(env_key, "").strip()
            if model:
                configs[role] = AgentConfig(model=model)
        return configs
