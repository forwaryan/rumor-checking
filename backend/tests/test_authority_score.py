"""Continuous authority score covering the four signals we picked:

1. tier base — S/A/B/C get 40/32/20/10
2. whitelist bonus — TOP_TIER_DOMAINS or piyao adds +15
3. HTTPS + independent domain — +4 each (hosted blog platforms lose the domain bonus)
4. suspicious signals — sketchy TLD -8, advertorial URL -10, clickbait title -10

These are the invariants each band asserts. If you rewrite the score,
rewrite the tests too — same signal, same test.
"""
from __future__ import annotations

from backend.app.services.retrieval_provider import (
    _authority_score,
    infer_source_signals,
)


def test_tier_base_gives_the_anchor():
    # No URL/title signals kick in for a bare tier-C source with an obscure host.
    # It just gets the C anchor (10) + HTTPS (4) + independent-domain (4) = 18.
    assert _authority_score("https://weibo.com/xxx", "微博", "C", "") == 18.0

    # Same host on A tier: 32 + 4 + 4 = 40 (no whitelist hit — weibo.com isn't
    # in TOP_TIER_DOMAINS).
    assert _authority_score("https://weibo.com/xxx", "微博", "A", "") == 40.0


def test_whitelist_domain_adds_bonus():
    # xinhuanet.com is in TOP_TIER_DOMAINS → +15 whitelist on top of A base + HTTPS + indep.
    # 32 + 15 + 4 + 4 = 55
    assert _authority_score("https://www.xinhuanet.com/2026/x", "新华社", "A", "") == 55.0


def test_piyao_gets_the_whitelist_bonus():
    # piyao.org.cn is separately whitelisted (not in TOP_TIER_DOMAINS by name).
    # S tier: 40 + 15 + 4 + 4 = 63.
    assert _authority_score("https://www.piyao.org.cn/a/x", "辟谣", "S", "") == 63.0


def test_https_absence_costs_the_https_bonus():
    # HTTP instead of HTTPS: lose the +4 HTTPS bonus. B tier 20 + 4 (indep) = 24.
    assert _authority_score("http://example.cn/x", "example", "B", "") == 24.0


def test_hosted_blog_platform_loses_the_independent_domain_bonus():
    # medium.com is a hosted platform → skip the +4 independent-domain bonus.
    # B tier: 20 + 4 (HTTPS) + 0 (hosted) = 24.
    # (Note: the whitelist bonus does not apply — medium.com is not in TOP_TIER_DOMAINS.)
    assert _authority_score("https://foo.medium.com/x", "medium", "B", "") == 24.0


def test_suspicious_tld_deducts():
    # .top TLD on an unknown C source: 10 + 4 + 4 - 8 = 10.
    assert _authority_score("https://cheap-news.top/x", "cheap", "C", "") == 10.0


def test_advertorial_url_deducts():
    # /promotion/ segment marks paid content: -10 on top of the base.
    # A tier, HTTPS, independent, but advertorial: 32 + 4 + 4 - 10 = 30.
    assert _authority_score("https://portal.cn/promotion/abc", "portal", "A", "") == 30.0


def test_clickbait_title_deducts():
    # Title contains "震惊": -10 penalty. B tier with HTTPS + indep: 20 + 4 + 4 - 10 = 18.
    assert _authority_score("https://portal.cn/x", "portal", "B", "震惊！内幕曝光") == 18.0


def test_score_is_clamped_to_the_0_100_range():
    # Stack every penalty on a C-tier source: 10 + 4 (HTTPS but not indep) - 8 - 10 - 10 = -14
    # → clamped to 0.
    got = _authority_score(
        "https://foo.wordpress.com/promotion/x",
        "foo",
        "C",
        "震惊全网",
    )
    assert got == 0.0

    # Ceiling: an S-tier whitelisted piyao page can climb high but never past 100.
    got = _authority_score("https://www.piyao.org.cn/x", "piyao", "S", "官方通报")
    assert 0.0 <= got <= 100.0


def test_infer_source_signals_returns_both():
    tier, score = infer_source_signals("https://www.xinhuanet.com/x", "新华社", "国家发布")
    assert tier == "A"
    # 32 (A base) + 15 (whitelist) + 4 (HTTPS) + 4 (indep) = 55
    assert score == 55.0


def test_authority_score_orders_sources_within_a_tier():
    # Both are B-tier portal hits, but one is clickbait — authority_score must
    # separate them even though tier is identical.
    normal = _authority_score("https://portal.cn/x", "portal", "B", "公告：赛事信息")
    clickbait = _authority_score("https://portal.cn/x", "portal", "B", "震惊！全网疯传")
    assert normal > clickbait
    assert normal - clickbait == 10.0  # exactly one clickbait penalty
