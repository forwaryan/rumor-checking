from __future__ import annotations

import backend.app.services.llm_provider as llm_provider_module

from backend.app.api.v1.endpoints import analyze as analyze_endpoint
from backend.app.core.config import get_settings
from backend.app.models.schemas import ClaimItem, NormalizedEvent, ProviderAnalysis, ProviderEventDraft
from backend.app.services.analyze_pipeline import AnalyzePipeline
from backend.app.services.llm_provider import LlmStructuredProvider
from backend.app.services.provider_enricher import ProviderEnricher
from backend.tests.conftest import load_eval_fixture


class _DummyResponse:
    def __init__(self, content: str) -> None:
        self._content = content
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def _quality_case(case_id: str):
    cases = load_eval_fixture("provider_text_news_cases.json")
    return next(item for item in cases if item["case_id"] == case_id)


def test_provider_text_news_acceptance_fixture_has_expected_coverage():
    cases = load_eval_fixture("provider_text_news_cases.json")
    assert 10 <= len(cases) <= 20
    assert {case["input_type"] for case in cases} == {"text_news"}

    focus_tags = {tag for case in cases for tag in case["focus_tags"]}
    assert {"titlebait", "rumor_question", "mixed_truth", "official_response"}.issubset(focus_tags)

    for case in cases:
        assert case["expected"]["provider_should_help"]
        assert case["expected"]["claims_min"] >= 2
        assert case["expected"]["claims_should_include"]


def test_llm_provider_parses_non_strict_schema_and_filters_generic_claims(monkeypatch):
    payload = """
    {
      "event": {
        "title": "待核实事件",
        "summary": "滨海地铁运营公司回应停运传闻，仅3号线夜间检修，其他线路正常运营。",
        "keywords": "滨海地铁, 停运传闻, 3号线夜间检修",
        "source_name": "滨海地铁运营公司",
        "published_at": "2026-03-11"
      },
      "claims": [
        {"text": "网传滨海地铁明天全线停运", "claim_type": "rumor"},
        {"claim": "运营公司称仅3号线夜间检修，其余线路正常运营"},
        {"claim": "请以官方通报为准", "claim_type": "fact"}
      ]
    }
    """.strip()

    def fake_post(url, headers, json, timeout):
        return _DummyResponse(payload)

    monkeypatch.setenv("ANALYSIS_PROVIDER", "kimi")
    monkeypatch.setenv("LLM_API_KEY", "test-llm-key")
    get_settings.cache_clear()
    monkeypatch.setattr(llm_provider_module.httpx, "post", fake_post)
    try:
        provider = LlmStructuredProvider()
        analysis = provider.analyze(
            NormalizedEvent(
                title="热搜截图",
                summary="【热搜截图】网传滨海地铁明天全线停运？运营公司深夜回应：仅3号线夜间检修，其他线路正常运营。",
                input_type="text_news",
                raw_input="【热搜截图】网传滨海地铁明天全线停运？运营公司深夜回应：仅3号线夜间检修，其他线路正常运营。",
            )
        )
    finally:
        get_settings.cache_clear()

    assert analysis is not None
    assert analysis.event.title is not None
    assert "滨海地铁" in analysis.event.title
    assert analysis.event.summary is not None
    assert "3号线夜间检修" in analysis.event.summary
    assert analysis.event.keywords[:2] == ["滨海地铁", "停运传闻"]
    assert [item.claim for item in analysis.claims] == [
        "滨海地铁明天全线停运。",
        "运营公司称仅3号线夜间检修，其余线路正常运营。",
    ]
    assert {item.claim_type for item in analysis.claims} == {"fact"}


