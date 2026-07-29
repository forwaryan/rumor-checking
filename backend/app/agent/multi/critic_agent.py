"""Critic sub-agent: adversarial verification of verdicts.

After the AnalysisAgent produces verdicts, the CriticAgent challenges them:
- LLM path: re-check each decisive claim using DIVERSE PERSPECTIVES via the
  reasoner's monotonic critic. Three distinct lenses (factual accuracy, source
  quality, logical consistency) independently verify each claim. A claim is
  downgraded only when ≥2 perspectives flag it.
- Rule path (no LLM): heuristic source-strength check — a decisive verdict must
  cite at least one A/S-tier source (or two lower-tier ones) or it's downgraded.

Both paths are MONOTONE: a claim can only move toward "insufficient", never
toward a stronger conclusion, so a critic mistake can never manufacture a verdict.

When `multi_agent_critic_perspectives > 1`, the LLM path runs that many
INDEPENDENT diverse-lens passes. Each perspective is a structurally different
prompt that forces the model to evaluate from a specific angle.
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

# Diverse verification lenses — each forces the critic to evaluate from a
# structurally different angle, catching failure modes redundancy cannot.
_CRITIC_LENSES = [
    {
        "name": "factual_accuracy",
        "label": "事实准确性",
        "instruction": (
            "Focus ONLY on factual accuracy: does the cited evidence actually state "
            "what the verdict claims it states? Check for misquotes, number mismatches, "
            "scope overreach (evidence says 'some' but verdict says 'all'), and "
            "temporal mismatches (evidence is about a different time period)."
        ),
    },
    {
        "name": "source_quality",
        "label": "来源质量",
        "instruction": (
            "Focus ONLY on source quality: is the cited evidence authoritative enough "
            "to justify the verdict's confidence level? Check for: low-tier sources "
            "backing high-confidence verdicts, aggregator pages with no original reporting, "
            "anonymous or user-generated content treated as authoritative, and sources "
            "that merely repeat the claim without independent verification."
        ),
    },
    {
        "name": "logical_consistency",
        "label": "逻辑一致性",
        "instruction": (
            "Focus ONLY on logical consistency: does the reasoning from evidence to "
            "verdict follow logically? Check for: correlation-as-causation leaps, "
            "evidence about subject A used to judge subject B, partial evidence "
            "treated as conclusive, and contradictions between the evidence snippets "
            "that the verdict ignores."
        ),
    },
]


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
        all_downgraded: Set[int] = set()

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
                all_downgraded = downgraded
        else:
            if self._critique_via_rules(state, ctx):
                actions_taken.append("critique_rules")
                all_downgraded = self._rule_downgraded_indices(state)

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
            downgraded_indices=all_downgraded if all_downgraded else None,
        )

    def _apply_model(self, ctx: ToolContext) -> Optional[str]:
        if self.config.model:
            reasoner = ctx.agent_reasoner
            if hasattr(reasoner, "model_override"):
                reasoner.model_override = self.config.model
            return self.config.model
        return None

    def _critique_via_llm(self, state: AgentState, ctx: ToolContext) -> Optional[Set[int]]:
        """Run diverse-lens adversarial verification of the current verdicts.

        Uses 3 structurally different perspectives (factual accuracy, source quality,
        logical consistency) to independently verify each decisive claim. A claim is
        downgraded only when ≥2 perspectives flag it (majority vote), reducing false
        positives from any single lens while maintaining high recall.

        When `multi_agent_critic_perspectives > 1`, each configured perspective runs
        in parallel. Returns the set of downgraded claim indices, or None on failure."""
        reasoner = ctx.agent_reasoner
        if reasoner is None or not hasattr(reasoner, "critique_claims"):
            return None

        claim_results = state.verdict.claim_results
        has_decisive = any(cr.verdict in _DECISIVE and cr.evidence for cr in claim_results)
        if not has_decisive:
            return set()

        perspectives = max(int(getattr(ctx.settings, "multi_agent_critic_perspectives", 1) or 1), 1)
        lenses = _CRITIC_LENSES[:perspectives] if perspectives <= len(_CRITIC_LENSES) else _CRITIC_LENSES

        emit_log(
            stage_key=_STAGE_KEY,
            title="LLM 多视角对抗复检",
            summary=f"对判定进行 {len(lenses)} 视角对抗性验证：{', '.join(l['label'] for l in lenses)}。",
        )

        try:
            all_votes = self._collect_diverse_votes(reasoner, claim_results, lenses)
        except Exception as exc:
            logger.warning("critic_llm_failed error=%s", exc)
            return None

        # Majority vote: downgrade only when ≥2 lenses flag an index
        vote_counts: dict[int, int] = {}
        for votes in all_votes:
            for idx in votes:
                vote_counts[idx] = vote_counts.get(idx, 0) + 1

        threshold = 2 if len(lenses) >= 3 else 1
        all_downgraded = {idx for idx, count in vote_counts.items() if count >= threshold}

        if all_downgraded:
            self._apply_downgrades(state.verdict.claim_results, all_downgraded)
            emit_log(
                stage_key=_STAGE_KEY,
                title="对抗复检降级",
                summary=f"{len(all_downgraded)} 条判定因多视角一致质疑被降级为存疑。",
                details=[
                    f"downgraded_indices={sorted(all_downgraded)}",
                    f"vote_counts={dict(sorted(vote_counts.items()))}",
                ],
            )
        return all_downgraded

    @staticmethod
    def _collect_diverse_votes(reasoner, claim_results, lenses: list) -> list[Set[int]]:
        """Run each lens in parallel and return per-lens sets of flagged indices."""
        if len(lenses) == 1:
            _, downgraded = reasoner.critique_claims(claim_results)
            return [set(downgraded)]

        parent_callback = get_progress_callback()

        def _one_lens(lens: dict) -> Set[int]:
            token = set_progress_callback(parent_callback) if parent_callback is not None else None
            try:
                _, downgraded = reasoner.critique_claims(
                    claim_results, lens_instruction=lens.get("instruction")
                )
                return set(downgraded)
            finally:
                if token is not None:
                    reset_progress_callback(token)

        results: list[Set[int]] = []
        with ThreadPoolExecutor(max_workers=len(lenses)) as pool:
            futures = [pool.submit(_one_lens, lens) for lens in lenses]
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception:
                    results.append(set())
        return results

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

    @staticmethod
    def _rule_downgraded_indices(state: "AgentState") -> Set[int]:
        """Identify indices of claims that the rule path just downgraded to insufficient."""
        if state.verdict is None:
            return set()
        return {
            i for i, cr in enumerate(state.verdict.claim_results)
            if cr.claim_type == "fact" and cr.verdict == "insufficient"
            and "对抗复检" in (cr.notes or "")
        }
