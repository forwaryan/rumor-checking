"""Per-claim correction: compare each claim against evidence snippets and
produce a structured factual correction when the evidence contradicts or refines
the claim's specific numbers/details."""

from __future__ import annotations

import json
import logging
import re
from typing import Dict, List, Optional, Set

import httpx

from backend.app.core.config import get_settings
from backend.app.models.schemas import ClaimResult

logger = logging.getLogger(__name__)


def annotate_claim_corrections(
    claim_results: List[ClaimResult],
    page_bodies: Optional[Dict[str, str]] = None,
) -> List[ClaimResult]:
    """For each claim that has evidence, call a lightweight LLM to generate a
    per-claim structured correction if the evidence contradicts the claim's specifics
    (numbers, names, dates). Returns a new list with `correction` field set.

    The correction is a dict: {"original": str, "actual": str, "source": str}.
    Gracefully degrades (returns original results unchanged) on any failure.
    """
    settings = get_settings()
    if not settings.llm_api_key:
        return claim_results

    # Only process claims that have evidence and are fact-type
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
        # Include page body content from ALL available pages for richer context
        extra_context = ""
        if page_bodies:
            chars_remaining = 400
            for e in cr.evidence[:5]:
                body_text = page_bodies.get(e.url, "")
                if not body_text:
                    # Try matching by looking through page_bodies keys
                    for rid, body in page_bodies.items():
                        if body:
                            body_text = body
                            break
                if body_text and chars_remaining > 0:
                    chunk = body_text[:chars_remaining]
                    extra_context += f"\n   page_text: {chunk}"
                    chars_remaining -= len(chunk)
        claim_lines.append(
            f"{idx+1}. claim: {cr.claim}\n   evidence: {snippets}{extra_context}"
        )

    if not claim_lines:
        return claim_results

    claims_block = "\n".join(claim_lines)
    system = (
        "你是事实核查助手。对每条claim，对比它的evidence，判断claim中的数字/细节是否和evidence不一致。\n"
        "如果不一致，输出结构化纠正；如果一致或无法判断，输出null。\n"
        "actual字段中的数字必须直接来自evidence或page_text，不得推断或编造。如果evidence中没有具体数字，actual应描述证据显示的定性信息（如'大规模招聘'而非具体数字）。\n"
        '返回JSON数组，每项对应一条claim，格式：[{"correction": {"original": "用户说的", "actual": "证据显示的", "source": "来源标题"}} 或 {"correction": null}]\n'
        "original: claim中不准确的部分(不超过20字)。actual: evidence显示的实际情况(不超过30字)。source: 依据的来源标题(不超过20字)。"
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
                "max_tokens": 1024,
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

        # Apply corrections with number-grounding validation
        evidence_numbers = _extract_evidence_numbers(candidates, page_bodies)
        updated = list(claim_results)
        for (i, _cr), corr in zip(candidates, corrections):
            if corr and isinstance(corr, dict):
                # Validate the structured correction has required fields
                original = corr.get("original", "")
                actual = corr.get("actual", "")
                source = corr.get("source", "")
                if original and actual:
                    # Verify numbers in actual are grounded in evidence
                    if not _actual_is_grounded(actual, evidence_numbers.get(i, set())):
                        logger.debug(
                            "discarding correction for claim %d: "
                            "'actual' number not found in evidence", i
                        )
                        continue
                    updated[i] = updated[i].model_copy(
                        update={"correction": {
                            "original": original[:40],
                            "actual": actual[:60],
                            "source": source[:40],
                        }}
                    )
        return updated

    except Exception as exc:
        logger.debug("claim correction LLM failed: %s", exc)
        return claim_results


# Chinese number mapping for cross-referencing
_CHINESE_NUM_MAP = {
    "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    "百": 100, "千": 1000, "万": 10000, "亿": 100000000,
}

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?(?:[万亿千百十])?")


def _extract_numbers_from_text(text: str) -> Set[str]:
    """Extract all numbers (digit-based and Chinese-unit suffixed) from text."""
    if not text:
        return set()
    nums = set()
    for m in _NUMBER_RE.finditer(text):
        nums.add(m.group())
        # Also add the raw numeric part stripped of Chinese unit suffix
        raw = re.sub(r"[万亿千百十]", "", m.group())
        if raw:
            nums.add(raw)
    return nums


def _extract_evidence_numbers(
    candidates: List[tuple],
    page_bodies: Optional[Dict[str, str]],
) -> Dict[int, Set[str]]:
    """For each candidate (by original index), extract all numbers found in its
    evidence titles and page bodies."""
    result: Dict[int, Set[str]] = {}
    for i, cr in candidates:
        pool = set()
        # Numbers from evidence titles
        for e in cr.evidence:
            pool |= _extract_numbers_from_text(e.title)
        # Numbers from page bodies
        if page_bodies:
            for e in cr.evidence:
                body = page_bodies.get(e.url, "")
                if body:
                    pool |= _extract_numbers_from_text(body[:800])
            # Also scan all page_bodies values (for cross-ref)
            for body in page_bodies.values():
                if body:
                    pool |= _extract_numbers_from_text(body[:400])
        result[i] = pool
    return result


def _actual_is_grounded(actual: str, evidence_numbers: Set[str]) -> bool:
    """Check if numbers mentioned in the 'actual' field appear in the evidence.
    If actual contains no numbers at all (purely qualitative), it passes.
    If it contains numbers, at least one must appear in evidence_numbers."""
    actual_numbers = _extract_numbers_from_text(actual)
    if not actual_numbers:
        # No numbers in actual — qualitative statement, always OK
        return True
    if not evidence_numbers:
        # actual has numbers but evidence has none — hallucination
        return False
    # At least one number in actual must appear in evidence
    return bool(actual_numbers & evidence_numbers)


def _parse_corrections(content: str) -> Optional[List[Optional[Dict[str, str]]]]:
    """Extract a JSON array of structured correction objects from LLM output."""

    def _extract_item(item: object) -> Optional[Dict[str, str]]:
        if not isinstance(item, dict):
            return None
        corr = item.get("correction")
        if corr is None or corr == "null":
            return None
        if isinstance(corr, str):
            # Legacy string format — skip (we want structured)
            return None
        if isinstance(corr, dict):
            return corr
        return None

    # Try direct parse
    try:
        arr = json.loads(content)
        if isinstance(arr, list):
            return [_extract_item(item) for item in arr]
    except json.JSONDecodeError:
        pass
    # Try extracting from markdown fencing
    match = re.search(r"\[.*\]", content, re.DOTALL)
    if match:
        try:
            arr = json.loads(match.group(0))
            if isinstance(arr, list):
                return [_extract_item(item) for item in arr]
        except json.JSONDecodeError:
            pass
    return None