def test_provider_enricher_prefers_specific_provider_fields_over_generic_event_title():
    event = NormalizedEvent(
        title="热搜截图",
        summary="【热搜截图】网传滨海地铁明天全线停运？运营公司深夜回应：仅3号线夜间检修，其他线路正常运营。",
        keywords=["滨海地铁"],
        source_name="用户提供文本",
        input_type="text_news",
        raw_input="【热搜截图】网传滨海地铁明天全线停运？运营公司深夜回应：仅3号线夜间检修，其他线路正常运营。",
    )

    class _FakeProvider:
        def analyze(self, current_event):
            assert current_event.title == "热搜截图"
            return ProviderAnalysis(
                event=ProviderEventDraft(
                    title="待核实事件",
                    summary="滨海地铁运营公司称，仅3号线夜间检修，其他线路正常运营，不存在全线停运。",
                    keywords=["停运传闻", "3号线夜间检修"],
                    source_name="滨海地铁运营公司",
                    published_at="2026-03-11",
                ),
                claims=[
                    ClaimItem(claim="滨海地铁明天全线停运。", claim_type="fact"),
                    ClaimItem(claim="运营公司称仅3号线夜间检修，其余线路正常运营。", claim_type="fact"),
                ],
            )

    enricher = ProviderEnricher(provider=_FakeProvider())
    enriched_event, provider_claims = enricher.enrich(event)

    assert enriched_event.title is not None
    assert enriched_event.title != "热搜截图"
    assert "滨海地铁" in enriched_event.title
    assert enriched_event.summary.startswith("滨海地铁运营公司称")
    assert enriched_event.source_name == "滨海地铁运营公司"
    assert provider_claims is not None
    assert len(provider_claims) == 2


def test_api_provider_enabled_surfaces_more_helpful_output_than_off(monkeypatch, client):
    case = _quality_case("KP01")

    class _DisabledProvider:
        def analyze(self, event):
            return None

    class _FakeProvider:
        def analyze(self, event):
            return ProviderAnalysis(
                event=ProviderEventDraft(
                    title="滨海地铁回应停运传闻",
                    summary="滨海地铁运营公司称，仅3号线夜间检修，其他线路正常运营，不存在明天全线停运。",
                    keywords=["滨海地铁", "3号线夜间检修", "停运传闻"],
                    source_name="滨海地铁运营公司",
                    published_at="2026-03-11",
                ),
                claims=[
                    ClaimItem(claim="滨海地铁明天全线停运。", claim_type="fact"),
                    ClaimItem(claim="运营公司称仅3号线夜间检修，其余线路正常运营。", claim_type="fact"),
                ],
            )

    off_pipeline = AnalyzePipeline()
    off_pipeline.provider_enricher.provider = _DisabledProvider()
    monkeypatch.setattr(analyze_endpoint, "AnalyzePipeline", lambda: off_pipeline)
    off_response = client.post(
        "/api/v1/analyze",
        json={
            "raw_input": case["raw_input"],
            "input_type": case["input_type"],
        },
    )
    assert off_response.status_code == 200
    off_report = off_response.json()

    on_pipeline = AnalyzePipeline()
    on_pipeline.provider_enricher.provider = _FakeProvider()
    monkeypatch.setattr(analyze_endpoint, "AnalyzePipeline", lambda: on_pipeline)
    on_response = client.post(
        "/api/v1/analyze",
        json={
            "raw_input": case["raw_input"],
            "input_type": case["input_type"],
            "request_context": {"mode": "deep"},
        },
    )
    assert on_response.status_code == 200
    on_report = on_response.json()

    assert on_report["event"]["title"] != off_report["event"]["title"]
    assert all(token in on_report["event"]["title"] for token in case["expected"]["title_should_contain"])
    assert all(token in on_report["event"]["summary"] for token in case["expected"]["summary_should_include"])
    assert len(on_report["claim_results"]) >= case["expected"]["claims_min"]
    assert on_report["event"]["source_name"] == "滨海地铁运营公司"
    assert on_report["event"]["source_name"] != off_report["event"]["source_name"]
    assert on_report["provenance"]["provider_used"] is True
    assert off_report["provenance"]["provider_used"] is False



