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
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

from backend.app.agent.multi import AgentRole, AgentStatus, SubAgent, SubAgentResult
from backend.app.agent.multi.analysis_agent import AnalysisAgent
from backend.app.agent.multi.critic_agent import CriticAgent
from backend.app.agent.multi.report_agent import ReportAgent
from backend.app.agent.multi.retrieval_agent import RetrievalAgent
from backend.app.agent.state import AgentState
from backend.app.agent_tools.base import ToolContext
from backend.app.agent_tools import tools as _tools  # noqa: F401 — triggers @tool registration
from backend.app.models.schemas import AnalyzeRequest, Report
from backend.app.services.progress import emit_log

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
    ) -> None:
        self.ctx = ctx
        self.max_parallel = max_parallel
        self._results: Dict[AgentRole, SubAgentResult] = {}

        if agents:
            self.agents: List[SubAgent] = agents
        else:
            from backend.app.agent.multi import AgentConfig
            configs = agent_configs or self._load_configs_from_settings()
            self.agents = self._default_agents(configs)

    def run(self, request: AnalyzeRequest) -> Report:
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
        deadline = time.monotonic() + wall_clock

        emit_log(
            stage_key=_STAGE_KEY,
            title="Supervisor 启动",
            summary=f"多 Agent 协作模式，共 {len(self.agents)} 个子 Agent。",
            details=[f"agents={','.join(a.role.value for a in self.agents)}"],
        )

        agent_map = {a.role: a for a in self.agents}
        completed: set[AgentRole] = set()
        failed: set[AgentRole] = set()
        iteration = 0
        max_iterations = 3

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
                    if result.role == AgentRole.RETRIEVAL:
                        raise RuntimeError(
                            f"critical_agent_failed:{result.role.value} error={result.error}"
                        )

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
                completed.discard(AgentRole.RETRIEVAL)
                completed.discard(AgentRole.ANALYSIS)
                completed.discard(AgentRole.CRITIC)
                state.per_claim_iterations = 0
                state.per_claim_searches = 0
                state.done_actions.append("supervisor_loop_back")

        if state.report is None:
            self._force_finalize(state, completed)

        if state.report is None:
            raise RuntimeError("supervisor_finished_without_report")

        emit_log(
            stage_key=_STAGE_KEY,
            title="Supervisor 完成",
            summary=f"已完成 {len(completed)} 个 Agent，失败 {len(failed)} 个。",
            details=[
                f"completed={','.join(r.value for r in completed)}",
                f"failed={','.join(r.value for r in failed)}",
            ],
        )

        return state.report

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

        results: List[SubAgentResult] = []
        with ThreadPoolExecutor(max_workers=min(len(agents), self.max_parallel)) as pool:
            futures = {
                pool.submit(self._run_agent, agent, state, deadline): agent
                for agent in agents
            }
            for future in as_completed(futures):
                results.append(future.result())
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
                result = agent.run(state, self.ctx)
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
    def _default_agents(configs: Optional[Dict[AgentRole, "AgentConfig"]] = None) -> List[SubAgent]:
        from backend.app.agent.multi import AgentConfig
        configs = configs or {}

        default_configs = {
            AgentRole.RETRIEVAL: AgentConfig(
                goal="标准化输入并从多源收集高质量证据。",
                tools=["normalize", "search_news", "resolve_question", "follow_up_retrieval", "investigate", "fetch_url"],
                max_retries=2,
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

        merged = {role: AgentConfig(
            model=configs.get(role, AgentConfig()).model or default_configs[role].model,
            temperature=configs.get(role, AgentConfig()).temperature or default_configs[role].temperature,
            max_retries=configs.get(role, AgentConfig()).max_retries if configs.get(role) else default_configs[role].max_retries,
            timeout_seconds=configs.get(role, AgentConfig()).timeout_seconds or default_configs[role].timeout_seconds,
            goal=configs.get(role, AgentConfig()).goal or default_configs[role].goal,
            tools=configs.get(role, AgentConfig()).tools or default_configs[role].tools,
            skip_when=configs.get(role, AgentConfig()).skip_when or default_configs[role].skip_when,
        ) for role in AgentRole}

        return [
            RetrievalAgent(config=merged[AgentRole.RETRIEVAL]),
            AnalysisAgent(config=merged[AgentRole.ANALYSIS]),
            CriticAgent(config=merged[AgentRole.CRITIC]),
            ReportAgent(config=merged[AgentRole.REPORT]),
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
