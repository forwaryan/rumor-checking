"""Merge sub-agent: recombine the parallel source bundles, then refine.

Waits on all source agents (declared as dependencies), unions their per-source
bundles into a single `state.retrieval_bundle`, then runs the post-initial
retrieval refinement the old single RetrievalAgent did: resolve_question ->
follow_up_retrieval -> investigate -> fetch_url.

Result ids are namespaced by source key before union. Providers already use
distinct id prefixes (web-/xhs_/tt_/wx_), but downstream synthesis keys evidence
by id, so a defensive per-source namespace guarantees no cross-source collision
ever conflates unrelated articles — the same defense retrieval_service applies
across queries.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from typing import List, Optional

from backend.app.agent.multi import AgentConfig, AgentRole, AgentStatus, SubAgentResult
from backend.app.agent.multi.source_agents import SOURCE_ROLES
from backend.app.agent.state import AgentState
from backend.app.agent_tools.base import ToolContext, get_tool_fn
from backend.app.models.schemas import NormalizedEvent
from backend.app.services.progress import emit_log
from backend.app.services.retrieval_deduper import chronological_sort_key, merge_search_results
from backend.app.services.retrieval_models import RetrievalBundle

logger = logging.getLogger(__name__)

_STAGE_KEY = "agent_retrieval_merge"


class MergeAgent:
    role = AgentRole.RETRIEVAL_MERGE
    description = "Merge parallel source bundles and run retrieval refinement."

    def __init__(self, config: Optional[AgentConfig] = None) -> None:
        self.config = config or AgentConfig()

    @property
    def dependencies(self) -> List[AgentRole]:
        return list(SOURCE_ROLES)

    def run(self, state: AgentState, ctx: ToolContext) -> SubAgentResult:
        actions_taken: List[str] = []

        merged = self._merge_source_bundles(state)
        if merged is None:
            emit_log(
                stage_key=_STAGE_KEY,
                level="warning",
                title="合并 Agent 无结果",
                summary="所有来源都没有返回结果。",
            )
            # Leave retrieval_bundle as-is (None); downstream degrades gracefully.
        else:
            state.initial_retrieval_bundle = merged
            state.retrieval_bundle = merged
            actions_taken.append("merge_sources")
            state.done_actions.append("merge_sources")
            emit_log(
                stage_key=_STAGE_KEY,
                title="合并 Agent 完成来源汇总",
                summary=f"已汇总 {len(state.source_bundles)} 个来源，共 {len(merged.canonical_results)} 条去重结果。",
                details=[f"sources={','.join(sorted(state.source_bundles))}"],
            )

        # Post-retrieval refinement: same steps the single RetrievalAgent ran
        # after the initial search. Each tool self-gates on state.
        self._run_step(ctx, state, "resolve_question", actions_taken)
        self._run_step(ctx, state, "follow_up_retrieval", actions_taken)
        if self._should_investigate(state, ctx):
            self._run_step(ctx, state, "investigate", actions_taken)
        if self._should_fetch_url(state, ctx):
            self._run_step(ctx, state, "fetch_url", actions_taken)

        return SubAgentResult(
            role=self.role,
            status=AgentStatus.COMPLETED,
            actions_taken=actions_taken,
        )

    def _merge_source_bundles(self, state: AgentState) -> Optional[RetrievalBundle]:
        bundles = [(key, b) for key, b in state.source_bundles.items() if b is not None]
        if not bundles:
            return None

        raw_results = []
        for source_key, bundle in bundles:
            raw_results.extend(self._namespace_results(bundle.raw_results, source_key))

        canonical_pool = []
        for source_key, bundle in bundles:
            canonical_pool.extend(self._namespace_results(bundle.canonical_results, source_key))
        canonical_results = merge_search_results(canonical_pool)

        # Prefer the primary (baidu) bundle for scalar provenance; fall back to the
        # first available. Computed props (evidence_grade, counts) derive from the
        # canonical set, so they recompute correctly on the merged bundle.
        primary = state.source_bundles.get("baidu") or bundles[0][1]
        retrieved_at = max((b.retrieved_at for _, b in bundles if b.retrieved_at), default=primary.retrieved_at)
        provider_name = "multi:" + "+".join(sorted(state.source_bundles))

        return RetrievalBundle(
            query=state.primary_query or primary.query,
            matched_case_id=primary.matched_case_id or "real_search",
            mode_hint=self._mode_hint_for_results(canonical_results),
            raw_results=tuple(sorted(raw_results, key=chronological_sort_key)),
            canonical_results=tuple(sorted(canonical_results, key=chronological_sort_key)),
            expected_origin_result_id=primary.expected_origin_result_id,
            expected_turning_point_result_id=primary.expected_turning_point_result_id,
            provider_name=provider_name,
            cache_status=primary.cache_status,
            fallback_used=all(b.fallback_used for _, b in bundles),
            retrieved_at=retrieved_at,
            query_groups=primary.query_groups,
            query_failures=tuple(
                f for _, b in bundles for f in b.query_failures
            ),
        )

    @staticmethod
    def _namespace_results(results, source_key: str):
        prefix = f"{source_key}::"
        renamed = []
        for item in results:
            new_dup = f"{prefix}{item.duplicate_of}" if item.duplicate_of else item.duplicate_of
            renamed.append(replace(item, result_id=f"{prefix}{item.result_id}", duplicate_of=new_dup))
        return renamed

    @staticmethod
    def _mode_hint_for_results(canonical_results) -> str:
        high_trust_sources = {
            item.effective_independence_key
            for item in canonical_results
            if item.is_high_trust and item.effective_independence_key
        }
        if len(high_trust_sources) >= 2:
            return "complete_or_partial"
        if canonical_results:
            return "partial"
        return "safe"

    @staticmethod
    def _run_step(ctx: ToolContext, state: AgentState, action: str, actions_taken: List[str]) -> None:
        tool_fn = get_tool_fn(action)
        if tool_fn is None:
            return
        try:
            tool_fn(ctx, state)
            actions_taken.append(action)
            state.done_actions.append(action)
        except Exception as exc:
            logger.warning("merge_agent_step_failed action=%s error=%s", action, exc)

    @staticmethod
    def _should_investigate(state: AgentState, ctx: ToolContext) -> bool:
        if not getattr(ctx.settings, "lightweight_agent_ready", False):
            return False
        bundle = state.retrieval_bundle
        if bundle is None:
            return False
        return bundle.evidence_grade in ("weak", "none")

    @staticmethod
    def _should_fetch_url(state: AgentState, ctx: ToolContext) -> bool:
        if len(state.fetched_bodies) >= state.max_url_fetches:
            return False
        bundle = state.retrieval_bundle
        if bundle is None:
            return False
        return any(
            r.url and r.result_id not in state.fetched_bodies
            for r in bundle.canonical_results[:3]
        )
