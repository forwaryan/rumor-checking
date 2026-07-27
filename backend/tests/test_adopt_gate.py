"""Regression tests for the adopt-gate decisive-source tiebreaker.

Reproduces the 美团 case: a follow-up retrieval round surfaced the official
辟谣/回应 sources, but the adopt gate discarded it because grade, high-trust
count, and canonical count were all tied with the weaker original bundle — so
synthesis never saw the decisive evidence.
"""
from __future__ import annotations

from backend.app.services.analyze_pipeline import _bundle_quality
from backend.app.services.retrieval_models import RetrievalBundle, SearchResult


def _result(result_id: str, title: str, *, tier: str = "C", url: str | None = None) -> SearchResult:
    return SearchResult(
        case_id="live",
        query="美团 裁员",
        result_id=result_id,
        title=title,
        url=url or f"https://aggregator.example.com/{result_id}",
        source_name=url.split("//")[-1].split("/")[0] if url else "aggregator.example.com",
        published_at="",
        snippet=title,
        source_tier=tier,
    )


def _bundle(results) -> RetrievalBundle:
    return RetrievalBundle(query="美团 裁员", canonical_results=tuple(results))


def test_decisive_result_count_counts_official_and_response_hits():
    bundle = _bundle(
        [
            _result("a", "美团旗下社区团购巨头也挺不住了"),  # neither
            _result("b", "美团产品岗裁员50%消息不实 官方已辟谣"),  # response signal
            _result("c", "辟谣公告", url="https://www.meituan.com/notice"),  # official + response
        ]
    )
    assert bundle.decisive_result_count == 2


def test_adopt_gate_prefers_bundle_with_decisive_sources_on_tie():
    """The core fix: two bundles tie on grade / high-trust / canonical count, but
    the candidate carries official 辟谣/回应 sources. It must rank higher so the
    gate adopts it instead of discarding the decisive evidence."""
    original = _bundle(
        [
            _result("o1", "美团的真正威胁在暗处"),
            _result("o2", "美团一季度净亏损48.5亿元"),
            _result("o3", "美团旗下社区团购巨头也挺不住了"),
        ]
    )
    candidate = _bundle(
        [
            _result("c1", "美团产品岗裁员50%消息不实 官方已辟谣"),
            _result("c2", "网传美团大规模集中裁员 官方回应来了"),
            _result("c3", "辟谣公告", url="https://www.meituan.com/notice"),
        ]
    )
    # Same grade (C), same high-trust count (0), same canonical count (3).
    assert original.evidence_grade == candidate.evidence_grade
    assert original.independent_high_trust_source_count == candidate.independent_high_trust_source_count
    assert len(original.canonical_results) == len(candidate.canonical_results)
    # ...but the candidate has decisive sources, so it must win.
    assert _bundle_quality(candidate) > _bundle_quality(original)


def test_adopt_gate_does_not_prefer_equal_decisive_bundle():
    """No spurious adoption: when neither bundle has an edge on any dimension,
    quality ties (so the gate keeps the original)."""
    a = _bundle([_result("a1", "美团新闻一"), _result("a2", "美团新闻二")])
    b = _bundle([_result("b1", "美团新闻三"), _result("b2", "美团新闻四")])
    assert _bundle_quality(a) == _bundle_quality(b)
