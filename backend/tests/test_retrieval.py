from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from backend.app.core.config import get_settings
from backend.app.models.schemas import AnalyzeRequest, NormalizedEvent
from backend.app.services.analyze_pipeline import AnalyzePipeline
from backend.app.services.mock_retriever import MockRetriever
from backend.app.services.retrieval_cache import RetrievalCache
from backend.app.services.retrieval_models import RetrievalBundle, SearchResult
from backend.app.services.retrieval_provider import GdeltNewsProvider
from backend.app.services.retrieval_service import RetrievalService
from backend.app.services.timeline_builder import TimelineBuilder
from backend.tests.conftest import load_eval_fixture


RETRIEVAL_CASES = load_eval_fixture("retrieval_cases.json")


def _case_by_id(case_id: str):
    return next(item for item in RETRIEVAL_CASES if item["case_id"] == case_id)


def _event_for_case(case_id: str) -> NormalizedEvent:
    case = _case_by_id(case_id)
    input_type = "question_only" if case_id == "R03" else "text_news"
    return NormalizedEvent(
        summary=case["query"],
        keywords=[],
        input_type=input_type,
        raw_input=case["query"],
    )


def _make_result(
    *,
    result_id: str,
    title: str,
    snippet: str,
    published_at: str,
    source_name: str = "news.example.com",
    source_tier: str = "A",
    url: str | None = None,
) -> SearchResult:
    return SearchResult(
        case_id="real_search",
        query="??? ?? ??? ??",
        result_id=result_id,
        title=title,
        url=url or f"https://example.com/{result_id}",
        source_name=source_name,
        published_at=published_at,
        snippet=snippet,
        source_tier=source_tier,
    )


class FakeProvider:
    name = "gdelt"
    enabled = True

    def __init__(self, results=None, error: Exception | None = None):
        self._results = list(results or [])
        self._error = error
        self.calls: list[str] = []

    def search(self, query_text: str):
        self.calls.append(query_text)
        if self._error is not None:
            raise self._error
        return list(self._results)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_mock_retriever_normalizes_and_merges_results():
    case = _case_by_id("R01")
    bundle = MockRetriever().retrieve(case["query"])

    assert bundle.matched_case_id == "R01"
    assert bundle.related_result_count >= case["expected"]["min_related_results"]
    assert bundle.high_trust_result_count >= case["expected"]["min_high_trust_results"]

    canonical_ids = [item.result_id for item in bundle.canonical_results]
    assert "R01-2" in canonical_ids
    assert "R01-3" not in canonical_ids

    merged_report = next(item for item in bundle.canonical_results if item.result_id == "R01-2")
    assert merged_report.merged_result_ids == ("R01-3",)
    assert merged_report.merged_notes[0].startswith("R01-3:repost:")


@pytest.mark.parametrize("case_id", ["R01", "R02", "R03", "R04"])
def test_timeline_builder_uses_retrieval_candidates(case_id: str):
    case = _case_by_id(case_id)
    result_lookup = {item["result_id"]: item for item in case["mock_search_results"]}
    event = _event_for_case(case_id)
    retriever = MockRetriever()
    bundle = retriever.retrieve_for_event(event)
    timeline = TimelineBuilder().build(event, retrieval_bundle=bundle)

    assert timeline
    assert all(node.why_selected for node in timeline)

    expected_origin_id = case["expected"]["expected_origin_result_id"]
    if expected_origin_id is not None:
        origin_node = next(item for item in timeline if item.node_type == "origin")
        assert origin_node.url == result_lookup[expected_origin_id]["url"]

    expected_turn_id = case["expected"]["expected_turning_point_result_id"]
    if expected_turn_id is not None:
        expected_url = result_lookup[expected_turn_id]["url"]
        assert any(node.url == expected_url and node.node_type in {"turn", "clarification"} for node in timeline)


def test_gdelt_provider_normalizes_article_payload():
    settings = replace(get_settings(), retrieval_provider="gdelt")
    provider = GdeltNewsProvider(settings=settings)
    results = provider._parse_articles(
        "??? ?? ??? ??",
        {
            "articles": [
                {
                    "url": "https://www.news.cn/society/20260313/a1.htm",
                    "title": "??????????????????",
                    "seendate": "20260313T101500Z",
                    "domain": "news.cn",
                }
            ]
        },
    )

    assert len(results) == 1
    assert results[0].result_id == "gdelt-1"
    assert results[0].source_name == "news.cn"
    assert results[0].source_tier == "A"
    assert results[0].published_at.startswith("2026-03-13T10:15:00")


