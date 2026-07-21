from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.core.config import get_settings
from backend.app.main import create_app
from backend.app.models.schemas import ClaimItem, ProviderAnalysis, ProviderEventDraft
from backend.app.services.llm_provider import LlmStructuredProvider
from backend.app.services.retrieval_models import SearchResult
from backend.app.services.retrieval_provider import LlmWebSearchProvider


def test_health_reports_degraded_when_llm_is_not_configured(monkeypatch):
    monkeypatch.setenv("ANALYSIS_PROVIDER", "kimi")
    monkeypatch.setenv("KIMI_API_KEY", "")
    get_settings.cache_clear()

    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"


def test_analyze_request_falls_back_to_rule_claims_when_llm_returns_no_claims(monkeypatch):
    monkeypatch.setenv("ANALYSIS_PROVIDER", "kimi")
    monkeypatch.setenv("RETRIEVAL_PROVIDER", "kimi")
    monkeypatch.setenv("LLM_API_KEY", "test-llm-key")

    def fake_search(self, query_text: str):
        return [
            SearchResult(
                case_id="real_search",
                query=query_text,
                result_id="web-1",
                title="平台回应相关传闻",
                url="https://example-news.test/story-1",
                source_name="example-news.test",
                published_at="2026-03-15T08:00:00+08:00",
                snippet="平台回应称正在核查相关传闻。",
                source_tier="A",
            )
        ]

    def fake_analyze(self, event):
        return ProviderAnalysis(
            event=ProviderEventDraft(
                title="平台回应相关传闻",
                summary="平台回应称正在核查相关传闻。",
                keywords=["平台回应", "相关传闻"],
            ),
            claims=[],
        )

    monkeypatch.setattr(LlmWebSearchProvider, "search", fake_search)
    monkeypatch.setattr(LlmStructuredProvider, "analyze", fake_analyze)
    get_settings.cache_clear()

    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/v1/analyze",
            json={"raw_input": "最近有个女网红脑出血死了真的假的？", "input_type": "question"},
        )

    assert response.status_code == 200
    report = response.json()
    assert report["provenance"]["retrieval_provider"] == "kimi"
    assert report["provenance"]["claim_source"] == "rule"
    assert report["claim_results"]


def test_analyze_request_uses_llm_only_path(monkeypatch):
    monkeypatch.setenv("ANALYSIS_PROVIDER", "kimi")
    monkeypatch.setenv("RETRIEVAL_PROVIDER", "kimi")
    monkeypatch.setenv("LLM_API_KEY", "test-llm-key")

    def fake_search(self, query_text: str):
        return [
            SearchResult(
                case_id="real_search",
                query=query_text,
                result_id="web-1",
                title="医院回应脑出血救治情况",
                url="https://hospital.example.com/notice-1",
                source_name="hospital.example.com",
                published_at="2026-03-15T08:00:00+08:00",
                snippet="医院通报称当事人仍在救治，没有死亡信息。",
                source_tier="S",
            ),
            SearchResult(
                case_id="real_search",
                query=query_text,
                result_id="web-2",
                title="平台发布辟谣说明",
                url="https://platform.example.com/statement-1",
                source_name="platform.example.com",
                published_at="2026-03-15T09:00:00+08:00",
                snippet="平台称网传死亡和封锁消息不实。",
                source_tier="A",
            ),
        ]

    def fake_analyze(self, event):
        return ProviderAnalysis(
            event=ProviderEventDraft(
                title="某主播脑出血传闻与平台辟谣",
                summary="公开回应显示当事人正在救治，网传死亡和封锁消息不实。",
                keywords=["脑出血", "救治", "辟谣"],
                source_name="平台公告",
                published_at="2026-03-15T09:00:00+08:00",
            ),
            claims=[
                ClaimItem(claim="当事人发生脑出血并正在救治。", claim_type="fact"),
                ClaimItem(claim="当事人已经死亡。", claim_type="fact"),
                ClaimItem(claim="平台封锁了消息。", claim_type="fact"),
            ],
        )

    monkeypatch.setattr(LlmWebSearchProvider, "search", fake_search)
    monkeypatch.setattr(LlmStructuredProvider, "analyze", fake_analyze)
    get_settings.cache_clear()

    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/v1/analyze",
            json={"raw_input": "最近有个女网红脑出血死了真的假的？", "input_type": "question"},
        )

    assert response.status_code == 200
    report = response.json()
    assert report["provenance"]["source_type"] == "backend_live"
    assert report["provenance"]["retrieval_provider"] == "kimi"
    assert report["provenance"]["claim_source"] == "provider"
    assert report["provenance"]["provider_used"] is True
    assert report["provenance"]["fallback_used"] is False
    assert report["retrieval_diagnostics"]["provider_name"] == "kimi"
    assert report["retrieval_diagnostics"]["canonical_result_count"] == 2
    assert report["claim_results"]
    assert report["content_check"] is not None
