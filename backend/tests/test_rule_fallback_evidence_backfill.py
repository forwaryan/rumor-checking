"""Rule fallback safety net: rescue claim.evidence when the rule / LLM judge
path selected almost nothing but the retrieval bundle clearly has high-tier
material. This mirrors the failure mode from the 耿同学/Nature 撤稿 run where
LLM synthesis silently returned empty three times, the pipeline dropped to
the rule path, and the report ended up showing 20+ retrieval hits alongside a
"证据不足" verdict with only one xiaohongshu URL attached to the main claim.
"""
from __future__ import annotations

from backend.app.models.schemas import (
    AnalyzeRequest,
    ClaimItem,
    ClaimResult,
    EvidenceItem,
    NormalizedEvent,
)
from backend.app.services.retrieval_models import RetrievalBundle, SearchResult, build_independence_key
from backend.app.services.verdict_engine import VerdictEngine


def _hit(url: str, tier: str = "B", *, title: str = "") -> SearchResult:
    return SearchResult(
        case_id="test", query="q", result_id=url, title=title or url,
        url=url, source_name=url.split("//")[-1].split("/")[0],
        published_at="2026-07-29T09:00:00+08:00",
        snippet=title or url, source_tier=tier, provider_name="test",
        independence_key=build_independence_key(url, ""),
    )


def _pool_item(url: str, tier: str = "B", *, title: str = "") -> EvidenceItem:
    return EvidenceItem(
        title=title or url, url=url,
        source_name=url.split("//")[-1].split("/")[0],
        published_at="2026-07-29T09:00:00+08:00",
        snippet=title or url,
        relevance_reason="retrieved",
        source_tier=tier,
    )


def _claim_result(url_evidences: list[str], notes: str = "") -> ClaimResult:
    """Build a ClaimResult with the given attached URLs (evidence)."""
    evidence = [
        EvidenceItem(
            title=url, url=url, source_name=url,
            published_at="", snippet=url, relevance_reason="prev-rule-selected",
            source_tier="C",
        )
        for url in url_evidences
    ]
    return ClaimResult(
        claim="耿同学查到4个院士在nature上的论文造假。",
        claim_type="fact",
        verdict="insufficient",
        confidence="low",
        evidence=evidence,
        notes=notes,
    )


def test_backfill_fires_when_claim_has_zero_evidence():
    """The core rescue: rule engine selected nothing but the pool has 5 high-tier hits."""
    engine = VerdictEngine()
    pool = [
        _pool_item("https://m.163.com/1", tier="B", title="163 报道A"),
        _pool_item("https://news.qq.com/2", tier="B", title="腾讯 报道B"),
        _pool_item("https://news.sina.cn/3", tier="B", title="新浪 报道C"),
        _pool_item("https://mp.weixin.qq.com/4", tier="B", title="微信 报道D"),
        _pool_item("https://zhihu.com/5", tier="C", title="知乎 干扰"),
    ]
    results = engine._backfill_rule_fallback_evidence(
        results=[_claim_result([])],
        evidence_pool=pool,
    )
    assert len(results[0].evidence) == 3
    assert "规则兜底" in (results[0].notes or "")
    # Top-3 by tier priority: all B, not the C-tier zhihu
    attached_urls = {ev.url for ev in results[0].evidence}
    assert "https://zhihu.com/5" not in attached_urls
    # All attached items carry the "参考材料" marker in relevance_reason.
    for ev in results[0].evidence:
        assert "rule fallback" in ev.relevance_reason.lower()


def test_backfill_fires_when_claim_has_exactly_one_evidence():
    """Attached=1 is still 'almost nothing' — the failure mode we're rescuing."""
    engine = VerdictEngine()
    pool = [
        _pool_item("https://a.com/x", tier="B", title="A"),
        _pool_item("https://b.com/y", tier="B", title="B"),
        _pool_item("https://c.com/z", tier="B", title="C"),
    ]
    results = engine._backfill_rule_fallback_evidence(
        results=[_claim_result(["https://existing.com/1"])],
        evidence_pool=pool,
    )
    # Existing 1 + newly attached 3 = 4
    assert len(results[0].evidence) == 4
    assert "规则兜底" in (results[0].notes or "")


