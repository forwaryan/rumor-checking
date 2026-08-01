"""Baidu SERP date-extraction tests.

Baidu emits per-result dates in a `prefix-time` span (or a fallback
`<!--s-data:...prefixTime...` JSON blob for summary-layout hits). Before
2026-07-29 the parser ignored them and every hit ended up dateless,
which downstream fabricated `datetime.now()` fallbacks masqueraded as
publication times (see [[datetime-normalization-trap]]).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.app.services.playwright_search_provider import (
    _extract_baidu_items,
    _parse_baidu_date,
)

_REF = datetime(2026, 7, 29, 12, 0, tzinfo=timezone(timedelta(hours=8)))


class TestParseBaiduDate:
    def test_absolute_chinese_date(self) -> None:
        assert _parse_baidu_date("2026年7月16日", now=_REF) == "2026-07-16"
        assert _parse_baidu_date("2026年2月25日", now=_REF) == "2026-02-25"

    def test_absolute_iso_date(self) -> None:
        assert _parse_baidu_date("2026-07-24", now=_REF) == "2026-07-24"
        assert _parse_baidu_date("2026/07/24", now=_REF) == "2026-07-24"

    def test_relative_days(self) -> None:
        assert _parse_baidu_date("今天", now=_REF) == "2026-07-29"
        assert _parse_baidu_date("昨天", now=_REF) == "2026-07-28"
        assert _parse_baidu_date("前天", now=_REF) == "2026-07-27"
        assert _parse_baidu_date("6天前", now=_REF) == "2026-07-23"
        assert _parse_baidu_date("30天前", now=_REF) == "2026-06-29"

    def test_relative_hours_and_minutes(self) -> None:
        # Same-day-so-far markers all resolve to the reference date.
        assert _parse_baidu_date("3小时前", now=_REF) == "2026-07-29"
        assert _parse_baidu_date("45分钟前", now=_REF) == "2026-07-29"
        assert _parse_baidu_date("2个小时前", now=_REF) == "2026-07-29"

    def test_relative_hours_can_cross_midnight(self) -> None:
        # Reference is 2026-07-29 01:00 CST — 3 hours ago = 2026-07-28.
        early = datetime(2026, 7, 29, 1, 0, tzinfo=timezone(timedelta(hours=8)))
        assert _parse_baidu_date("3小时前", now=early) == "2026-07-28"

    def test_no_parseable_date_returns_none(self) -> None:
        assert _parse_baidu_date("", now=_REF) is None
        assert _parse_baidu_date("   ", now=_REF) is None
        # Baidu occasionally puts "官方" in the same span slot.
        assert _parse_baidu_date("官方", now=_REF) is None
        assert _parse_baidu_date("百度百科", now=_REF) is None

    def test_invalid_absolute_date_returns_none(self) -> None:
        # 13-month date — parser should reject rather than crash.
        assert _parse_baidu_date("2026年13月45日", now=_REF) is None


class TestExtractBaiduItemsCarriesDate:
    """End-to-end: given a stub SERP HTML, each item should carry a
    published_at string (or None when the span is absent)."""

    def test_prefix_time_span_extracted(self) -> None:
        html = """
        <div id="content_left">
          <div>
            <h3><a href="https://ex.com/a">Title A</a></h3>
            <span class="c-color-gray source_1Vdff">Source A</span>
            <span class="prefix-time_650Xx">2026年7月16日</span>
            <div class="c-abstract">Snippet A</div>
          </div>
          <div>
            <h3><a href="https://ex.com/b">Title B</a></h3>
            <span class="c-color-gray">Source B</span>
            <span class="prefix-time_650Xx">6天前</span>
          </div>
        </div>
        <div id="content_right"></div>
        """
        items = _extract_baidu_items(html)
        assert len(items) == 2
        assert items[0]["published_at"] == "2026-07-16"
        # 6天前 relative to whatever today is — just assert it's a valid
        # ISO date string, not the None sentinel.
        assert items[1]["published_at"] and len(items[1]["published_at"]) == 10

    def test_prefixtime_json_fallback_when_span_absent(self) -> None:
        # Baidu's summary-layout hits omit the visible span but keep the
        # date inside an embedded s-data JSON blob.
        html = """
        <div id="content_left">
          <div>
            <h3><a href="https://ex.com/c">Title C</a></h3>
            <!--s-data:{"summaryData":{"generalLines":[{"prefixTime":"2026年2月25日"}]}}-->
            <div class="c-abstract">Snippet C</div>
          </div>
        </div>
        <div id="content_right"></div>
        """
        items = _extract_baidu_items(html)
        assert len(items) == 1
        assert items[0]["published_at"] == "2026-02-25"

    def test_missing_date_becomes_none(self) -> None:
        html = """
        <div id="content_left">
          <div>
            <h3><a href="https://ex.com/d">Title D</a></h3>
            <span class="c-color-gray">Source D</span>
            <div class="c-abstract">No date span here.</div>
          </div>
        </div>
        <div id="content_right"></div>
        """
        items = _extract_baidu_items(html)
        assert len(items) == 1
        assert items[0]["published_at"] is None