def test_gdelt_provider_search_uses_aligned_config(monkeypatch):
    captured = {}
    settings = replace(
        get_settings(),
        retrieval_provider="gdelt",
        retrieval_timeout_seconds=7.5,
        retrieval_max_results=3,
        retrieval_gdelt_base_url="https://example.test/gdelt",
    )
    provider = GdeltNewsProvider(settings=settings)

    def fake_get(url, *, params, timeout):
        captured["url"] = url
        captured["params"] = params
        captured["timeout"] = timeout
        return _FakeResponse(
            {
                "articles": [
                    {
                        "url": "https://news.cn/society/20260313/a1.htm",
                        "title": "??????????????????",
                        "seendate": "20260313T101500Z",
                        "domain": "news.cn",
                    }
                ]
            }
        )

    monkeypatch.setattr("backend.app.services.retrieval_provider.httpx.get", fake_get)
    results = provider.search("??? ?? ??? ??")

    assert len(results) == 1
    assert captured["url"] == "https://example.test/gdelt"
    assert captured["params"]["maxrecords"] == "3"
    assert captured["timeout"] == 7.5


def test_retrieval_cache_round_trip(tmp_path: Path):
    cache = RetrievalCache(cache_root=tmp_path, ttl_seconds=3600)
    bundle = RetrievalBundle(
        query="??? ?? ??? ??",
        matched_case_id="real_search",
        mode_hint="partial",
        raw_results=(
            _make_result(
                result_id="real-1",
                title="?????????",
                snippet="????????????",
                published_at="2026-03-13T10:00:00+08:00",
                source_name="news.cn",
            ),
        ),
        canonical_results=(
            _make_result(
                result_id="real-1",
                title="?????????",
                snippet="????????????",
                published_at="2026-03-13T10:00:00+08:00",
                source_name="news.cn",
            ),
        ),
    )

    cache.write(query_text=bundle.query, provider_name="gdelt", bundle=bundle)
    loaded = cache.read(query_text=bundle.query, provider_name="gdelt")

    assert loaded is not None
    assert loaded.query == bundle.query
    assert loaded.canonical_results[0].title == bundle.canonical_results[0].title


def test_retrieval_service_falls_back_to_mock_when_real_provider_fails(tmp_path: Path):
    event = _event_for_case("R01")
    service = RetrievalService(
        settings=replace(get_settings(), retrieval_fallback_to_mock=True),
        provider=FakeProvider(error=RuntimeError("network down")),
        cache=RetrievalCache(cache_root=tmp_path, ttl_seconds=3600),
    )

    bundle = service.retrieve_for_event(event)

    assert bundle.matched_case_id == "R01"
    assert bundle.canonical_results
    assert bundle.fallback_used is True
    assert bundle.fallback_reason == "real_retrieval_failed"


def test_retrieval_service_cache_only_mode_returns_empty_without_fallback(tmp_path: Path):
    event = _event_for_case("R01")
    service = RetrievalService(
        settings=replace(
            get_settings(),
            retrieval_provider="gdelt",
            retrieval_fallback_to_mock=False,
        ),
        provider=FakeProvider(
            results=[
                _make_result(
                    result_id="real-1",
                    title="?????????",
                    snippet="????????????",
                    published_at="2026-03-13T09:00:00+08:00",
                )
            ]
        ),
        cache=RetrievalCache(cache_root=tmp_path, ttl_seconds=3600),
    )

    bundle = service.retrieve_for_event(
        event,
        request_context={"retrieval_cache_only": True},
    )

    assert bundle.canonical_results == ()
    assert bundle.provider_name == "gdelt"
    assert bundle.fallback_reason == "retrieval_cache_only_miss"


def test_question_only_pipeline_uses_real_retrieval_bundle(tmp_path: Path):
    provider = FakeProvider(
        results=[
            _make_result(
                result_id="real-1",
                title="医院回应网传女网红脑出血去世：仍在救治",
                snippet="医院表示涉事当事人仍在救治，网传去世消息不实。",
                published_at="2026-03-13T09:00:00+08:00",
                source_name="news.cn",
                source_tier="A",
                url="https://news.cn/health/20260313/a1.htm",
            ),
            _make_result(
                result_id="real-2",
                title="警方辟谣女网红因熬夜脑出血死亡传闻",
                snippet="警方称相关死亡传闻系谣言，请勿继续传播。",
                published_at="2026-03-13T11:00:00+08:00",
                source_name="gov.cn",
                source_tier="S",
                url="https://www.gov.cn/xinwen/2026-03/13/content_1.htm",
            ),
        ]
    )
    pipeline = AnalyzePipeline()
    pipeline.provider_enricher.enrich = lambda event: (event, None)
    pipeline.retriever = RetrievalService(
        settings=replace(get_settings(), retrieval_provider="gdelt"),
        provider=provider,
        cache=RetrievalCache(cache_root=tmp_path, ttl_seconds=3600),
    )

    report = pipeline.analyze(
        AnalyzeRequest(
            raw_input="最近是不是有一个女网红因为熬夜脑出血死掉了？",
            input_type="question",
        )
    )

    assert provider.calls
    assert report.mode == "partial_mode"
    assert report.sources
    assert report.timeline
    assert report.claim_results[0].verdict == "refuted"
