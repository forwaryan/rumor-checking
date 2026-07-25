"""Per-claim correction: compare each claim against evidence snippets and
produce a short factual correction when the evidence contradicts or refines
the claim's specific numbers/details."""

from __future__ import annotations

import json
import logging
from typing import List, Optional

import httpx

from backend.app.core.config import get_settings
from backend.app.models.schemas import ClaimResult

logger = logging.getLogger(__name__)


def annotate_claim_corrections(claim_results: List[ClaimResult]) -> List[ClaimResult]:
    """For each claim that has evidence, call a lightweight LLM to generate a
    per-claim correction if the evidence contradicts the claim's specifics
    (numbers, names, dates). Returns a new list with `correction` field set."""
    settings = get_settings()
    if not settings.llm_api_key:
        return claim_results

    # Only process claims that have evidence and are insufficient/refuted
    candidates = [
        (i, cr) for i, cr in enumerate(claim_results)
        if cr.evidence and cr.claim_type == "fact"
    ]
    if not candidates:
        return claim_results

    # Build a single batch prompt for all candidates
    claim_lines = []
    for idx, (i, cr) in enumerate(candidates):
        snippets = " | ".join(e.title for e in cr.evidence[:3] if e.title.strip())
        claim_lines.append(f"{idx+1}. claim: {cr.claim}\n   evidence: {snippets}")

    if not claim_lines:
        return claim_results

    claims_block = "\n".join(claim_lines)
    system = (
        "你是事实核查助手。对每条claim，对比它的evidence，判断claim中的数字/细节是否和evidence不一致。\n"
        "如果不一致，输出纠正；如果一致或无法判断，输出null。\n"
        "返回JSON数组，每项对应一条claim，格式：[{\"correction\": \"纠正文本或null\"}]\n"
        "纠正要具体指出：claim说的是什么，evidence显示实际是什么。不超过40字。"
    )
    user = f"待核查claims:\n{claims_block}"

    # Use a non-reasoning model
    model = "DeepSeek-V4-Flash"
    for m in settings.available_models:
        if not settings.is_reasoning_model(m):
            model = m
            break
    base_url = settings.base_url_for_model(model)

    try:
        resp = httpx.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={
                "model": model,
                "temperature": 0.2,
                "max_tokens": 512,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=30.0,
        )
        if resp.status_code != 200:
            logger.debug("claim correction LLM returned %d", resp.status_code)
            return claim_results

        data = resp.json()
        msg = data["choices"][0]["message"]
        content = (msg.get("content") or "").strip()
        if not content:
            return claim_results

        # Parse JSON array from response
        corrections = _parse_corrections(content)
        if not corrections or len(corrections) != len(candidates):
            return claim_results

        # Apply corrections
        updated = list(claim_results)
        for (i, _cr), corr in zip(candidates, corrections):
            if corr and corr != "null" and len(corr) <= 80:
                updated[i] = updated[i].model_copy(update={"correction": corr})
        return updated

    except Exception as exc:
        logger.debug("claim correction LLM failed: %s", exc)
        return claim_results


def _parse_corrections(content: str) -> Optional[List[Optional[str]]]:
    """Extract a JSON array of correction strings from LLM output."""
    # Try direct parse
    try:
        arr = json.loads(content)
        if isinstance(arr, list):
            return [
                item.get("correction") if isinstance(item, dict) else None
                for item in arr
            ]
    except json.JSONDecodeError:
        pass
    # Try extracting from markdown fencing
    import re
    match = re.search(r"\[.*\]", content, re.DOTALL)
    if match:
        try:
            arr = json.loads(match.group(0))
            if isinstance(arr, list):
                return [
                    item.get("correction") if isinstance(item, dict) else None
                    for item in arr
                ]
        except json.JSONDecodeError:
            pass
    return None
