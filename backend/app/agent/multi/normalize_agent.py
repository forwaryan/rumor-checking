"""Normalize sub-agent: shared prep for the parallel-retrieval DAG.

Runs the `normalize` tool once (all source agents need `state.normalized_event`)
and precomputes `state.primary_query`. The source agents pass that query straight
into retrieval as `force_retrieval_query`, so none of them re-runs the query
planner — which on the deep path can cost an LLM round-trip per agent.
"""
from __future__ import annotations

import logging

from backend.app.agent.multi import AgentConfig, AgentRole, AgentStatus, SubAgentResult
from backend.app.agent.state import AgentState
from backend.app.agent_tools.base import ToolContext, get_tool_fn
from backend.app.services.progress import emit_log

logger = logging.getLogger(__name__)

_STAGE_KEY = "agent_normalize"


class NormalizeAgent:
    role = AgentRole.NORMALIZE
    description = "Normalize input and precompute the shared primary query."

    def __init__(self, config: AgentConfig | None = None) -> None:
        self.config = config or AgentConfig()

    @property
    def dependencies(self) -> list[AgentRole]:
        return []

    def run(self, state: AgentState, ctx: ToolContext) -> SubAgentResult:
        actions_taken: list[str] = []

        emit_log(
            stage_key=_STAGE_KEY,
            title="标准化 Agent 启动",
            summary="标准化输入并预计算共享检索 query。",
        )

        tool_fn = get_tool_fn("normalize")
        if tool_fn is None:
            return SubAgentResult(
                role=self.role,
                status=AgentStatus.FAILED,
                error="normalize tool not registered",
            )
        try:
            tool_fn(ctx, state)
            actions_taken.append("normalize")
            state.done_actions.append("normalize")
        except Exception as exc:
            logger.error("normalize_agent_failed error=%s", exc)
            return SubAgentResult(
                role=self.role,
                status=AgentStatus.FAILED,
                actions_taken=actions_taken,
                error=f"normalize: {exc}",
            )

        state.primary_query = self._compute_primary_query(state, ctx)

        emit_log(
            stage_key=_STAGE_KEY,
            title="标准化 Agent 完成",
            summary="已标准化输入。" + (f"主 query: {state.primary_query}" if state.primary_query else ""),
            details=[f"actions={','.join(actions_taken)}"],
        )
        return SubAgentResult(
            role=self.role,
            status=AgentStatus.COMPLETED,
            actions_taken=actions_taken,
        )

    @staticmethod
    def _compute_primary_query(state: AgentState, ctx: ToolContext) -> str | None:
        """Best-effort primary query from the shared planner. Degrades to None
        (source agents then plan their own) so a planner hiccup never blocks."""
        event = state.normalized_event
        if event is None:
            return None
        retriever = ctx.retriever
        if not hasattr(retriever, "build_query_plan"):
            return None
        try:
            plan = retriever.build_query_plan(event, request_context=state.request.request_context)
        except Exception as exc:
            logger.warning("normalize_agent_query_plan_failed error=%s", exc)
            return None
        if not plan:
            return None
        return plan[0].query
