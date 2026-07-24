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
from backend.app.services.retrieval_provider import GdeltNewsProvider, LlmWebSearchProvider
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
        self.status_code = 200

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


def test_llm_web_search_provider_runs_tool_loop_and_parses_results(monkeypatch):
    calls = []

    class _FakeResponse:
        def __init__(self, payload):
            self._payload = payload
            self.status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    responses = iter(
        [
            _FakeResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "tool-1",
                                        "type": "builtin_function",
                                        "function": {
                                            "name": "$web_search",
                                            "arguments": '{"search_result":{"search_id":"abc123"},"usage":{"total_tokens":7123}}',
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }
            ),
            _FakeResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": """
                                {
                                  "question": "最近有个女网红脑出血死了真的假的？",
                                  "verdict_hint": "现有公开来源更倾向于不实。",
                                  "results": [
                                    {
                                      "title": "医院回应网传女网红脑出血去世：仍在救治",
                                      "url": "https://news.cn/health/20260313/a1.htm",
                                      "source_name": "news.cn",
                                      "published_at": "2026-03-13",
                                      "snippet": "医院表示当事人仍在救治，网传去世消息不实。"
                                    },
                                    {
                                      "title": "警方辟谣女网红因脑出血死亡传闻",
                                      "url": "https://www.gov.cn/xinwen/2026-03/13/content_1.htm",
                                      "source_name": "gov.cn",
                                      "published_at": "2026-03-13T11:00:00+08:00",
                                      "snippet": "警方称相关死亡传闻系谣言，请勿继续传播。"
                                    },
                                    {
                                      "title": "示例占位链接，不应进入结果",
                                      "url": "https://example.com/fake",
                                      "source_name": "example.com",
                                      "published_at": null,
                                      "snippet": "placeholder"
                                    }
                                  ]
                                }
                                """,
                            }
                        }
                    ]
                }
            ),
        ]
    )

    def fake_post(url, headers, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return next(responses)

    monkeypatch.setattr("backend.app.services.retrieval_provider.httpx.post", fake_post)
    provider = LlmWebSearchProvider(
        settings=replace(
            get_settings(),
            retrieval_provider="kimi",
            llm_api_key="test-llm-key",
            llm_search_model="demo-search-model",
            retrieval_max_results=5,
        )
    )

    results = provider.search("最近有个女网红脑出血死了真的假的？")

    assert len(calls) == 2
    assert calls[0]["json"]["tools"] == [{"type": "builtin_function", "function": {"name": "$web_search"}}]
    second_messages = calls[1]["json"]["messages"]
    assert any(item.get("role") == "tool" and item.get("tool_call_id") == "tool-1" for item in second_messages)
    assert len(results) == 2
    assert results[0].title == "医院回应网传女网红脑出血去世：仍在救治"
    assert results[0].source_tier == "A"
    assert results[1].source_tier == "S"
    assert all("example.com" not in item.url for item in results)


def test_agent_retrieval_alias_uses_llm_web_search_provider(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_PROVIDER", "agent")
    monkeypatch.setenv("LLM_API_KEY", "test-llm-key")
    get_settings.cache_clear()

    settings = get_settings()
    service = RetrievalService(settings=settings)

    assert settings.retrieval_provider == "kimi"
    assert settings.uses_agent_retrieval is True
    assert settings.llm_required is True
    assert isinstance(service.provider, LlmWebSearchProvider)


def test_llm_web_search_provider_uses_configured_search_model_verbatim():
    provider = LlmWebSearchProvider(
        settings=replace(
            get_settings(),
            retrieval_provider="kimi",
            llm_api_key="test-llm-key",
            llm_search_model="demo-search-model",
        )
    )

    # Config decides the search model; no hard-coded rewrite.
    assert provider._search_model() == "demo-search-model"


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


def test_retrieval_service_builds_multi_query_bundle_with_independence_and_conflict_signals(tmp_path: Path):
    event = _event_for_case("R03")
    provider = FakeProvider(
        results=[
            _make_result(
                result_id="real-rumor",
                title="网传晨星生物将裁员40%",
                snippet="自媒体爆料称多个部门将裁员40%。",
                published_at="2026-03-05T08:00:00+08:00",
                source_name="职场爆料",
                source_tier="C",
                url="https://rumor.example.com/morningstar-1",
            ),
            _make_result(
                result_id="real-turn",
                title="晨星生物回应裁员传闻：没有40%裁员计划",
                snippet="公司回应称不存在所谓40%裁员安排。",
                published_at="2026-03-06T09:00:00+08:00",
                source_name="晨星生物",
                source_tier="S",
                url="https://ir.example.com/morningstar-response",
            ),
            _make_result(
                result_id="real-follow",
                title="证券时报：公司否认裁员40%",
                snippet="媒体跟进称交易所问询后公司否认相关传闻。",
                published_at="2026-03-06T12:00:00+08:00",
                source_name="证券时报",
                source_tier="A",
                url="https://finance.example.com/morningstar-followup",
            ),
        ]
    )
    service = RetrievalService(
        settings=replace(get_settings(), retrieval_provider="gdelt"),
        provider=provider,
        cache=RetrievalCache(cache_root=tmp_path, ttl_seconds=3600),
    )

    bundle = service.retrieve_for_event(event)

    assert 2 <= len(bundle.query_groups) <= 5
    assert bundle.independent_source_count >= 2
    assert "rumor_vs_response" in bundle.conflict_signals
    assert bundle.high_trust_result_count >= 2
    assert bundle.to_diagnostics().failure_detail is None


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


def test_retrieval_service_caches_each_query_group_separately(tmp_path: Path):
    event = _event_for_case("R01")
    provider = FakeProvider(
        results=[
            _make_result(
                result_id="real-1",
                title="海州市市场监管局通报海州新鲜屋整改情况",
                snippet="发现2批次酸奶超过保质期，涉事门店停业整改。",
                published_at="2026-03-01T09:00:00+08:00",
                source_name="海州市市场监管局",
                source_tier="S",
                url="https://gov.example.cn/hzsamr/2026-03-01",
            )
        ]
    )
    service = RetrievalService(
        settings=replace(get_settings(), retrieval_provider="gdelt"),
        provider=provider,
        cache=RetrievalCache(cache_root=tmp_path, ttl_seconds=3600),
    )

    first = service.retrieve_for_event(event)
    first_call_count = len(provider.calls)
    cached = service.retrieve_for_event(event, request_context={"retrieval_cache_only": True})

    cache_files = list((tmp_path / "gdelt").glob("*.json"))

    assert first_call_count == len(first.query_groups)
    assert len(cache_files) == len(first.query_groups)
    assert cached.canonical_results
    assert len(provider.calls) == first_call_count
    assert cached.cache_status in {"partial_hit", "hit", "mixed"}


def test_retrieval_service_filters_obviously_off_topic_canonical_hits(tmp_path: Path):
    event = NormalizedEvent(
        title="拼多多雄安新区招聘信息",
        summary="拼多多雄安新区招聘信息",
        keywords=[],
        input_type="text_news",
        raw_input="拼多多雄安新区招聘信息",
    )
    provider = FakeProvider(
        results=[
            _make_result(
                result_id="relevant-1",
                title="拼多多雄安公司员工数量超过600人",
                snippet="报道提到拼多多在雄安新区购置办公楼并持续招聘岗位。",
                published_at="2026-06-30T09:00:00+08:00",
                source_name="新浪财经",
                source_tier="B",
                url="https://finance.example.com/pdd-xiongan",
            ),
            _make_result(
                result_id="off-topic-1",
                title="河北赵县梨品类专项培训会现场",
                snippet="当地举行梨产业培训会，未提及雄安新区招聘。",
                published_at="2026-06-15T09:00:00+08:00",
                source_name="新民晚报新民网",
                source_tier="C",
                url="https://example.com/zhaoxian-pear",
            ),
        ]
    )
    service = RetrievalService(
        settings=replace(get_settings(), retrieval_provider="gdelt", retrieval_max_results=5),
        provider=provider,
        cache=RetrievalCache(cache_root=tmp_path, ttl_seconds=3600),
    )

    bundle = service.retrieve_for_event(event, request_context={"force_retrieval_query": "拼多多雄安新区招聘信息"})

    canonical_ids = {item.result_id for item in bundle.canonical_results}
    assert "relevant-1" in canonical_ids
    assert "off-topic-1" not in canonical_ids


def test_retrieval_service_drops_navigational_brand_homepage(tmp_path: Path):
    # A search for "拼多多雄安买楼" returns the pinduoduo homepage / batch platform,
    # which only match the brand term (拼多多) and none of the event terms
    # (雄安/购买/研发). These are navigational pages, not evidence — must be dropped,
    # while a real article about the event is kept.
    event = NormalizedEvent(
        title="拼多多在雄安买了三栋楼招了5000研发人员",
        summary="拼多多在雄安买了三栋楼招了5000研发人员",
        keywords=[],
        input_type="text_news",
        raw_input="拼多多在雄安买了三栋楼招了5000研发人员",
    )
    provider = FakeProvider(
        results=[
            _make_result(
                result_id="homepage",
                title="拼多多 新电商开创者",
                snippet="微信扫码免费领取拼多多店铺 联系我们 客服热线。",
                published_at="2026-07-20T09:00:00+08:00",
                source_name="www.pinduoduo.com",
                source_tier="C",
                url="https://www.pinduoduo.com/",
            ),
            _make_result(
                result_id="batch",
                title="拼多多批发 官方采购批发平台",
                snippet="拼多多官方旗下采购批发平台，采购就上拼多多批发。",
                published_at="2026-07-19T09:00:00+08:00",
                source_name="pifa.pinduoduo.com",
                source_tier="C",
                url="https://pifa.pinduoduo.com/",
            ),
            _make_result(
                result_id="real-article",
                title="拼多多在雄安设立研发中心并招聘5000人",
                snippet="拼多多宣布在雄安新区购置办公楼并招聘研发人员。",
                published_at="2026-07-21T09:00:00+08:00",
                source_name="finance.example.com",
                source_tier="B",
                url="https://finance.example.com/pdd-xiongan-rd",
            ),
        ]
    )
    service = RetrievalService(
        settings=replace(get_settings(), retrieval_provider="gdelt", retrieval_max_results=5),
        provider=provider,
        cache=RetrievalCache(cache_root=tmp_path, ttl_seconds=3600),
    )

    bundle = service.retrieve_for_event(
        event,
        request_context={"force_retrieval_query": "拼多多 雄安 购买 三栋楼 研发 5000 官方"},
    )

    canonical_ids = {item.result_id for item in bundle.canonical_results}
    assert "real-article" in canonical_ids
    assert "homepage" not in canonical_ids
    assert "batch" not in canonical_ids


def test_retrieval_service_returns_empty_when_all_results_are_navigational_junk(tmp_path: Path):
    # The exact failure mode from the pinduoduo trace: a search where EVERY hit is a
    # navigational brand page. Returning nothing is more honest than surfacing the
    # homepage as "evidence" — the old code fell back to the noise-stripped set and
    # let the homepage through when relevance filtering emptied the list.
    event = NormalizedEvent(
        title="拼多多在雄安买了三栋楼招了5000研发人员",
        summary="拼多多在雄安买了三栋楼招了5000研发人员",
        keywords=[],
        input_type="text_news",
        raw_input="拼多多在雄安买了三栋楼招了5000研发人员",
    )
    provider = FakeProvider(
        results=[
            _make_result(
                result_id="homepage",
                title="拼多多 新电商开创者",
                snippet="微信扫码免费领取拼多多店铺 联系我们 客服热线。",
                published_at="2026-07-20T09:00:00+08:00",
                source_name="www.pinduoduo.com",
                source_tier="C",
                url="https://www.pinduoduo.com/",
            ),
            _make_result(
                result_id="batch",
                title="拼多多批发 官方采购批发平台",
                snippet="拼多多官方旗下采购批发平台，采购就上拼多多批发。",
                published_at="2026-07-19T09:00:00+08:00",
                source_name="pifa.pinduoduo.com",
                source_tier="C",
                url="https://pifa.pinduoduo.com/",
            ),
        ]
    )
    service = RetrievalService(
        settings=replace(get_settings(), retrieval_provider="gdelt", retrieval_max_results=5),
        provider=provider,
        cache=RetrievalCache(cache_root=tmp_path, ttl_seconds=3600),
    )

    bundle = service.retrieve_for_event(
        event,
        request_context={"force_retrieval_query": "拼多多 雄安 购买 三栋楼 研发 5000 官方"},
    )

    assert bundle.canonical_results == ()
    assert bundle.mode_hint == "safe"


def test_retrieval_service_drops_lone_navigational_result(tmp_path: Path):
    # A single navigational page must NOT slip through: the old len==1 short-circuit
    # returned the sole result before the navigational check could drop it.
    event = NormalizedEvent(
        title="拼多多在雄安买了三栋楼招了5000研发人员",
        summary="拼多多在雄安买了三栋楼招了5000研发人员",
        keywords=[],
        input_type="text_news",
        raw_input="拼多多在雄安买了三栋楼招了5000研发人员",
    )
    provider = FakeProvider(
        results=[
            _make_result(
                result_id="homepage",
                title="拼多多 新电商开创者",
                snippet="微信扫码免费领取拼多多店铺 联系我们 客服热线。",
                published_at="2026-07-20T09:00:00+08:00",
                source_name="www.pinduoduo.com",
                source_tier="C",
                url="https://www.pinduoduo.com/",
            ),
        ]
    )
    service = RetrievalService(
        settings=replace(get_settings(), retrieval_provider="gdelt", retrieval_max_results=5),
        provider=provider,
        cache=RetrievalCache(cache_root=tmp_path, ttl_seconds=3600),
    )

    bundle = service.retrieve_for_event(
        event,
        request_context={"force_retrieval_query": "拼多多 雄安 购买 三栋楼 研发 5000 官方"},
    )

    assert bundle.canonical_results == ()


def test_retrieval_service_drops_brand_page_matching_only_a_generic_commerce_word(tmp_path: Path):
    # Real leak from the pinduoduo trace: the batch platform's snippet says
    # "办公采购", and the old bigram matcher counted the "办公" of the query's
    # 办公楼 as an event-topic match, so the brand page survived and inflated the
    # evidence grade. The event terms (雄安/研发/招聘) appear nowhere on the page,
    # so it must be dropped.
    event = NormalizedEvent(
        title="拼多多在雄安买了三栋楼招了5000研发人员",
        summary="拼多多在雄安买了三栋楼招了5000研发人员",
        keywords=[],
        input_type="text_news",
        raw_input="拼多多在雄安买了三栋楼招了5000研发人员",
    )
    provider = FakeProvider(
        results=[
            _make_result(
                result_id="batch",
                title="拼多多批发 - 拼多多官方采购批发平台，多多批发",
                snippet="拼多多官方旗下采购批发平台。提供好货好价的精选好货，满足货源采购、办公采购、企业购等诉求。",
                published_at="2026-07-19T09:00:00+08:00",
                source_name="pifa.pinduoduo.com",
                source_tier="C",
                url="https://pifa.pinduoduo.com/",
            ),
            _make_result(
                result_id="real-article",
                title="拼多多在雄安设立研发中心并招聘5000人",
                snippet="拼多多宣布在雄安新区购置办公楼并招聘研发人员。",
                published_at="2026-07-21T09:00:00+08:00",
                source_name="finance.example.com",
                source_tier="B",
                url="https://finance.example.com/pdd-xiongan-rd",
            ),
        ]
    )
    service = RetrievalService(
        settings=replace(get_settings(), retrieval_provider="gdelt", retrieval_max_results=5),
        provider=provider,
        cache=RetrievalCache(cache_root=tmp_path, ttl_seconds=3600),
    )

    bundle = service.retrieve_for_event(
        event,
        request_context={"force_retrieval_query": "拼多多 雄安 购买 办公楼 研发 招聘 官方"},
    )

    canonical_ids = {item.result_id for item in bundle.canonical_results}
    assert "batch" not in canonical_ids
    assert "real-article" in canonical_ids


def test_retrieval_service_publishes_caller_stage_key_to_providers(tmp_path: Path):
    # Regression for the trace stage_key collision: provider HTTP/LLM events used
    # to hardcode "retrieval_initial", so an investigation-round retrieval's events
    # landed in the wrong card. The service must publish the caller's stage_key so
    # providers tag their sub-events with it.
    from backend.app.services.progress import get_retrieval_stage_key

    seen_stage_keys: list = []

    class StageKeyProbeProvider:
        name = "gdelt"
        enabled = True

        def search(self, query_text: str):
            seen_stage_keys.append(get_retrieval_stage_key())
            return []

    event = NormalizedEvent(
        title="某事件",
        summary="某事件摘要",
        keywords=[],
        input_type="text_news",
        raw_input="某事件摘要",
    )
    service = RetrievalService(
        settings=replace(get_settings(), retrieval_provider="gdelt", retrieval_max_results=5),
        provider=StageKeyProbeProvider(),
        cache=RetrievalCache(cache_root=tmp_path, ttl_seconds=3600),
    )

    service.retrieve_for_event(
        event,
        request_context={
            "force_retrieval_query": "某事件 追加检索",
            "retrieval_stage_key": "investigation_retrieval",
        },
    )

    assert seen_stage_keys, "provider.search was never invoked"
    assert all(key == "investigation_retrieval" for key in seen_stage_keys)
    # And the contextvar is reset once retrieval returns (no leakage).
    assert get_retrieval_stage_key() is None


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
            raw_input="最近是不是有一个女网红因为熬夜脑出血去世了？",
            input_type="question",
        )
    )

    assert len(provider.calls) >= 4
    assert len(set(provider.calls)) >= 2
    assert any("gov" in call or "官方" in call for call in provider.calls)
    assert report.mode == "partial_mode"
    assert report.sources
    assert report.timeline
    assert report.claim_results[0].verdict == "refuted"
    assert report.provenance.source_type == "backend_live"
    assert report.provenance.event_source == "retrieval_resolved"
    assert report.provenance.evidence_source == "retrieval_live"
    assert report.provenance.timeline_source == "retrieval"
    assert report.provenance.fallback_used is False


def test_llm_question_retrieval_keeps_raw_rumor_phrasing(tmp_path: Path):
    class LlmLikeProvider(FakeProvider):
        name = "kimi"

    provider = LlmLikeProvider(
        results=[
            _make_result(
                result_id="real-1",
                title="医院回应网传女网红脑出血去世：仍在救治",
                snippet="医院表示当事人仍在救治，网传去世消息不实。",
                published_at="2026-03-13T09:00:00+08:00",
                source_name="news.cn",
                source_tier="A",
                url="https://news.cn/health/20260313/a1.htm",
            ),
            _make_result(
                result_id="real-2",
                title="警方辟谣女网红因脑出血死亡传闻",
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
        settings=replace(get_settings(), retrieval_provider="kimi"),
        provider=provider,
        cache=RetrievalCache(cache_root=tmp_path, ttl_seconds=3600),
    )

    report = pipeline.analyze(
        AnalyzeRequest(
            raw_input="最近有个女网红脑出血死了真的假的？",
            input_type="question",
        )
    )

    assert "最近有个女网红脑出血死了真的假的" in provider.calls
    assert len(provider.calls) >= 4
    assert report.mode == "partial_mode"
    assert report.event.title in {
        "医院回应网传女网红脑出血去世：仍在救治",
        "警方辟谣女网红因脑出血死亡传闻",
    }
    assert report.sources
    assert report.provenance.evidence_source == "retrieval_live"
    assert report.provenance.retrieval_provider == "kimi"

def test_safe_mode_keeps_raw_retrieval_hits_visible(tmp_path: Path):
    provider = FakeProvider(
        results=[
            _make_result(
                result_id="real-1",
                title="unrelated entertainment roundup",
                snippet="a general entertainment digest without a matching subject",
                published_at="2026-03-13T09:00:00+08:00",
                source_name="portal.example.com",
                source_tier="B",
                url="https://example.com/raw-hit-1",
            ),
            _make_result(
                result_id="real-2",
                title="regional blog discusses another creator rumor",
                snippet="mentions a creator rumor but does not confirm the same person or event",
                published_at="2026-03-13T10:00:00+08:00",
                source_name="blog.example.com",
                source_tier="C",
                url="https://example.com/raw-hit-2",
            ),
            _make_result(
                result_id="real-3",
                title="official hospital bulletin about another patient",
                snippet="mentions a hospital bulletin but not the same influencer or case",
                published_at="2026-03-13T11:00:00+08:00",
                source_name="hospital.example.com",
                source_tier="A",
                url="https://example.com/raw-hit-3",
            ),
        ]
    )
    pipeline = AnalyzePipeline()
    pipeline.provider_enricher.enrich = lambda event: (event, None)
    pipeline.retriever = RetrievalService(
        settings=replace(get_settings(), retrieval_provider="gdelt", retrieval_fallback_to_mock=False),
        provider=provider,
        cache=RetrievalCache(cache_root=tmp_path, ttl_seconds=3600),
    )

    report = pipeline.analyze(
        AnalyzeRequest(
            raw_input="did a female influencer die from cerebral hemorrhage",
            input_type="question",
        )
    )

    assert report.mode == "safe_mode"
    assert report.retrieval_hits
    assert report.retrieval_diagnostics is not None
    assert report.retrieval_diagnostics.query
    assert "female influencer" in report.retrieval_diagnostics.query
    assert report.retrieval_diagnostics.canonical_result_count == 3
    assert report.retrieval_hits[0].url == "https://example.com/raw-hit-3"
    assert report.retrieval_hits[1].url == "https://example.com/raw-hit-2"
    assert report.retrieval_hits[2].url == "https://example.com/raw-hit-1"

def test_pipeline_marks_mock_provenance_when_real_retrieval_falls_back_to_mock(tmp_path: Path):
    pipeline = AnalyzePipeline()
    pipeline.provider_enricher.enrich = lambda event: (event, None)
    pipeline.retriever = RetrievalService(
        settings=replace(get_settings(), retrieval_provider="gdelt", retrieval_fallback_to_mock=True),
        provider=FakeProvider(error=RuntimeError("network down")),
        cache=RetrievalCache(cache_root=tmp_path, ttl_seconds=3600),
    )

    report = pipeline.analyze(
        AnalyzeRequest(
            raw_input="【海州市市场监管局通报】2026年3月1日，海州市市场监管局发布通报称，在例行抽检中发现海州新鲜屋连锁门店有2批次酸奶超过保质期，涉事门店已停业整改。",
            input_type="text",
        )
    )

    assert report.sources
    assert report.provenance.source_type == "backend_mock"
    assert report.provenance.evidence_source == "retrieval_mock"
    assert report.provenance.fallback_used is True
    assert "real_retrieval_failed" in report.provenance.fallback_reasons


def test_pipeline_without_evidence_stays_safe_and_exposes_none_provenance(tmp_path: Path):
    pipeline = AnalyzePipeline()
    pipeline.provider_enricher.enrich = lambda event: (event, None)
    pipeline.retriever = RetrievalService(
        settings=replace(get_settings(), retrieval_provider="gdelt", retrieval_fallback_to_mock=False),
        provider=FakeProvider(results=[]),
        cache=RetrievalCache(cache_root=tmp_path, ttl_seconds=3600),
    )

    report = pipeline.analyze(
        AnalyzeRequest(
            raw_input="网传某地今晚会出现不明爆炸，但没有给出地点和来源。",
            input_type="text",
        )
    )

    assert report.mode == "safe_mode"
    assert report.sources == []
    assert all(item.verdict == "insufficient" for item in report.claim_results if item.claim_type == "fact")
    assert report.provenance.source_type == "backend_live"
    assert report.provenance.event_source == "input_normalized"
    assert report.provenance.evidence_source == "none"
    assert report.provenance.timeline_source == "input_seed"

def test_retrieval_service_skip_cache_alias_bypasses_cached_bundle(tmp_path: Path):
    event = _event_for_case("R01")
    provider = FakeProvider(
        results=[
            _make_result(
                result_id="real-1",
                title="棣栬疆瀹炴椂妫€绱㈢粨鏋?",
                snippet="绗竴杞繑鍥炵殑鍏紑鏉ユ簮缁撴灉銆?",
                published_at="2026-03-13T09:00:00+08:00",
                url="https://example.com/live-1",
            )
        ]
    )
    service = RetrievalService(
        settings=replace(get_settings(), retrieval_provider="gdelt"),
        provider=provider,
        cache=RetrievalCache(cache_root=tmp_path, ttl_seconds=3600),
    )

    first = service.retrieve_for_event(event)
    provider._results = [
        _make_result(
            result_id="real-2",
            title="璺宠繃缂撳瓨鍚庣殑鏂扮粨鏋?",
            snippet="杩欐槸缁曡繃缂撳瓨鍚庢嬁鍒扮殑鏂拌繑鍥炪€?",
            published_at="2026-03-13T10:00:00+08:00",
            url="https://example.com/live-2",
        )
    ]
    bypassed = service.retrieve_for_event(event, request_context={"skip_retrieval_cache": True})
    cached = service.retrieve_for_event(event)

    per_run_call_count = len(first.query_groups)
    assert first.canonical_results[0].result_id == "real-1"
    assert bypassed.canonical_results[0].result_id == "real-2"
    assert bypassed.cache_status == "bypassed"
    assert cached.canonical_results[0].result_id == "real-1"
    assert len(provider.calls) == per_run_call_count * 2


def test_timeline_builder_selects_key_nodes_from_real_bundle():
    event = NormalizedEvent(
        summary="晨星生物 裁员40% 传闻",
        keywords=["晨星生物", "裁员", "传闻"],
        input_type="text_news",
        raw_input="晨星生物 裁员40% 传闻",
    )
    results = (
        _make_result(
            result_id="real-rumor",
            title="网传晨星生物将裁员40%",
            snippet="自媒体爆料称多个部门将裁员40%。",
            published_at="2026-03-05T08:00:00+08:00",
            source_name="职场爆料",
            source_tier="C",
            url="https://example.com/rumor",
        ),
        _make_result(
            result_id="real-amplify",
            title="多家平台转发晨星生物裁员传闻",
            snippet="传闻持续发酵，多个聚合页跟进转载。",
            published_at="2026-03-05T12:00:00+08:00",
            source_name="聚合快讯",
            source_tier="B",
            url="https://example.com/amplify",
        ),
        _make_result(
            result_id="real-turn",
            title="晨星生物回应裁员传闻：没有40%裁员计划",
            snippet="公司回应称不存在所谓40%裁员安排。",
            published_at="2026-03-06T09:00:00+08:00",
            source_name="证券时报",
            source_tier="A",
            url="https://example.com/response",
        ),
        _make_result(
            result_id="real-clarification",
            title="晨星生物发布情况说明",
            snippet="公司补充说明业务调整和人员安排，没有大规模裁员。",
            published_at="2026-03-06T18:00:00+08:00",
            source_name="晨星生物",
            source_tier="S",
            url="https://example.com/clarification",
        ),
    )
    bundle = RetrievalBundle(
        query="晨星生物 裁员40% 传闻",
        matched_case_id="real_search",
        mode_hint="partial",
        raw_results=results,
        canonical_results=results,
        provider_name="gdelt",
    )

    timeline_build = TimelineBuilder().build_with_source(event, retrieval_bundle=bundle)
    nodes = {item.node_type: item for item in timeline_build.nodes}

    assert {"origin", "amplification", "turn", "clarification"}.issubset(nodes)
    assert nodes["origin"].url == "https://example.com/rumor"
    assert "起点" in nodes["origin"].why_selected or "最早" in nodes["origin"].why_selected
    assert nodes["amplification"].url == "https://example.com/amplify"
    assert "扩散" in nodes["amplification"].why_selected
    assert nodes["turn"].url == "https://example.com/response"
    assert "回应" in nodes["turn"].why_selected or "转折" in nodes["turn"].why_selected
    assert nodes["clarification"].url == "https://example.com/clarification"
    assert "说明" in nodes["clarification"].why_selected or "澄清" in nodes["clarification"].why_selected
    assert timeline_build.completeness >= 80
    assert timeline_build.confidence >= 60


def test_timeline_origin_prefers_dated_result_over_undated():
    # Regression (codex review P2): an undated hit must not masquerade as the
    # earliest event. A mixed bundle with one undated rumor and one dated rumor
    # should anchor the origin on the dated one, not the undated one.
    event = NormalizedEvent(
        summary="晨星生物 裁员40% 传闻",
        keywords=["晨星生物", "裁员", "传闻"],
        input_type="text_news",
        raw_input="晨星生物 裁员40% 传闻",
    )
    results = (
        _make_result(
            result_id="undated-rumor",
            title="网传晨星生物将裁员40%",
            snippet="有网民发帖称晨星生物多个部门将裁员40%。",
            published_at=None,
            source_name="观察者网",
            source_tier="C",
            url="https://example.com/undated-rumor",
        ),
        _make_result(
            result_id="dated-rumor",
            title="网传晨星生物将裁员40%引发关注",
            snippet="有帖子称晨星生物裁员40%，网上持续发酵。",
            published_at="2026-03-05T08:00:00+08:00",
            source_name="晨星观察",
            source_tier="C",
            url="https://example.com/dated-rumor",
        ),
    )
    bundle = RetrievalBundle(
        query="晨星生物 裁员40% 传闻",
        matched_case_id="real_search",
        mode_hint="partial",
        raw_results=results,
        canonical_results=results,
        provider_name="playwright",
    )

    timeline_build = TimelineBuilder().build_with_source(event, retrieval_bundle=bundle)
    origin = next((node for node in timeline_build.nodes if node.node_type == "origin"), None)
    assert origin is not None
    assert origin.url == "https://example.com/dated-rumor"


def test_timeline_builder_scores_frozen_propagation_cases():
    builder = TimelineBuilder()
    retriever = MockRetriever()

    for case_id in ("R01", "R03"):
        event = _event_for_case(case_id)
        bundle = retriever.retrieve_for_event(event)
        timeline_build = builder.build_with_source(event, retrieval_bundle=bundle)

        assert timeline_build.source == "retrieval"
        assert timeline_build.nodes
        assert timeline_build.completeness >= 60
        assert timeline_build.confidence >= 50


def test_question_only_resolution_stays_unresolved_without_high_trust_results():
    event = NormalizedEvent(
        summary="generic rumor claim",
        keywords=[],
        input_type="question_only",
        raw_input="is there a vague viral rumor",
    )
    bundle = RetrievalBundle(
        query="generic rumor",
        canonical_results=(
            _make_result(
                result_id="low-1",
                title="forum users discuss another topic",
                snippet="no clear entity matches the question",
                published_at="2026-03-13T09:00:00+08:00",
                source_tier="C",
            ),
            _make_result(
                result_id="low-2",
                title="aggregator repost without details",
                snippet="still no stable source or named subject",
                published_at="2026-03-13T10:00:00+08:00",
                source_tier="B",
            ),
        ),
    )

    resolution = AnalyzePipeline().question_resolver.resolve(event=event, retrieval_bundle=bundle)

    assert resolution.selected_result is None
    assert resolution.follow_up_query is None
    assert resolution.event.summary == event.summary


def test_question_query_rewrite_preserves_core_rumor_terms():
    service = RetrievalService()
    query = service._rewrite_question_query("最近有个女网红脑出血死了真的假的？")

    assert "女网红" in query
    assert "脑出血" in query
    assert "死亡" in query


def test_question_query_rewrite_collapses_broad_trend_question_to_topic():
    service = RetrievalService()

    assert service._rewrite_question_query("最近是不是有裁员") == "裁员"


def test_question_only_pipeline_rejects_partial_subject_match_candidates(tmp_path: Path):
    provider = FakeProvider(
        results=[
            _make_result(
                result_id="real-1",
                title="晨星回应裁员传闻",
                snippet="Morningstar 表示正在评估组织调整，但没有确认与用户提问的是同一家公司。",
                published_at="2026-03-13T09:00:00+08:00",
                source_name="Morningstar",
                source_tier="S",
                url="https://morningstar.example.com/layoff",
            ),
            _make_result(
                result_id="real-2",
                title="生物医药行业 2024 年持续裁员",
                snippet="行业观察提到多家生物公司出现裁员，但没有点名晨星生物。",
                published_at="2026-03-13T10:00:00+08:00",
                source_name="行业周刊",
                source_tier="A",
                url="https://industry.example.com/biotech-layoffs",
            ),
        ]
    )
    pipeline = AnalyzePipeline()
    pipeline.provider_enricher.enrich = lambda event: (event, None)
    pipeline.retriever = RetrievalService(
        settings=replace(get_settings(), retrieval_provider="gdelt", retrieval_fallback_to_mock=False),
        provider=provider,
        cache=RetrievalCache(cache_root=tmp_path, ttl_seconds=3600),
    )

    report = pipeline.analyze(
        AnalyzeRequest(
            raw_input="晨星生物是不是裁员了？",
            input_type="question",
        )
    )

    assert len(provider.calls) >= 1
    assert report.mode == "safe_mode"
    assert report.provenance.event_source == "input_normalized"
    assert report.provenance.evidence_source == "retrieval_live"
    assert all(item.verdict == "insufficient" for item in report.claim_results if item.claim_type == "fact")
    assert report.retrieval_hits
    assert "Morningstar" not in report.event.title
    assert "不能证明原句说的就是其中哪一个" in report.investigation.final_conclusion


def test_question_only_pipeline_keeps_exact_entity_matches_resolvable(tmp_path: Path):
    provider = FakeProvider(
        results=[
            _make_result(
                result_id="real-1",
                title="Morningstar 回应深圳团队裁员旧闻",
                snippet="Morningstar 表示相关组织调整发生于旧批次，不代表新的大规模裁员计划。",
                published_at="2026-03-13T09:00:00+08:00",
                source_name="Morningstar",
                source_tier="S",
                url="https://morningstar.example.com/shenzhen-layoff",
            ),
            _make_result(
                result_id="real-2",
                title="媒体跟进 Morningstar 裁员旧闻",
                snippet="财经媒体梳理了 Morningstar 过往的深圳团队调整背景。",
                published_at="2026-03-13T11:00:00+08:00",
                source_name="证券时报",
                source_tier="A",
                url="https://finance.example.com/morningstar-followup",
            ),
        ]
    )
    pipeline = AnalyzePipeline()
    pipeline.provider_enricher.enrich = lambda event: (event, None)
    pipeline.retriever = RetrievalService(
        settings=replace(get_settings(), retrieval_provider="gdelt", retrieval_fallback_to_mock=False),
        provider=provider,
        cache=RetrievalCache(cache_root=tmp_path, ttl_seconds=3600),
    )

    report = pipeline.analyze(
        AnalyzeRequest(
            raw_input="Morningstar 裁员是真的吗？",
            input_type="question",
        )
    )

    assert len(provider.calls) >= 4
    assert report.provenance.event_source == "retrieval_resolved"
    assert report.retrieval_hits


def test_question_only_pipeline_answers_broad_trend_questions_without_forcing_single_event(tmp_path: Path):
    provider = FakeProvider(
        results=[
            _make_result(
                result_id="trend-1",
                title="Meta 启动新一轮裁员调整",
                snippet="公司确认多个团队出现岗位优化和裁员安排。",
                published_at="2026-03-13T09:00:00+08:00",
                source_name="Reuters",
                source_tier="A",
                url="https://reuters.example.com/meta-layoff",
            ),
            _make_result(
                result_id="trend-2",
                title="亚马逊宣布部分业务继续裁员",
                snippet="亚马逊在最新组织调整中继续削减相关岗位。",
                published_at="2026-03-13T11:00:00+08:00",
                source_name="news.cn",
                source_tier="A",
                url="https://news.example.com/amazon-layoff",
            ),
        ]
    )
    pipeline = AnalyzePipeline()
    pipeline.provider_enricher.enrich = lambda event: (event, None)
    pipeline.retriever = RetrievalService(
        settings=replace(get_settings(), retrieval_provider="gdelt", retrieval_fallback_to_mock=False),
        provider=provider,
        cache=RetrievalCache(cache_root=tmp_path, ttl_seconds=3600),
    )

    report = pipeline.analyze(
        AnalyzeRequest(
            raw_input="最近是不是有裁员",
            input_type="question",
        )
    )

    assert 1 <= len(provider.calls) <= 2
    assert "裁员" in provider.calls
    assert report.mode == "partial_mode"
    assert report.provenance.event_source == "input_normalized"
    assert report.provenance.evidence_source == "retrieval_live"
    assert report.retrieval_hits
    assert any(item.verdict == "supported" for item in report.claim_results)
    assert "最近确实有裁员相关消息" in report.final_summary
    assert "不是单一事件" in report.investigation.final_conclusion
    assert any("不是单一事件" in item.answer for item in report.content_check.possible_answers)
    question_resolution_step = next(step for step in report.pipeline_trace.steps if step.stage_key == "question_resolution")
    assert "范围型问句" in question_resolution_step.summary

