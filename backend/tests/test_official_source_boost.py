"""Targeted official-source boost: whitelist selection + retrieval merge.

The boost is a second-pass retrieval that only fires when the primary bundle
is weak on high-tier evidence (grade C/D and zero independent S/A sources).
It runs the primary provider with `site:x OR site:y` limited to a curated
whitelist so we probe officials directly instead of counting on Baidu to
surface them.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from backend.app.services.retrieval_models import (
    RetrievalBundle,
    SearchResult,
    build_independence_key,
    detect_signal_tags,
    infer_source_category,
)
from backend.app.services.retrieval_service import RetrievalService


class _StubProvider:
    """Records the query it was called with and replies with pre-canned hits."""

    def __init__(self, hits: list[SearchResult]):
        self.hits = hits
        self.name = "stub"
        self.enabled = True
        self.calls: list[str] = []

    def search(self, query: str) -> list[SearchResult]:
        self.calls.append(query)
        return list(self.hits)


def _result(url: str, source_name: str, source_tier: str, title: str = "t") -> SearchResult:
    r = SearchResult(
        case_id="test",
        query="q",
        result_id=url,
        title=title,
        url=url,
        source_name=source_name,
        published_at="2026-07-20T09:00:00+08:00",
        snippet=title,
        source_tier=source_tier,
        provider_name="stub",
    )
    return replace(
        r,
        independence_key=build_independence_key(url, source_name),
        source_category=infer_source_category(url, source_name),
        signal_tags=detect_signal_tags(title, title, source_name),
    )


def _bundle(results: list[SearchResult]) -> RetrievalBundle:
    return RetrievalBundle(
        query="耿同学 Nature 撤稿",
        matched_case_id="test",
        canonical_results=tuple(results),
        raw_results=tuple(results),
        provider_name="stub",
    )


def _service_with_provider(provider: _StubProvider) -> RetrievalService:
    svc = RetrievalService.__new__(RetrievalService)
    svc.provider = provider
    svc.settings = None  # not needed for the boost path
    return svc


def test_pick_whitelist_includes_academic_group_for_academic_query():
    svc = RetrievalService.__new__(RetrievalService)
    domains = svc._pick_official_whitelist("耿同学 Nature 论文 造假 撤稿")
    # Always-on group present
    assert "gov.cn" in domains
    assert "xinhuanet.com" in domains
    # Academic group present because query mentions Nature / 撤稿
    assert "nature.com" in domains
    assert "retractionwatch.com" in domains
    # Off-topic groups NOT pulled in
    assert "nhc.gov.cn" not in domains
    assert "cea.gov.cn" not in domains


def test_pick_whitelist_falls_back_to_always_on_group():
    svc = RetrievalService.__new__(RetrievalService)
    domains = svc._pick_official_whitelist("某网红开演唱会")
    assert "gov.cn" in domains
    # No topical hits → academic/health/quake/finance groups absent
    assert "nature.com" not in domains
    assert "nhc.gov.cn" not in domains


def test_boost_skips_when_bundle_already_has_high_trust_source():
    provider = _StubProvider(hits=[_result("https://nature.com/x", "Nature", "S")])
    svc = _service_with_provider(provider)
    strong = _bundle([
        _result("https://xinhuanet.com/a", "新华网", "A"),
        _result("https://zhihu.com/q/1", "知乎", "C"),
    ])
    out = svc._append_official_source_results(strong, "耿同学 Nature 撤稿", stage_key="s")
    assert out is strong
    assert provider.calls == []


def test_boost_skips_when_grade_is_A_or_B():
    provider = _StubProvider(hits=[_result("https://nature.com/x", "Nature", "S")])
    svc = _service_with_provider(provider)
    # No high-trust source in bundle, but grade_B (>=1 high_trust_result_count)
    b_grade = _bundle([_result("https://xinhuanet.com/a", "新华网", "A")])
    # A-tier hit makes bundle high_trust_result_count == 1, grade = "B".
    # Because we already have >=1 independent high-trust source, boost skips.
    out = svc._append_official_source_results(b_grade, "耿同学 Nature 撤稿", stage_key="s")
    assert out is b_grade
    assert provider.calls == []


def test_boost_fires_and_merges_when_bundle_is_thin():
    boost_hit = _result("https://www.nature.com/articles/xxxx", "Nature", "S", title="Retracted paper")
    provider = _StubProvider(hits=[boost_hit])
    svc = _service_with_provider(provider)
    thin = _bundle([
        _result("https://m.163.com/a", "163", "B"),
        _result("https://zhihu.com/q/1", "知乎", "C"),
        _result("https://xiaohongshu.com/x", "小红书", "C"),
    ])
    # Sanity: thin bundle has zero independent S/A source → boost should fire.
    assert thin.independent_high_trust_source_count == 0
    assert thin.evidence_grade == "C"

    out = svc._append_official_source_results(thin, "耿同学 Nature 撤稿", stage_key="s")
    assert out is not thin
    assert len(provider.calls) == 1
    # Query passed to provider must carry site: filters (Baidu-compatible)
    query = provider.calls[0]
    assert "site:nature.com" in query
    assert " OR " in query
    # The new nature.com hit is now in canonical + independent high-trust count reflects it
    urls = {r.url for r in out.canonical_results}
    assert "https://www.nature.com/articles/xxxx" in urls
    assert out.independent_high_trust_source_count == 1


def test_boost_dedupes_by_independence_key():
    """If a boost query re-surfaces a domain already in the bundle it must not
    double-count that domain as a fresh independent source."""
    existing = _result("https://www.people.com.cn/a", "人民网", "A")
    boost_hit = _result("https://www.people.com.cn/b", "人民网另一篇", "A")
    provider = _StubProvider(hits=[boost_hit])
    svc = _service_with_provider(provider)
    # existing is A-tier so bundle is grade B and boost normally would skip.
    # Force the weak state by using a C-only bundle then adding a same-domain
    # low-tier existing entry.
    weak_existing = _result("https://www.people.com.cn/a", "人民网转载", "C")
    thin = _bundle([weak_existing])
    assert thin.evidence_grade == "C"
    out = svc._append_official_source_results(thin, "耿同学 Nature 撤稿", stage_key="s")
    # provider was called, but the returned bundle should NOT gain a duplicate
    # people.com.cn entry because the independence key matches.
    people_hits = [r for r in out.canonical_results if "people.com.cn" in r.url]
    assert len(people_hits) == 1


def test_boost_is_disabled_when_context_flag_set():
    """The pipeline flag disable_official_boost has to short-circuit the caller
    before this method is ever entered — assert the method itself is a no-op if
    the primary provider is disabled, which is the mechanism the caller uses."""
    provider = _StubProvider(hits=[_result("https://nature.com/x", "Nature", "S")])
    provider.enabled = False
    svc = _service_with_provider(provider)
    thin = _bundle([_result("https://zhihu.com/q/1", "知乎", "C")])
    out = svc._append_official_source_results(thin, "耿同学 Nature 撤稿", stage_key="s")
    assert out is thin
    assert provider.calls == []


def test_boost_swallows_provider_exception():
    class _Failing:
        name = "boom"
        enabled = True
        def search(self, q): raise RuntimeError("upstream 500")

    svc = _service_with_provider(_Failing())
    thin = _bundle([_result("https://zhihu.com/q/1", "知乎", "C")])
    # Must not propagate; the bundle is returned unchanged and the pipeline
    # continues with whatever the primary retrieval collected.
    out = svc._append_official_source_results(thin, "耿同学 Nature 撤稿", stage_key="s")
    assert out is thin
