"""Regression tests for datetime normalization helpers.

`ensure_datetime_string` fabricates `datetime.now()` when the source has
no date, which is fine for internal timestamps but MISLEADS the timeline
UI (users saw "2026-07-29T17:48:34.228 / .231 / .231 / .231" for four
different articles — those are report-generation microsecond deltas, not
publication times). Evidence/timeline paths must use the `_or_empty`
variant so undated hits render as "时间未知" downstream.
"""
from __future__ import annotations

from backend.app.services.contract_utils import (
    ensure_datetime_string,
    ensure_datetime_string_or_empty,
)


class TestEnsureDatetimeStringOrEmpty:
    def test_returns_empty_for_none(self) -> None:
        assert ensure_datetime_string_or_empty(None) == ""

    def test_returns_empty_for_empty_string(self) -> None:
        assert ensure_datetime_string_or_empty("") == ""

    def test_returns_empty_for_whitespace(self) -> None:
        assert ensure_datetime_string_or_empty("   ") == ""

    def test_returns_empty_for_unparseable(self) -> None:
        assert ensure_datetime_string_or_empty("not-a-date") == ""

    def test_date_only_gets_midnight_shanghai(self) -> None:
        assert ensure_datetime_string_or_empty("2026-07-15") == "2026-07-15T00:00:00+08:00"

    def test_iso_string_kept(self) -> None:
        assert (
            ensure_datetime_string_or_empty("2026-07-15T10:00:00+08:00")
            == "2026-07-15T10:00:00+08:00"
        )

    def test_z_suffix_normalizes_to_utc(self) -> None:
        assert (
            ensure_datetime_string_or_empty("2026-07-15T10:00:00Z")
            == "2026-07-15T10:00:00+00:00"
        )


class TestEnsureDatetimeStringPreservesNowFallback:
    """The original helper's now() fallback is still correct for internal
    timestamps (retrieved_at). Guardrail against an accidental broad change."""

    def test_none_falls_back_to_now_not_empty(self) -> None:
        result = ensure_datetime_string(None)
        assert result != ""
        # Sanity-check that it parses as an ISO datetime by looking for the
        # year-month-day-T shape.
        assert result[4] == "-" and "T" in result
