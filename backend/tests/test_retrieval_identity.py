"""Regression cases for independent evidence surviving multi-query dedup."""
from dataclasses import replace

import pytest

from backend.app.services.retrieval_deduper import merge_search_results
from backend.app.services.retrieval_models import SearchResult
from backend.app.services.retrieval_url import retrieval_url_identity


def hit(result_id="a", **kwargs):
    return replace(SearchResult(
        case_id="test", query="q", result_id=result_id,
        title="甲企业正式声明", url="https://example.org/News",
        source_name="Example", published_at="2026-09-01",
        snippet="公司表示相关情况属实。", source_tier="A",
    ), **kwargs)


@pytest.mark.parametrize("left,right", [
    ("https://EXAMPLE.org:443/a", "https://example.org/a"),
    ("https://example.org", "https://example.org/"),
    ("https://example.org/a?utm_source=web&id=1&fbclid=x", "https://example.org/a?id=1"),
    ("https://example.org/a#paragraph-2", "https://example.org/a"),
])
def test_safe_aliases_share_identity_without_changing_url(left, right):
    assert retrieval_url_identity(left) == retrieval_url_identity(right)
    results = merge_search_results([hit(url=left), hit("b", url=right, title="更新的标题")])
    assert len(results) == 1
    assert results[0].url in {left, right}


@pytest.mark.parametrize("left,right", [
    ("https://example.org/News", "https://example.org/news"),
    ("https://example.org/a?id=1", "https://example.org/a?id=2"),
    ("https://example.org/a?q=News", "https://example.org/a?q=news"),
    ("https://example.org/a?id=1&id=2", "https://example.org/a?id=2&id=1"),
    ("https://example.org/a?a=1&b=2", "https://example.org/a?b=2&a=1"),
    ("https://example.org/a?blank=", "https://example.org/a"),
    ("https://example.org/#/article/1", "https://example.org/#/article/2"),
    ("https://example.org/#!/article/1", "https://example.org/#!/article/2"),
    ("https://example.org/#article=1", "https://example.org/#article=2"),
    ("http://example.org/a", "https://example.org/a"),
])
def test_distinct_pages_preserve_evidence(left, right):
    assert retrieval_url_identity(left) != retrieval_url_identity(right)
    results = merge_search_results([hit(url=left), hit("b", url=right, snippet="公司表示相关情况不实。")])
    assert len(results) == 2


@pytest.mark.parametrize("url", ["", " ", "not-a-url", "https://[", "https://example.org:invalid/a",
                                    "https://example.org/a b", "https://user:password@example.org/a",
                                    "https://%zz/a", "https://example.org/%zz"])
def test_empty_or_invalid_urls_never_merge_unrelated_articles(url):
    assert retrieval_url_identity(url) is None
    assert len(merge_search_results([hit(url=url), hit("b", url=url, title="乙机构独立调查")])) == 2


def test_colliding_ids_do_not_prevent_true_alias_dedup():
    results = merge_search_results([hit(), hit(url="https://example.org/News?utm_source=search")])
    assert len(results) == 1
    assert results[0].merged_result_ids == ()  # Never manufacture a self-reference.
    assert len(results[0].merged_notes) == 1


def test_ambiguous_duplicate_reference_cannot_merge_three_independent_articles():
    results = merge_search_results([
        hit(), hit(url="https://other.org/b", title="乙机构独立调查"),
        hit("c", url="https://third.org/c", title="丙公司年度财报", duplicate_of="a"),
    ])
    assert len(results) == 3


def test_unambiguous_explicit_repost_reference_still_merges():
    results = merge_search_results([hit(), hit("b", title="转载：声明", url="https://other.org/b", duplicate_of="a")])
    assert len(results) == 1
    assert results[0].merged_result_ids == ("b",)


@pytest.mark.parametrize("snippet", ["", "点击查看全文", "公司表示相关情况不实。"])
def test_same_title_without_matching_substantive_content_preserves_both_sources(snippet):
    assert len(merge_search_results([hit(), hit("b", url="https://other.org/b", snippet=snippet)])) == 2


def test_matching_substantive_repost_content_merges_with_provenance_retained():
    snippet = "市场监督管理部门已完成现场调查，公布抽检结果及后续整改安排，并要求经营单位公开复检情况。"
    original = hit(snippet=snippet)
    repost = hit("b", title="转载：甲企业正式声明", url="https://other.org/b", snippet=snippet)
    merged = merge_search_results([original, repost])
    assert len(merged) == 1
    again = merge_search_results([*merged, hit("c", url="https://example.org/News?gclid=x")])
    assert set(again[0].merged_result_ids) == {"b", "c"}
    assert merge_search_results(again)[0].merged_result_ids == again[0].merged_result_ids


def test_near_titles_with_conflicting_numbers_cannot_merge():
    first = hit(title="企业 招聘 计划 官方 发布 5000人", snippet="招聘人数为5000人。")
    second = hit("b", title="企业 招聘 计划 官方 发布 1000人", url="https://other.org/b", snippet="招聘人数为1000人。")
    assert len(merge_search_results([first, second])) == 2


@pytest.mark.parametrize("left,right", [
    ("企业利润增长 10%", "企业利润增长 -10%"),
    ("企业利润增长 1.5%", "企业利润增长 15%"),
    ("企业利润增长 10%", "企业利润增长 10‰"),
    ("企业利润增长 10%", "企业利润增长 10"),
    ("中国某知名企业公布最新年度财务报表显示净利润同比增长5000万元",
     "中国某知名企业公布最新年度财务报表显示净利润同比增长1000万元"),
    ("中国某知名企业公布最新年度财务报表显示净利润同比增长10%",
     "中国某知名企业公布最新年度财务报表显示净利润未同比增长10%"),
])
def test_background_snippet_cannot_hide_conflicting_quantitative_headlines(left, right):
    background = "该公司于周三正式发布了年度财务报告，报告包含营业收入、净利润以及对下一年度经营计划的详细说明。"
    assert len(merge_search_results([
        hit(title=left, snippet=background),
        hit("b", title=right, snippet=background, url="https://other.org/b"),
    ])) == 2


def test_invalid_ipv6_url_cannot_crash_retrieval_filtering():
    from backend.app.services.retrieval_service import RetrievalService

    result = hit(url="https://[broken")
    assert result.is_navigational
    assert RetrievalService()._filter_relevant_results([result]) == []
