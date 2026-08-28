"""Downgrade a time-scoped claim's confidence when its evidence predates the
claim's stated timeframe.

Motivating case: the claim "京东在今年…裁员" (今年 = the current year) was marked
supported · 75% on the strength of a 2024-05 article. The verdict engine already
recognizes 今年 as a time-sensitive marker, but it only used publication date to
*sort* evidence for display — it never checked whether the evidence actually
falls inside the window the claim asserts, so two-year-stale material propped up a
high-confidence "supported".

This module runs once, at the report-builder chokepoint both verdict paths share
(rule path and deep agent synthesis), so the fix covers whichever produced the
claim. It only ever *lowers* confidence — never raises it, never flips a verdict —
so it can't manufacture agreement the evidence doesn't have.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from backend.app.models.schemas import ClaimResult, EvidenceItem

# Confidence ladder, most→least certain. Downgrade = move one step toward "low".
_CONFIDENCE_ORDER = ("high", "medium", "low")

# A time-scoped claim whose newest supporting evidence is at least this many days
# older than the start of the claimed window is treated as unsupported-in-window.
# One year: enough that a claim about "this year" isn't carried by last year's — or
# older — reporting, while a few-month lag (a Dec article for a Jan claim) is fine.
_STALE_THRESHOLD_DAYS = 365

# When downgraded, truth_probability is capped here: a supported verdict whose
# evidence is out-of-window shouldn't read as near-certain. Left untouched when
# the existing value is already below the cap.
_STALE_PROBABILITY_CAP = 55

_ABSOLUTE_YEAR_RE = re.compile(r"(19|20)\d{2}\s*年?")
# Relative-year words → offset from the reference year. 今年 anchors the window to
# the reference year itself; 去年/前年 shift back; 明年/后年 shift forward.
_RELATIVE_YEAR_OFFSETS = {
    "前年": -2,
    "去年": -1,
    "旧年": -1,
    "今年": 0,
    "本年": 0,
    "明年": 1,
    "次年": 1,
    "后年": 2,
}


def _reference_date(reference: date | datetime | None) -> date:
    if isinstance(reference, datetime):
        return reference.date()
    if isinstance(reference, date):
        return reference
    # No reference supplied: fall back to today. This is a genuine "now", not a
    # fabricated source date, so it does not fall under the datetime-normalization
    # rule that forbids now() for user-visible SOURCE dates.
    return datetime.now().date()


def claimed_window_start(claim_text: str, *, reference: date | datetime | None = None) -> date | None:
    """The earliest date the claim's stated timeframe allows, or None if the claim
    names no year/relative-year window.

    Absolute years ("2026年", "2026") → Jan 1 of that year. Relative words
    ("今年"/"去年"/…) → Jan 1 of the resolved year. When several appear, the
    EARLIEST start wins, so a claim spanning "去年到今年" is judged against the
    older bound and stale evidence is not over-penalized.
    """
    ref = _reference_date(reference)
    starts: list[date] = []

    for match in _ABSOLUTE_YEAR_RE.finditer(claim_text):
        year = int(re.match(r"(19|20)\d{2}", match.group(0)).group(0))
        starts.append(date(year, 1, 1))

    for word, offset in _RELATIVE_YEAR_OFFSETS.items():
        if word in claim_text:
            starts.append(date(ref.year + offset, 1, 1))

    if not starts:
        return None
    return min(starts)


def _evidence_date(item: EvidenceItem) -> date | None:
    if not item.published_at:
        return None
    try:
        return datetime.fromisoformat(item.published_at).date()
    except ValueError:
        return None


def _supporting_evidence(claim: ClaimResult) -> list[EvidenceItem]:
    """Evidence that actually bears the claim's weight. On a supported verdict
    that's the 'supports' stance; when stance is unset (rule path often leaves it
    None) every attached item counts, matching how the panel reads."""
    supporting = [e for e in claim.evidence if e.stance == "supports"]
    if supporting:
        return supporting
    return list(claim.evidence)


def _downgrade_confidence(confidence: str) -> str:
    try:
        idx = _CONFIDENCE_ORDER.index(confidence)
    except ValueError:
        return "low"
    return _CONFIDENCE_ORDER[min(idx + 1, len(_CONFIDENCE_ORDER) - 1)]


def apply_timeliness_downgrade(
    claim_results: list[ClaimResult],
    *,
    reference: date | datetime | None = None,
) -> list[ClaimResult]:
    """Lower confidence (and cap truth_probability) for any supported/conflicting
    claim whose stated timeframe is not covered by its own supporting evidence.

    Only touches claims that (a) name a time window, (b) hold a decisive verdict
    worth trusting, and (c) have dated supporting evidence that is entirely older
    than the window by the stale threshold. Undated evidence is ignored here — the
    verdict engine already handles the all-undated case. Never raises confidence,
    never changes the verdict string.
    """
    updated: list[ClaimResult] = []
    for claim in claim_results:
        window_start = claimed_window_start(claim.claim, reference=reference)
        if window_start is None or claim.verdict not in {"supported", "conflicting"}:
            updated.append(claim)
            continue

        supporting = _supporting_evidence(claim)
        dated = [d for d in (_evidence_date(e) for e in supporting) if d is not None]
        if not dated:
            # No dated support to judge against — leave the verdict engine's own
            # undated handling in charge rather than guessing.
            updated.append(claim)
            continue

        newest = max(dated)
        staleness_days = (window_start - newest).days
        if staleness_days < _STALE_THRESHOLD_DAYS:
            updated.append(claim)
            continue

        new_confidence = _downgrade_confidence(claim.confidence)
        capped_probability = claim.truth_probability
        if capped_probability is not None and capped_probability > _STALE_PROBABILITY_CAP:
            capped_probability = _STALE_PROBABILITY_CAP
        note_flag = (
            f"\n[时效提醒] 该说法指向 {window_start.year} 年及以后，但支撑证据最新为 "
            f"{newest.isoformat()}，早于所述时间范围，已下调置信度，仅供参考。"
        )
        updated.append(
            claim.model_copy(
                update={
                    "confidence": new_confidence,
                    "truth_probability": capped_probability,
                    "notes": (claim.notes or "") + note_flag,
                }
            )
        )
    return updated
