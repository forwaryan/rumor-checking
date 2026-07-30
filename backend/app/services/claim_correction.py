"""Per-claim correction: compare each claim against evidence snippets and
produce a structured factual correction when the evidence contradicts or refines
the claim's specific numbers/details."""

from __future__ import annotations

import json
import logging
import re
from typing import Callable, Dict, List, Optional, Set

from backend.app.core.config import get_settings
from backend.app.models.schemas import ClaimResult
from backend.app.services.model_health import complete_once

logger = logging.getLogger(__name__)


def annotate_claim_corrections(
    claim_results: List[ClaimResult],
    page_bodies: Optional[Dict[str, str]] = None,
    all_evidence_titles: Optional[List[str]] = None,
    completion_fn: Optional[Callable[[str, str], str]] = None,
) -> List[ClaimResult]:
    """For each claim that has evidence, call a lightweight LLM to generate a
    per-claim structured correction if the evidence contradicts the claim's specifics
    (numbers, names, dates). Returns a new list with `correction` field set.

    The correction is a dict: {"original": str, "actual": str, "source": str}.
    Gracefully degrades (returns original results unchanged) on any failure.

    completion_fn: optional (system, user) -> content callable. When supplied, the
    LLM call is routed through it (e.g. the agent reasoner's retry/streaming layer)
    instead of the shared health-aware failover transport. This lets callers whose
    default model can actually complete the request avoid the fast-model timeout
    that the default path can hit on some gateways. The rest of the logic (prompt,
    parsing, number-grounding) is identical on both paths.
    """
    settings = get_settings()
    # The key gate only guards the default transport path. When the caller injects a
    # completion_fn, it owns the LLM transport (and its own auth), so a blank key
    # here must not block it.
    if completion_fn is None and not settings.llm_api_key:
        return claim_results

    # Only process fact-type claims. Include claims even without bound evidence
    # if we have all_evidence_titles (the pool may have relevant numbers).
    candidates = [
        (i, cr) for i, cr in enumerate(claim_results)
        if cr.claim_type == "fact" and (cr.evidence or all_evidence_titles)
    ]
    if not candidates:
        return claim_results

    # Build a "pool" context line with ALL retrieval titles containing numbers
    # so the LLM can see what evidence actually says (not just the 2 bound hits).
    pool_context = ""
    if all_evidence_titles:
        number_titles = [t for t in all_evidence_titles if _NUMBER_RE.search(t)]
        if number_titles:
            pool_context = "\n\n全部检索结果（含数字）：\n" + "\n".join(f"- {t}" for t in number_titles[:10])

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
    user = f"待核查claims:\n{claims_block}{pool_context}"

    try:
        if completion_fn is not None:
            # Caller-supplied LLM layer (e.g. agent reasoner retry/streaming path).
            content = (completion_fn(system, user) or "").strip()
        else:
            # Default path: health-aware failover over the fast models.
            content = complete_once(
                system,
                user,
                settings=settings,
                temperature=0.2,
                max_tokens=1024,
                timeout=30.0,
                stage_key="verdict_engine",
            )

        if not content:
            return claim_results

        # Parse JSON array from response
        corrections = _parse_corrections(content)
        if not corrections or len(corrections) != len(candidates):
            return claim_results

        # Apply corrections with number-grounding validation. The grounding pool
        # must include the pool titles we actually showed the LLM (all_evidence_titles),
        # not just each claim's bound evidence — decisive verdicts (esp. "refuted")
        # frequently carry no bound evidence ids, so restricting grounding to
        # cr.evidence would discard every correction whose figure lives in the pool.
        pool_numbers: Set[str] = set()
        for t in all_evidence_titles or []:
            pool_numbers |= _extract_numbers_from_text(t)
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
                    if not _actual_is_grounded(actual, evidence_numbers.get(i, set()) | pool_numbers):
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


# Chinese numeral cross-referencing. Evidence often writes figures as Chinese
# numerals ("员工突破两千人") while the claim uses Arabic ("2000"), or vice versa.
# To let number-grounding match across the two scripts, we parse contiguous
# Chinese-numeral runs into their integer value and add that (as a string) to the
# extracted number set alongside the literal Arabic digits.
_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000, "亿": 100000000}
_CN_NUM_RE = re.compile(r"[零一二两三四五六七八九十百千万亿]{1,}")

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?(?:[万亿千百十])?")


def _parse_chinese_numeral(text: str) -> Optional[int]:
    """Parse a contiguous Chinese-numeral run into an int (万/亿 close a section).
    Returns None unless the run contains an actual digit word (一二三…): a run of
    bare unit chars alone ("万" in 万元/万达, "十" in 十字路口, "千" in 千米) is NOT a
    number and must not enter the grounding pool, or a hallucinated "10000人" would
    ground against the "万" in an unrelated "万元营收". Best-effort: mixed/malformed
    runs degrade to a partial value rather than raising."""
    total = 0      # accumulated value of closed sections (>= 万)
    section = 0    # value of the section currently being built
    cur = 0        # pending single digit awaiting a unit
    has_digit = False  # a real digit word (not a bare unit) appeared
    for ch in text:
        if ch in _CN_DIGITS:
            cur = _CN_DIGITS[ch]
            has_digit = True
        elif ch in _CN_UNITS:
            unit = _CN_UNITS[ch]
            if unit >= 10000:  # 万/亿 close and scale the whole section so far
                # Default to 1 only when the section is genuinely empty ("万"=1万);
                # if 千/百/十 already built a section value, adding 1 would corrupt it
                # (一千万 must be 1000*10000, not 1001*10000).
                section = section + cur if (section or cur) else 1
                total += section * unit
                section = 0
                cur = 0
            else:              # 十/百/千 scale the pending digit into the section
                section += (cur or 1) * unit
                cur = 0
        else:
            return None
    if not has_digit:
        return None
    return total + section + cur


def _extract_numbers_from_text(text: str) -> Set[str]:
    """Extract all numbers from text as strings for cross-referencing: Arabic
    digits (with optional Chinese scale suffix stripped) AND Chinese numerals
    converted to their Arabic value, so "三千" and "3000" ground each other."""
    if not text:
        return set()
    nums = set()
    for m in _NUMBER_RE.finditer(text):
        nums.add(m.group())
        # Also add the raw numeric part stripped of Chinese unit suffix
        raw = re.sub(r"[万亿千百十]", "", m.group())
        if raw:
            nums.add(raw)
    # Chinese-numeral runs (三千 / 两千零五十) -> their Arabic value as a string.
    for m in _CN_NUM_RE.finditer(text):
        value = _parse_chinese_numeral(m.group())
        if value is not None:
            nums.add(str(value))
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
