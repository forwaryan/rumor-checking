"""Report sub-agent: owns timeline construction and final report assembly.

Takes the verified claims, evidence, and timeline data and produces the
final Report object. Always runs last after all other agents complete.
"""
from __future__ import annotations

import logging

from backend.app.agent.multi import AgentConfig, AgentRole, AgentStatus, SubAgentResult
from backend.app.agent.state import AgentState
from backend.app.agent_tools.base import ToolContext, get_tool_fn
from backend.app.services.progress import emit_log

logger = logging.getLogger(__name__)

_STAGE_KEY = "agent_report"


class ReportAgent:
    role = AgentRole.REPORT
    description = "Build timeline and assemble the final verification report."

    def __init__(self, config: AgentConfig | None = None) -> None:
        self.config = config or AgentConfig()

    @property
    def dependencies(self) -> list[AgentRole]:
        return [AgentRole.CRITIC]

    def run(self, state: AgentState, ctx: ToolContext) -> SubAgentResult:
        actions_taken: list[str] = []

        emit_log(
            stage_key=_STAGE_KEY,
            title="报告 Agent 启动",
            summary="开始时间线构建与报告生成。",
        )

        if not state.agent_synthesized:
            try:
                timeline_fn = get_tool_fn("build_timeline")
                if timeline_fn:
                    timeline_fn(ctx, state)
                    actions_taken.append("build_timeline")
                    state.done_actions.append("build_timeline")
            except Exception as exc:
                logger.warning("report_agent_timeline_failed error=%s", exc)
                actions_taken.append("build_timeline")
                state.done_actions.append("build_timeline")

        try:
            finalize_fn = get_tool_fn("finalize_report")
            if finalize_fn is None:
                raise RuntimeError("finalize_report tool not registered")
            finalize_fn(ctx, state)
            actions_taken.append("finalize_report")
            state.done_actions.append("finalize_report")
        except Exception as exc:
            logger.error("report_agent_finalize_failed error=%s", exc)
            return SubAgentResult(
                role=self.role,
                status=AgentStatus.FAILED,
                actions_taken=actions_taken,
                error=f"finalize_report: {exc}",
            )

        emit_log(
            stage_key=_STAGE_KEY,
            title="报告 Agent 完成",
            summary="验证报告已生成。",
            details=[f"actions={','.join(actions_taken)}"],
        )

        return SubAgentResult(
            role=self.role,
            status=AgentStatus.COMPLETED,
            actions_taken=actions_taken,
        )
