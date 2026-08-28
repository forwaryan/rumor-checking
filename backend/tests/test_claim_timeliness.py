"""Regression tests for claim-timeliness confidence downgrade.

Guards the fix for the user-reported case: a 今年 (current-year) claim was marked
supported · 75% on 2024-05 evidence. Evidence older than the claimed window must
lower confidence (never raise it, never flip the verdict).
"""
from datetime import date

from backend.app.models.schemas import ClaimResult, EvidenceItem
from backend.app.services.claim_timeliness import apply_timeliness_downgrade, claimed_window_start

_REF = date(2026, 8, 28)


def _ev(published_at: str, *, stance: str = "supports") -> EvidenceItem:
    return EvidenceItem(
        title="京东被曝近期大规模裁员",
        url="https://example.com/a",
        source_name="www.163.com",
        published_at=published_at,
        snippet="",
        relevance_reason="r",
        source_tier="B",
        stance=stance,
    )


def _claim(
    text: str,
    *,
    verdict: str = "supported",
    confidence: str = "medium",
    truth_probability: float | None = 75,
    published_at: str = "2024-05-27",
) -> ClaimResult:
    return ClaimResult(
        claim=text,
        claim_type="fact",
        verdict=verdict,
        confidence=confidence,
        truth_probability=truth_probability,
        evidence=[_ev(published_at)],
        notes="原始notes",
    )


def test_window_start_parses_relative_and_absolute_years():
    assert claimed_window_start("京东近期进行了大规模裁员", reference=_REF) is None
    assert claimed_window_start("京东今年裁员", reference=_REF) == date(2026, 1, 1)
    assert claimed_window_start("2024年京东裁员", reference=_REF) == date(2024, 1, 1)
    # Spanning words pick the EARLIEST bound so stale evidence isn't over-penalized.
    assert claimed_window_start("去年到今年裁员", reference=_REF) == date(2025, 1, 1)
    assert claimed_window_start("明年计划", reference=_REF) == date(2027, 1, 1)


def test_current_year_claim_on_stale_evidence_is_downgraded():
    [out] = apply_timeliness_downgrade([_claim("京东今年进行了大规模裁员")], reference=_REF)
    assert out.verdict == "supported"  # verdict unchanged
    assert out.confidence == "low"  # medium -> low
    assert out.truth_probability == 55  # capped
    assert "时效提醒" in out.notes


def test_claim_without_timeframe_is_untouched():
    [out] = apply_timeliness_downgrade([_claim("京东近期进行了大规模裁员")], reference=_REF)
    assert out.confidence == "medium"
    assert out.truth_probability == 75
    assert "时效提醒" not in out.notes


def test_split_claim_inherits_timeframe_from_original_input():
    # Regression: claim splitting dropped 今年 — the rumor "京东在今年…裁员"
    # became the supported sub-claim "京东曾进行大规模裁员" with no year, so the
    # 2024 evidence propped up 75% uncapped. With the original input supplied, the
    # sub-claim inherits the rumor's 今年(2026) window and gets capped.
    original = "京东在今年830 930 730的时间内开始裁员，主要针对的是中层"
    [out] = apply_timeliness_downgrade(
        [_claim("京东曾进行大规模裁员。")], reference=_REF, original_input=original
    )
    assert out.confidence == "low"
    assert out.truth_probability == 55
    assert "时效提醒" in out.notes


def test_inherited_timeframe_not_applied_when_evidence_in_window():
    # Inheriting the rumor's window must NOT cap a claim whose evidence IS in-window.
    original = "京东在今年830 930 730的时间内开始裁员"
    [out] = apply_timeliness_downgrade(
        [_claim("京东曾进行大规模裁员。", published_at="2026-07-13")],
        reference=_REF,
        original_input=original,
    )
    assert out.confidence == "medium"
    assert out.truth_probability == 75


def test_no_original_input_leaves_timeframeless_claim_untouched():
    # Without an original_input fallback, a timeframe-less claim stays as-is
    # (preserves the pre-fix behavior for callers that don't pass it).
    [out] = apply_timeliness_downgrade([_claim("京东曾进行大规模裁员。")], reference=_REF)
    assert out.confidence == "medium"
    assert out.truth_probability == 75


def test_in_window_evidence_is_untouched():
    [out] = apply_timeliness_downgrade(
        [_claim("京东今年进行了大规模裁员", published_at="2026-07-13")], reference=_REF
    )
    assert out.confidence == "medium"
    assert out.truth_probability == 75
    assert "时效提醒" not in out.notes


def test_same_year_earlier_month_is_not_stale():
    # Jan 2026 evidence for a 2026 claim is < 365 days before window start — fine.
    [out] = apply_timeliness_downgrade(
        [_claim("京东今年裁员", published_at="2026-01-15")], reference=_REF
    )
    assert out.confidence == "medium"


def test_high_confidence_steps_down_one_notch():
    [out] = apply_timeliness_downgrade(
        [_claim("京东今年裁员", confidence="high", truth_probability=90)], reference=_REF
    )
    assert out.confidence == "medium"  # high -> medium (one step)
    assert out.truth_probability == 55


def test_insufficient_verdict_never_changes():
    [out] = apply_timeliness_downgrade(
        [_claim("京东今年裁员", verdict="insufficient", confidence="low", truth_probability=15)],
        reference=_REF,
    )
    assert out.verdict == "insufficient"
    assert out.confidence == "low"
    assert out.truth_probability == 15


def test_low_probability_not_raised_by_cap():
    # Cap must only lower — a 40 stays 40, not bumped to 55.
    [out] = apply_timeliness_downgrade(
        [_claim("京东今年裁员", confidence="low", truth_probability=40)], reference=_REF
    )
    assert out.truth_probability == 40


def test_undated_supporting_evidence_defers_to_verdict_engine():
    [out] = apply_timeliness_downgrade(
        [_claim("京东今年裁员", published_at="")], reference=_REF
    )
    # No dated support to judge — leave it alone.
    assert out.confidence == "medium"
    assert "时效提醒" not in out.notes
