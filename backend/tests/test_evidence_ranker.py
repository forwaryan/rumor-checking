"""Tests for the evidence ranker."""
from __future__ import annotations

from backend.app.services.evidence_ranker import rank_results, score_result
from backend.app.services.retrieval_models import SearchResult


def _hit(result_id: str, title: str, snippet: str, tier: str = "B") -> SearchResult:
    return SearchResult(
        case_id="real_search",
        query="q",
        result_id=result_id,
        title=title,
        url=f"https://example.com/{result_id}",
        source_name="example.com",
        published_at="2026-07-01",
        snippet=snippet,
        source_tier=tier,
    )


def test_score_higher_for_matching_content():
    query = "樊振东 国家队 回归"
    relevant = _hit("r1", "樊振东正式回归国家队", "中国乒乓球队宣布樊振东重返国家队备战", "A")
    irrelevant = _hit("r2", "天气预报", "明天北京多云转晴温度适宜", "B")
    assert score_result(relevant, query) > score_result(irrelevant, query)


def test_score_number_bonus():
    query = "拼多多 雄安 5000人"
    with_number = _hit("r1", "拼多多雄安招聘5000人", "拼多多计划在雄安新区招聘5000名员工", "B")
    without_number = _hit("r2", "拼多多雄安办公室", "拼多多在雄安设立了新的办公区域", "B")
    assert score_result(with_number, query) > score_result(without_number, query)


def test_rank_results_orders_by_relevance():
    query = "樊振东 国家队"
    r1 = _hit("r1", "樊振东回归国家队", "樊振东重返国家队训练基地", "B")
    r2 = _hit("r2", "今日新闻汇总", "各类体育新闻", "B")
    r3 = _hit("r3", "国家队名单公布", "最新国家队大名单包括樊振东", "A")

    ranked = rank_results([r2, r1, r3], query_text=query, event_title="樊振东回归")
    ids = [r.result_id for r in ranked]
    # r1 and r3 both highly relevant, r2 should be last
    assert ids[-1] == "r2"


def test_rank_results_respects_limit():
    results = [_hit(f"r{i}", f"title{i}", f"snippet{i}") for i in range(10)]
    ranked = rank_results(results, query_text="test", limit=5)
    assert len(ranked) == 5


def test_score_empty_query():
    r = _hit("r1", "test", "content")
    assert score_result(r, "") == 0.0
