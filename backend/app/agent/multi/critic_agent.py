"""Critic sub-agent: adversarial verification of verdicts.

After the AnalysisAgent produces verdicts, the CriticAgent challenges them:
- LLM path: re-check each decisive claim against its OWN cited evidence via the
  reasoner's monotonic critic (can only downgrade, never upgrade).
- Rule path (no LLM): heuristic source-strength check — a decisive verdict must
  cite at least one A/S-tier source (or two lower-tier ones) or it's downgraded.

Both paths are MONOTONE: a claim can only move toward "insufficient", never
toward a stronger conclusion, so a critic mistake can never manufacture a verdict.

When `multi_agent_critic_perspectives > 1`, the LLM path runs several independent
critic passes and downgrades a claim if ANY perspective flags it (union of votes) —
an adversarial ensemble that trades a few extra calls for higher recall on
unfaithful verdicts.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Set

from backend.app.agent.multi import AgentConfig, AgentRole, AgentStatus, SubAgentResult
from backend.app.agent.state import AgentState
from backend.app.agent_tools.base import ToolContext
from backend.app.services.progress import (
    emit_log,
    get_progress_callback,
    reset_progress_callback,
    set_progress_callback,
)

logger = logging.getLogger(__name__)

_STAGE_KEY = "agent_critic"

# A decisive verdict is one that makes a falsifiable assertion; only these are
# worth adversarial re-checking (insufficient/unsupported are already cautious).
_DECISIVE = {"supported", "refuted", "conflicting"}


class CriticAgent:
    role = AgentRole.CRITIC
    description = "Adversarially verify verdicts — can only downgrade, never upgrade."

    def __init__(self, config: Optional[AgentConfig] = None) -> None:
        self.config = config or AgentConfig()

    @property
    def dependencies(self) -> List[AgentRole]:
        return [AgentRole.ANALYSIS]

    def run(self, state: AgentState, ctx: ToolContext) -> SubAgentResult:
        actions_taken: List[str] = []
        model_used = self._apply_model(ctx)

        if state.verdict is None:
            emit_log(
                stage_key=_STAGE_KEY,
                title="批判 Agent 跳过",
                summary="无可用判定结果供批判。",
            )
            return SubAgentResult(role=self.role, status=AgentStatus.SKIPPED)

        reasoner = ctx.agent_reasoner
        llm_ready = (
            reasoner is not None
            and getattr(reasoner, "enabled", False)
            and getattr(ctx.settings, "agent_synthesis_critic_enabled", False)
        )

        if llm_ready:
            downgraded = self._critique_via_llm(state, ctx)
            if downgraded is not None:
                actions_taken.append("critique_llm")
        else:
            if self._critique_via_rules(state, ctx):
                actions_taken.append("critique_rules")

        if not actions_taken:
            emit_log(
                stage_key=_STAGE_KEY,
                title="批判 Agent 跳过",
                summary="无决定性判定需要复检。",
            )
            return SubAgentResult(role=self.role, status=AgentStatus.SKIPPED, model_used=model_used)

        emit_log(
            stage_key=_STAGE_KEY,
            title="批判 Agent 完成",
            summary=f"完成 {len(actions_taken)} 项对抗性复检。",
            details=[f"actions={','.join(actions_taken)}"],
        )
        return SubAgentResult(
            role=self.role,
            status=AgentStatus.COMPLETED,
            actions_taken=actions_taken,
            model_used=model_used,
        )

    def _apply_model(self, ctx: ToolContext) -> Optional[str]:
        if self.config.model:
            reasoner = ctx.agent_reasoner
            if hasattr(reasoner, "model_override"):
                reasoner.model_override = self.config.model
            return self.config.model
        return None

    def _critique_via_llm(self, state: AgentState, ctx: ToolContext) -> Optional[Set[int]]:
        """Run the reasoner's monotonic critic over the current verdicts.

        Returns the set of downgraded claim indices, or None on failure. When
        `multi_agent_critic_perspectives > 1`, runs that many INDEPENDENT critic
        passes in parallel — each reviews the SAME original verdicts — and
        downgrades the union of every perspective's flagged indices
        (any-perspective-flags → downgrade). Independent-then-union keeps the
        ensemble adversarial (recall-favoring) rather than a chain where a later
        pass only sees an already-weakened set."""
        reasoner = ctx.agent_reasoner
        if reasoner is None or not hasattr(reasoner, "critique_claims"):
            return None

        claim_results = state.verdict.claim_results
        has_decisive = any(cr.verdict in _DECISIVE and cr.evidence for cr in claim_results)
        if not has_decisive:
            return set()

        perspectives = max(int(getattr(ctx.settings, "multi_agent_critic_perspectives", 1) or 1), 1)

        emit_log(
            stage_key=_STAGE_KEY,
            title="LLM 对抗复检",
            summary=f"对判定进行 {perspectives} 视角对抗性验证" + ("（并行）。" if perspectives > 1 else "。"),
        )

        try:
            all_downgraded = self._collect_downgrades(reasoner, claim_results, perspectives)
        except Exception as exc:
            logger.warning("critic_llm_failed error=%s", exc)
            return None

        if all_downgraded:
            self._apply_downgrades(state.verdict.claim_results, all_downgraded)
            emit_log(
                stage_key=_STAGE_KEY,
                title="对抗复检降级",
                summary=f"{len(all_downgraded)} 条判定因所引证据不足被降级为存疑。",
                details=[f"downgraded_indices={sorted(all_downgraded)}"],
            )
        return all_downgraded

    @staticmethod
    def _collect_downgrades(reasoner, claim_results, perspectives: int) -> Set[int]:
        """Union of downgraded indices across N independent critic passes.

        Single perspective runs inline; multiple run in parallel threads with the
        progress callback rebound per worker (ContextVars don't cross threads)."""
        if perspectives == 1:
            _, downgraded = reasoner.critique_claims(claim_results)
            return set(downgraded)

        parent_callback = get_progress_callback()

        def _one_pass(_: int) -> Set[int]:
            token = set_progress_callback(parent_callback) if parent_callback is not None else None
            try:
                _, downgraded = reasoner.critique_claims(claim_results)
                return set(downgraded)
            finally:
                if token is not None:
                    reset_progress_callback(token)

        all_downgraded: Set[int] = set()
        with ThreadPoolExecutor(max_workers=perspectives) as pool:
            futures = [pool.submit(_one_pass, i) for i in range(perspectives)]
            for future in as_completed(futures):
                all_downgraded |= future.result()
        return all_downgraded

    @staticmethod
    def _apply_downgrades(claim_results, indices: Set[int]) -> None:
        """Force each flagged claim to insufficient/low (monotone). Idempotent."""
        for idx in indices:
            if 0 <= idx < len(claim_results):
                cr = claim_results[idx]
                if cr.verdict in _DECISIVE:
                    cr.verdict = "insufficient"
                    cr.confidence = "low"

    def _critique_via_rules(self, state: AgentState, ctx: ToolContext) -> bool:
        """Zero-LLM fallback: downgrade decisive verdicts lacking a strong source.

        Uses the evidence actually attached to each claim (source_tier), NOT a
        non-existent id list. Monotone: only supported/refuted/conflicting →
        insufficient."""
        emit_log(
            stage_key=_STAGE_KEY,
            title="规则判定复检",
            summary="对规则判定做来源强度一致性检查。",
        )

        any_downgraded = False
        for cr in state.verdict.claim_results:
            if cr.claim_type != "fact":
                continue
            if cr.verdict not in _DECISIVE:
                continue
            if not self._has_strong_source(cr):
                cr.verdict = "insufficient"
                cr.confidence = "low"
                note = (cr.notes or "").rstrip("。")
                cr.notes = (
                    f"{note}。对抗复检：缺少高可信来源支撑，已下调为存疑。"
                    if note
                    else "对抗复检：缺少高可信来源支撑，已下调为存疑。"
                )
                any_downgraded = True

        if any_downgraded:
            emit_log(
                stage_key=_STAGE_KEY,
                title="规则复检降级",
                summary="部分判定因来源不够强被降级为存疑。",
            )
        return True

    @staticmethod
    def _has_strong_source(claim_result) -> bool:
        """A decisive verdict is well-grounded if it cites at least one S/A-tier
        source, or at least two sources of any tier."""
        evidence = getattr(claim_result, "evidence", None) or []
        if not evidence:
            return False
        if any(getattr(ev, "source_tier", "C") in ("S", "A") for ev in evidence):
            return True
        return len(evidence) >= 2