def test_backfill_skips_when_claim_already_has_two_attached():
    """If the rule engine already selected 2+ pieces of evidence we trust it.
    Adding more would inflate a well-judged claim with mediocre hits."""
    engine = VerdictEngine()
    pool = [
        _pool_item("https://a.com/x", tier="B", title="A"),
        _pool_item("https://b.com/y", tier="B", title="B"),
        _pool_item("https://c.com/z", tier="B", title="C"),
    ]
    original = _claim_result(["https://existing.com/1", "https://existing.com/2"])
    results = engine._backfill_rule_fallback_evidence(
        results=[original],
        evidence_pool=pool,
    )
    assert len(results[0].evidence) == 2
    assert "规则兜底" not in (results[0].notes or "")


def test_backfill_skips_when_pool_has_less_than_three_high_tier_hits():
    """Rescue is specifically 'pool has a lot but claim has almost none'.
    Two B-tier hits in the pool doesn't qualify."""
    engine = VerdictEngine()
    pool = [
        _pool_item("https://a.com/x", tier="B", title="A"),
        _pool_item("https://b.com/y", tier="B", title="B"),
        _pool_item("https://c.com/z", tier="C", title="C-tier"),
    ]
    results = engine._backfill_rule_fallback_evidence(
        results=[_claim_result([])],
        evidence_pool=pool,
    )
    assert len(results[0].evidence) == 0
    assert "规则兜底" not in (results[0].notes or "")


def test_backfill_prefers_higher_tier_when_available():
    """S/A must rank above B in the picked top-3."""
    engine = VerdictEngine()
    pool = [
        _pool_item("https://gov.cn/1", tier="S", title="官方通报"),
        _pool_item("https://xinhuanet.com/2", tier="A", title="新华 报道"),
        _pool_item("https://m.163.com/3", tier="B", title="163"),
        _pool_item("https://news.qq.com/4", tier="B", title="腾讯"),
    ]
    results = engine._backfill_rule_fallback_evidence(
        results=[_claim_result([])],
        evidence_pool=pool,
    )
    attached = results[0].evidence
    assert len(attached) == 3
    # Top-3 should include gov.cn (S) and xinhuanet.com (A) before either B.
    tiers = [ev.source_tier for ev in attached]
    assert "S" in tiers
    assert "A" in tiers


def test_backfill_skips_when_no_fact_claims():
    """Rescue only applies to fact claims; opinion/prediction/unverifiable
    claims are inherently non-decidable and shouldn't get backfilled."""
    engine = VerdictEngine()
    pool = [_pool_item(f"https://x.com/{i}", tier="B") for i in range(5)]
    opinion_claim = ClaimResult(
        claim="这真让人震惊。", claim_type="opinion",
        verdict="insufficient", confidence="low",
        evidence=[], notes="",
    )
    results = engine._backfill_rule_fallback_evidence(
        results=[opinion_claim],
        evidence_pool=pool,
    )
    assert len(results[0].evidence) == 0


def test_end_to_end_backfill_rescues_rule_path_verdict():
    """Integration path: run evaluate_with_source with a claim whose token
    match against the pool would fail — the pipeline should still surface
    the pool's top hits through the backfill safety net."""
    engine = VerdictEngine()
    bundle = RetrievalBundle(
        query="test query",
        matched_case_id="test",
        canonical_results=tuple([
            _hit("https://a.example.com/one", tier="B", title="foo bar baz alpha"),
            _hit("https://b.example.com/two", tier="B", title="foo bar baz beta"),
            _hit("https://c.example.com/three", tier="B", title="foo bar baz gamma"),
        ]),
        raw_results=tuple([]),
        provider_name="playwright",
    )
    verdict = engine.evaluate_with_source(
        request=AnalyzeRequest(raw_input="totally unrelated claim"),
        event=NormalizedEvent(
            title="disjoint", summary="disjoint",
            input_type="text_news", raw_input="disjoint",
        ),
        claims=[ClaimItem(claim="something quite different.", claim_type="fact")],
        retrieval_bundle=bundle,
    )
    main = verdict.claim_results[0]
    # Rule engine can't match any of the pool hits by anchors → attaches 0.
    # Backfill kicks in and appends the 3 B-tier items.
    assert len(main.evidence) >= 3
    assert "规则兜底" in (main.notes or "")
