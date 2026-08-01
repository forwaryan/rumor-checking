"""Per-source retrieval sub-agents for the parallel DAG.

Each agent owns exactly ONE evidence source and runs `retrieve_for_event` with a
`search_sources` filter so the sources fan out concurrently instead of the old
baidu→xhs→toutiao→weixin serial tail. Each writes its bundle to a disjoint
`state.source_bundles[key]` slot (no shared-write contention); the merge agent
recombines them.

All four keep `config.model = None`: they never touch `reasoner.model_override`,
so running them on parallel threads introduces no model-state race (the supervisor
asserts this before fanning out).

The three social sources reuse `state.primary_query` via `force_retrieval_query`,
which skips the query planner (and its optional LLM term extraction) since they
only need a short query string. Baidu deliberately does NOT force the query: it
runs the full multi-query plan (core/official/propagation/sub-claim) whose recall
matters, and its query plan already fans out internally.
"""
from __future__ import annotations

import logging

from backend.app.agent.multi import AgentConfig, AgentRole, AgentStatus, SubAgentResult
from backend.app.agent.state import AgentState
from backend.app.agent_tools.base import ToolContext
from backend.app.services.progress import emit_log

logger = logging.getLogger(__name__)


class SourceRetrievalAgent:
    """One evidence source, fetched in isolation via search_sources."""

    def __init__(
        self,
        *,
        role: AgentRole,
        source_key: str,
        force_primary_query: bool,
        config: AgentConfig | None = None,
    ) -> None:
        self.role = role
        self.source_key = source_key
        self.force_primary_query = force_primary_query
        # config.model stays None by construction — see module docstring.
        self.config = config or AgentConfig()
        self.description = f"Retrieve evidence from source={source_key} in isolation."

    @property
    def dependencies(self) -> list[AgentRole]:
        return [AgentRole.NORMALIZE]

    def run(self, state: AgentState, ctx: ToolContext) -> SubAgentResult:
        stage_key = f"agent_retrieval_{self.source_key}"

        # Respect the caller's source selection. If request_context.search_sources
        # is set (frontend toggle) and this source isn't in it, skip entirely —
        # otherwise every source agent runs regardless of the user's choice, since
        # the isolation below unconditionally rewrites search_sources to our own key.
        selected = state.request.request_context.get("search_sources")
        if isinstance(selected, list) and self.source_key not in selected:
            emit_log(
                stage_key=stage_key,
                title=f"检索 Agent 跳过 [{self.source_key}]",
                summary=f"来源 {self.source_key} 未被选中，跳过。",
            )
            return SubAgentResult(
                role=self.role,
                status=AgentStatus.SKIPPED,
                actions_taken=[f"skip_{self.source_key}:deselected"],
            )

        event = state.resolved_event or state.normalized_event
        if event is None:
            return SubAgentResult(
                role=self.role,
                status=AgentStatus.FAILED,
                error="no_normalized_event",
            )

        emit_log(
            stage_key=stage_key,
            title=f"检索 Agent 启动 [{self.source_key}]",
            summary=f"并行检索来源 {self.source_key}。",
        )

        request_context = dict(state.request.request_context)
        request_context["search_sources"] = [self.source_key]
        request_context["retrieval_stage_key"] = "retrieval_initial"
        if self.force_primary_query and state.primary_query:
            request_context["force_retrieval_query"] = state.primary_query

        try:
            bundle = ctx.retriever.retrieve_for_event(event, request_context=request_context)
        except Exception as exc:
            # A single source failing must NOT abort the run or skip the merge
            # (merge depends on all source roles). Degrade to an empty slot and
            # report COMPLETED — matches the "supplementary source never blocks"
            # philosophy the retrieval service already applies to social sources.
            logger.warning("source_agent_failed source=%s error=%s", self.source_key, exc)
            emit_log(
                stage_key=stage_key,
                level="warning",
                title=f"检索 Agent 降级 [{self.source_key}]",
                summary=f"来源 {self.source_key} 检索失败，本源无结果（不影响其他来源）。",
                details=[f"error={str(exc)[:120]}"],
            )
            return SubAgentResult(
                role=self.role,
                status=AgentStatus.COMPLETED,
                actions_taken=[f"search_{self.source_key}:failed"],
            )

        state.source_bundles[self.source_key] = bundle
        hits = len(bundle.canonical_results)
        emit_log(
            stage_key=stage_key,
            title=f"检索 Agent 完成 [{self.source_key}]",
            summary=f"来源 {self.source_key} 返回 {hits} 条去重结果。",
        )
        return SubAgentResult(
            role=self.role,
            status=AgentStatus.COMPLETED,
            actions_taken=[f"search_{self.source_key}"],
        )


# (role, source_key, force_primary_query) — baidu keeps its rich plan; the
# social/official sources reuse the precomputed primary query and skip re-planning.
_SOURCE_SPECS = [
    (AgentRole.RETRIEVAL_BAIDU, "baidu", False),
    (AgentRole.RETRIEVAL_XHS, "xiaohongshu", True),
    (AgentRole.RETRIEVAL_TOUTIAO, "toutiao", True),
    (AgentRole.RETRIEVAL_WEIXIN, "sogou_weixin", True),
    (AgentRole.RETRIEVAL_PIYAO, "piyao", True),
]


def build_source_agents() -> list[SourceRetrievalAgent]:
    return [
        SourceRetrievalAgent(role=role, source_key=key, force_primary_query=force)
        for role, key, force in _SOURCE_SPECS
    ]


SOURCE_ROLES = [role for role, _, _ in _SOURCE_SPECS]
