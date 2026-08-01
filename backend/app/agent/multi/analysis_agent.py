"""Analysis sub-agent: owns claim extraction, verdict, and LLM synthesis.

Responsibilities: synthesize (attempt) -> enrich -> extract_claims ->
judge_claims -> per_claim_search loop -> re_judge. Produces structured
verdicts for each claim on the shared state.
"""
from __future__ import annotations

import logging

from backend.app.agent.multi import AgentConfig, AgentRole, AgentStatus, SubAgentResult
from backend.app.agent.state import AgentState
from backend.app.agent_tools.base import ToolContext, get_tool_fn
from backend.app.services.progress import emit_log

logger = logging.getLogger(__name__)

_STAGE_KEY = "agent_analysis"
_MAX_PER_CLAIM_ITERATIONS = 3


class AnalysisAgent:
    role = AgentRole.ANALYSIS
    description = "Extract claims, judge verdicts, and run iterative evidence refinement."

    def __init__(self, config: AgentConfig | None = None, depends_on: list[AgentRole] | None = None) -> None:
        self.config = config or AgentConfig()
        # Which upstream role produces the retrieval bundle: RETRIEVAL on the
        # sequential DAG, RETRIEVAL_MERGE on the parallel DAG.
        self._depends_on = depends_on if depends_on is not None else [AgentRole.RETRIEVAL]

    @property
    def dependencies(self) -> list[AgentRole]:
        return list(self._depends_on)

    def run(self, state: AgentState, ctx: ToolContext) -> SubAgentResult:
        actions_taken: list[str] = []
        model_used = self._apply_model(ctx)

        is_debate_round = state.debate_rounds > 0 and state.debate_focus_indices
        is_loop_back_enrichment = state.loop_back_enrichment

        emit_log(
            stage_key=_STAGE_KEY,
            title=(
                "分析 Agent 启动（补充检索）"
                if is_loop_back_enrichment
                else "分析 Agent 启动" + (f"（辩论轮次 {state.debate_rounds}）" if is_debate_round else "")
            ),
            summary=(
                f"复用已有证据，直接执行逐条补检索与重判。模型: {model_used or 'default'}"
                if is_loop_back_enrichment
                else (
                    f"对 {len(state.debate_focus_indices)} 条被质疑 claim 重新判定。模型: {model_used or 'default'}"
                    if is_debate_round
                    else f"开始声明提取与判定。模型: {model_used or 'default'}"
                )
            ),
        )

        if is_loop_back_enrichment:
            self._per_claim_loop(state, ctx, actions_taken)
            state.loop_back_enrichment = False
            emit_log(
                stage_key=_STAGE_KEY,
                title="分析 Agent 完成（补充检索）",
                summary=f"复用已有证据完成 {len(actions_taken)} 个步骤。",
                details=[f"actions={','.join(actions_taken)}"],
            )
            return SubAgentResult(
                role=self.role,
                status=AgentStatus.COMPLETED,
                actions_taken=actions_taken,
                model_used=model_used,
            )

        # In a debate round, skip synthesis and go straight to per-claim re-search
        # targeting only the claims the critic downgraded.
        if is_debate_round:
            self._debate_rejudge(state, ctx, actions_taken)
            emit_log(
                stage_key=_STAGE_KEY,
                title="分析 Agent 完成（辩论重判）",
                summary=f"辩论轮次 {state.debate_rounds} 完成 {len(actions_taken)} 个步骤。",
                details=[f"actions={','.join(actions_taken)}"],
            )
            # Clear focus indices so next critic run evaluates fresh
            state.debate_focus_indices = None
            return SubAgentResult(
                role=self.role,
                status=AgentStatus.COMPLETED,
                actions_taken=actions_taken,
                model_used=model_used,
            )

        if self._try_synthesis(state, ctx, actions_taken):
            emit_log(
                stage_key=_STAGE_KEY,
                title="分析 Agent 完成（LLM 综合成功）",
                summary="LLM 综合判定成功，跳过规则链。",
            )
            return SubAgentResult(
                role=self.role,
                status=AgentStatus.COMPLETED,
                actions_taken=actions_taken,
                model_used=model_used,
            )

        fallback_steps = ["enrich", "extract_claims", "judge_claims"]
        for action in fallback_steps:
            try:
                tool_fn = get_tool_fn(action)
                if tool_fn:
                    tool_fn(ctx, state)
                    actions_taken.append(action)
                    state.done_actions.append(action)
            except Exception as exc:
                logger.warning("analysis_agent_step_failed action=%s error=%s", action, exc)
                actions_taken.append(action)
                state.done_actions.append(action)

        self._per_claim_loop(state, ctx, actions_taken)

        emit_log(
            stage_key=_STAGE_KEY,
            title="分析 Agent 完成",
            summary=f"完成 {len(actions_taken)} 个步骤。",
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

    def _try_synthesis(self, state: AgentState, ctx: ToolContext, actions_taken: list[str]) -> bool:
        try:
            tool_fn = get_tool_fn("synthesize")
            if tool_fn is None:
                return False
            tool_fn(ctx, state)
            actions_taken.append("synthesize")
            state.done_actions.append("synthesize")
            return state.agent_synthesized
        except Exception as exc:
            logger.warning("analysis_agent_synthesis_failed error=%s", exc)
            state.synthesis_attempted = True
            actions_taken.append("synthesize")
            state.done_actions.append("synthesize")
            return False

    def _per_claim_loop(self, state: AgentState, ctx: ToolContext, actions_taken: list[str]) -> None:
        for iteration in range(_MAX_PER_CLAIM_ITERATIONS):
            if not self._has_weak_claims(state):
                break

            try:
                search_fn = get_tool_fn("per_claim_search")
                if search_fn:
                    search_fn(ctx, state)
                    actions_taken.append("per_claim_search")
                    state.done_actions.append("per_claim_search")
                    state.per_claim_searches += 1
            except Exception as exc:
                logger.warning("analysis_agent_per_claim_search_failed iter=%d error=%s", iteration, exc)
                break

            try:
                rejudge_fn = get_tool_fn("re_judge_claims")
                if rejudge_fn:
                    rejudge_fn(ctx, state)
                    actions_taken.append("re_judge_claims")
                    state.done_actions.append("re_judge_claims")
                    state.per_claim_iterations += 1
            except Exception as exc:
                logger.warning("analysis_agent_rejudge_failed iter=%d error=%s", iteration, exc)
                state.per_claim_iterations += 1
                break

    @staticmethod
    def _has_weak_claims(state: AgentState) -> bool:
        if state.verdict is None:
            return False
        return any(
            cr.claim_type == "fact" and cr.verdict == "insufficient"
            for cr in state.verdict.claim_results
        )

    def _debate_rejudge(self, state: AgentState, ctx: ToolContext, actions_taken: list[str]) -> None:
        """In a debate round, run per-claim search + re-judge only on focused claims.

        This targets just the claims the critic downgraded, potentially finding
        better evidence to restore a decisive verdict or confirming they should
        stay insufficient."""
        if state.verdict is None or not state.debate_focus_indices:
            return

        # Run per_claim_search which internally targets insufficient claims
        for iteration in range(_MAX_PER_CLAIM_ITERATIONS):
            if not self._has_debate_weak_claims(state):
                break
            try:
                search_fn = get_tool_fn("per_claim_search")
                if search_fn:
                    search_fn(ctx, state)
                    actions_taken.append("debate_per_claim_search")
                    state.done_actions.append("per_claim_search")
                    state.per_claim_searches += 1
            except Exception as exc:
                logger.warning("debate_per_claim_search_failed iter=%d error=%s", iteration, exc)
                break

            try:
                rejudge_fn = get_tool_fn("re_judge_claims")
                if rejudge_fn:
                    rejudge_fn(ctx, state)
                    actions_taken.append("debate_re_judge")
                    state.done_actions.append("re_judge_claims")
                    state.per_claim_iterations += 1
            except Exception as exc:
                logger.warning("debate_rejudge_failed iter=%d error=%s", iteration, exc)
                state.per_claim_iterations += 1
                break

    def _has_debate_weak_claims(self, state: AgentState) -> bool:
        """During debate, only consider focused claims as weak."""
        if state.verdict is None or not state.debate_focus_indices:
            return False
        return any(
            i in state.debate_focus_indices
            and cr.claim_type == "fact"
            and cr.verdict == "insufficient"
            for i, cr in enumerate(state.verdict.claim_results)
        )
