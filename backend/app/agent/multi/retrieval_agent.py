"""Retrieval sub-agent: owns input normalization and all evidence gathering.

Responsibilities: normalize -> search_news -> resolve_question -> follow_up ->
investigate -> fetch_url. Outputs a fully populated retrieval bundle on the
shared state for downstream agents to consume.
"""
from __future__ import annotations

import logging

from backend.app.agent.multi import AgentConfig, AgentRole, AgentStatus, SubAgentResult
from backend.app.agent.state import AgentState
from backend.app.agent_tools.base import ToolContext, get_tool_fn
from backend.app.services.progress import emit_log
from backend.app.services.retrieval_models import LOW_EVIDENCE_GRADES

logger = logging.getLogger(__name__)

_STAGE_KEY = "agent_retrieval"


class RetrievalAgent:
    role = AgentRole.RETRIEVAL
    description = "Normalize input and gather all evidence from web sources."

    def __init__(self, config: AgentConfig | None = None) -> None:
        self.config = config or AgentConfig()

    @property
    def dependencies(self) -> list[AgentRole]:
        return []

    def run(self, state: AgentState, ctx: ToolContext) -> SubAgentResult:
        actions_taken: list[str] = []
        model_used = self._apply_model(ctx)

        emit_log(
            stage_key=_STAGE_KEY,
            title="检索 Agent 启动",
            summary=f"开始输入标准化和证据检索。模型: {model_used or 'default'}",
        )

        steps = [
            ("normalize", True),
            ("search_news", True),
            ("resolve_question", False),
            ("follow_up_retrieval", False),
        ]

        for action, critical in steps:
            try:
                tool_fn = get_tool_fn(action)
                if tool_fn is None:
                    continue
                tool_fn(ctx, state)
                actions_taken.append(action)
                state.done_actions.append(action)
            except Exception as exc:
                if critical:
                    logger.error("retrieval_agent_critical_failure action=%s error=%s", action, exc)
                    return SubAgentResult(
                        role=self.role,
                        status=AgentStatus.FAILED,
                        actions_taken=actions_taken,
                        error=f"{action}: {exc}",
                        model_used=model_used,
                    )
                logger.warning("retrieval_agent_step_failed action=%s error=%s", action, exc)
                actions_taken.append(action)
                state.done_actions.append(action)

        if self._should_investigate(state, ctx):
            try:
                tool_fn = get_tool_fn("investigate")
                if tool_fn:
                    tool_fn(ctx, state)
                    actions_taken.append("investigate")
                    state.done_actions.append("investigate")
            except Exception as exc:
                logger.warning("retrieval_agent_investigate_failed error=%s", exc)

        if self._should_fetch_url(state, ctx):
            try:
                tool_fn = get_tool_fn("fetch_url")
                if tool_fn:
                    tool_fn(ctx, state)
                    actions_taken.append("fetch_url")
                    state.done_actions.append("fetch_url")
            except Exception as exc:
                logger.warning("retrieval_agent_fetch_url_failed error=%s", exc)

        emit_log(
            stage_key=_STAGE_KEY,
            title="检索 Agent 完成",
            summary=f"完成 {len(actions_taken)} 个步骤，获取证据。",
            details=[f"actions={','.join(actions_taken)}"],
        )

        return SubAgentResult(
            role=self.role,
            status=AgentStatus.COMPLETED,
            actions_taken=actions_taken,
            model_used=model_used,
        )

    def _apply_model(self, ctx: ToolContext) -> str | None:
        if self.config.model:
            reasoner = ctx.agent_reasoner
            if hasattr(reasoner, "model_override"):
                reasoner.model_override = self.config.model
            return self.config.model
        return None

    def _should_investigate(self, state: AgentState, ctx: ToolContext) -> bool:
        lightweight = getattr(ctx.settings, "lightweight_agent_ready", False)
        if not lightweight:
            return False
        bundle = state.retrieval_bundle
        if bundle is None:
            return False
        return bundle.evidence_grade in LOW_EVIDENCE_GRADES

    def _should_fetch_url(self, state: AgentState, ctx: ToolContext) -> bool:
        if len(state.fetched_bodies) >= state.max_url_fetches:
            return False
        bundle = state.retrieval_bundle
        if bundle is None:
            return False
        return any(
            r.url and r.result_id not in state.fetched_bodies
            for r in bundle.canonical_results[:3]
        )
