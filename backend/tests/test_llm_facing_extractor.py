from __future__ import annotations

from backend.app.services.llm_facing_extractor import (
    compare_extractors,
    extract_main_text,
)
from backend.app.services.page_fetcher import _extract_key_paragraphs, _strip_tags


def _baseline(html: str) -> str:
    """The current production extraction: strip tags, then newline-split +
    digit/length paragraph scoring."""
    return _extract_key_paragraphs(_strip_tags(html))


# An article page whose navigation column is long, digit-laden, and link-heavy —
# exactly what the baseline's "contains digits + length" scorer over-ranks, and
# what link-density pruning is designed to drop.
_ARTICLE_WITH_NAV = """
<html><body>
<nav>
  <a href="/1">2024年最新政策解读汇总 第 1 期 共 30 期</a>
  <a href="/2">2023年度经济数据回顾 GDP 增长 5.2% 全年报告</a>
  <a href="/3">往期精选 100 篇 点击查看更多内容 立即订阅</a>
</nav>
<article>
  <h1>某市地铁票价维持不变</h1>
  <p>某市交通委今日通报，全市地铁执行 2 元起步价，全程最高 9 元，价格保持不变，网传上涨至 10 元的消息不属实。</p>
  <p>交通委强调，任何票价调整都会提前向社会公示，市民不必轻信未经证实的传言。</p>
</article>
<footer><a href="/x">版权所有 2024 联系我们 关于我们 友情链接</a></footer>
</body></html>
"""

# A clean article with no boilerplate — both extractors should handle it.
_CLEAN_ARTICLE = """
<html><body><article>
<p>国务院正式印发碳中和实施方案，明确到 2030 年实现相关阶段性目标，各部委将陆续发布配套细则。</p>
</article></body></html>
"""


def test_structural_extractor_drops_link_heavy_navigation():
    body = extract_main_text(_ARTICLE_WITH_NAV)
    # The article body must survive.
    assert "地铁执行" in body
    assert "价格保持不变" in body
    # The link-heavy nav / footer boilerplate must NOT.
    assert "往期精选" not in body
    assert "友情链接" not in body


def test_structural_extractor_handles_clean_article():
    body = extract_main_text(_CLEAN_ARTICLE)
    assert "碳中和实施方案" in body


def test_extractor_returns_empty_on_garbage_without_raising():
    # Malformed / bodyless input degrades to empty, never raises.
    assert extract_main_text("<not-html><<<") == ""
    assert extract_main_text("") == ""


def test_poc_comparison_reports_metrics_and_candidate_is_cleaner():
    """The PoC comparison must produce the decision metrics for both extractors,
    and the structure-aware candidate must keep boilerplate out better than the
    baseline — the dimension that justifies it."""
    samples = [
        (_ARTICLE_WITH_NAV, ["地铁", "票价", "9 元"], ["往期精选", "友情链接", "GDP 增长"]),
        (_CLEAN_ARTICLE, ["碳中和", "2030"], []),
    ]
    scores = compare_extractors(samples, baseline_fn=_baseline)

    assert set(scores) == {"baseline", "candidate"}
    for score in scores.values():
        assert 0.0 <= score.effective_body_rate <= 1.0
        assert 0.0 <= score.citation_locatability <= 1.0
        assert 0.0 <= score.boilerplate_free_rate <= 1.0
        assert score.latency_ms >= 0.0
        assert score.body_samples == 2

    # The structural extractor must leak strictly less boilerplate than the
    # baseline — this is the whole reason to consider it.
    assert scores["candidate"].boilerplate_free_rate > scores["baseline"].boilerplate_free_rate
