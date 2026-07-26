"""LLM-based verdict for fact claims where the rule engine is inconclusive.

The rule engine is fast and deterministic but struggles with nuanced claims
that require semantic understanding (causal reasoning, implicit contradictions,
partial overlap). This module provides an LLM fallback: when the rule engine
returns "insufficient" for a fact claim that has associated evidence, we ask
the LLM to judge whether the evidence supports, refutes, or is inconclusive
about the claim.

Only invoked when:
1. LLM is configured and available
2. The claim is fact-type
3. The rule verdict is "insufficient" (rule engine couldn't decide)
4. There is at least some evidence bound to the claim
"""

from __future__ import annotations

import json
import logging
import re
from typing import Callable, List, Optional, Tuple

import httpx

from backend.app.core.config import Settings, get_settings
from backend.app.models.schemas import ClaimResult, EvidenceItem
from backend.app.services.progress import emit_log, emit_stage

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "你是事实核查裁判。对于给定的claim和证据，判断证据是否支持(supported)、否定(refuted)、"
    "或无法判断(insufficient)该claim。\n\n"
    "规则:\n"
    "1. 只看证据说了什么，不使用自己的知识\n"
    "2. 如果证据中的数字与claim不同，判为refuted\n"
    "3. 如果证据明确否认了claim的核心事实，判为refuted\n"
    "4. 如果证据确认了claim的核心事实，判为supported\n"
    "5. 如果证据不相关或模糊，判为insufficient\n\n"
    '返回JSON: {"verdict": "supported"|"refuted"|"insufficient", '
    '"confidence": "high"|"medium"|"low", '
    '"reason": "一句话解释(不超过30字)"}'
)

_VALID_VERDICTS = {"supported", "refuted", "insufficient"}
_VALID_CONFIDENCES = {"high", "medium", "low"}


def llm_judge_claims(
    claim_results: List[ClaimResult],
    settings: Optional[Settings] = None,
    completion_fn: Optional[Callable[[str, str], str]] = None,
) -> List[ClaimResult]:
    """Re-judge insufficient fact claims using LLM.

    Only upgrades claims from "insufficient" to a stronger verdict when the
    LLM is confident. Returns a new list with updated verdicts where applicable.
    Gracefully degrades (returns original results) on any failure.

    completion_fn: optional (system, user) -> content callable. When supplied,
    LLM calls route through it (e.g. the agent reasoner's retry/streaming layer)
    instead of the built-in one-shot httpx POST. Same gate logic as claim_correction:
    when completion_fn is provided, the api key check is bypassed.
    """
    if settings is None:
        settings = get_settings()
    if completion_fn is None and not settings.llm_api_key:
        return claim_results

    candidates = [
        (i, cr) for i, cr in enumerate(claim_results)
        if cr.claim_type == "fact"
        and cr.verdict == "insufficient"
        and cr.evidence
    ]
    if not candidates:
        return claim_results

    emit_stage(
        stage_key="llm_verdict",
        title="LLM 补判",
        status="running",
        summary=f"规则引擎对 {len(candidates)} 条 claim 判定不足，正在调用 LLM 二次判定。",
        details=[f"candidate_claims={len(candidates)}"],
    )

    updated = list(claim_results)
    upgraded_count = 0
    for i, cr in candidates:
        result = _judge_single_claim(cr, settings, completion_fn=completion_fn)
        if result is not None:
            updated[i] = result
            upgraded_count += 1
            emit_log(
                stage_key="llm_verdict",
                title="LLM 判定升级",
                summary=f"claim「{cr.claim[:30]}」从 insufficient 升级为 {result.verdict}",
                details=[
                    f"verdict={result.verdict}",
                    f"confidence={result.confidence}",
                ],
            )

    status = "completed" if upgraded_count > 0 else "skipped"
    summary = (
        f"LLM 补判完成，{upgraded_count}/{len(candidates)} 条 claim 获得明确判定。"
        if upgraded_count > 0
        else "LLM 补判未改变任何 verdict（证据仍不足以强判）。"
    )
    emit_stage(
        stage_key="llm_verdict",
        title="LLM 补判",
        status=status,
        summary=summary,
        details=[
            f"candidates={len(candidates)}",
            f"upgraded={upgraded_count}",
        ],
    )

    return updated


def _judge_single_claim(
    claim_result: ClaimResult,
    settings: Settings,
    *,
    completion_fn: Optional[Callable[[str, str], str]] = None,
) -> Optional[ClaimResult]:
    """Ask LLM to judge a single claim against its evidence."""
    evidence_text = "\n".join(
        f"- [{e.source_tier}] {e.title}: {e.snippet}"
        for e in claim_result.evidence[:5]
    )
    user_prompt = f"Claim: {claim_result.claim}\n\n证据:\n{evidence_text}"

    try:
        if completion_fn is not None:
            content = (completion_fn(_SYSTEM_PROMPT, user_prompt) or "").strip()
        else:
            model = _pick_fast_model(settings)
            base_url = settings.base_url_for_model(model)
            resp = httpx.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json={
                    "model": model,
                    "temperature": 0.1,
                    "max_tokens": 256,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                },
                timeout=15.0,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            content = (data["choices"][0]["message"].get("content") or "").strip()

        if not content:
            return None
        return _parse_verdict_response(content, claim_result)

    except Exception as exc:
        logger.debug("LLM verdict failed for claim: %s", exc)
        return None


def _parse_verdict_response(
    content: str,
    original: ClaimResult,
) -> Optional[ClaimResult]:
    """Parse LLM response and return updated ClaimResult if valid."""
    try:
        start = content.index("{")
        end = content.rindex("}") + 1
        parsed = json.loads(content[start:end])
    except (ValueError, json.JSONDecodeError):
        return None

    verdict = parsed.get("verdict", "").strip().lower()
    confidence = parsed.get("confidence", "").strip().lower()
    reason = parsed.get("reason", "").strip()

    if verdict not in _VALID_VERDICTS:
        return None
    if confidence not in _VALID_CONFIDENCES:
        confidence = "medium"

    if verdict == "insufficient":
        return None

    notes = original.notes or ""
    if reason:
        notes = f"{notes} [LLM判定] {reason}" if notes else f"[LLM判定] {reason}"

    return original.model_copy(
        update={
            "verdict": verdict,
            "confidence": confidence,
            "notes": notes,
        }
    )


def _pick_fast_model(settings: Settings) -> str:
    """Pick a fast (non-reasoning) model for verdict judgment."""
    for m in settings.available_models:
        if not settings.is_reasoning_model(m):
            return m
    return settings.llm_model or "DeepSeek-V4-Flash"
