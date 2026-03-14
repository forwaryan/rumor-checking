from __future__ import annotations

from contextlib import contextmanager

import httpx
from fastapi.testclient import TestClient

from backend.app.core.config import get_settings
from backend.app.main import create_app
from backend.app.models.schemas import ClaimItem, ProviderAnalysis, ProviderEventDraft
from backend.app.services.kimi_provider import KimiProvider
from backend.app.services.url_content_extractor import UrlContentExtractor
from backend.tests.conftest import load_eval_fixture


REPORT_KEYS = {"mode", "event", "timeline", "claim_results", "final_summary", "risks", "sources"}


def _case_by_id(filename: str, case_id: str):
    cases = load_eval_fixture(filename)
    return next(item for item in cases if item["case_id"] == case_id)


@contextmanager
def _provider_enabled_client(monkeypatch):
    monkeypatch.setenv("ANALYSIS_PROVIDER", "kimi")
    monkeypatch.setenv("KIMI_API_KEY", "test-kimi-key")
    get_settings.cache_clear()
    try:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client
    finally:
        get_settings.cache_clear()


def _html_response(url: str, html: str, *, content_type: str = "text/html; charset=utf-8") -> httpx.Response:
    return httpx.Response(
        200,
        request=httpx.Request("GET", url),
        headers={"content-type": content_type},
        text=html,
    )


def test_health_endpoint_returns_service_metadata(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "rumor-checking-backend"


def test_health_endpoint_allows_local_frontend_origin(client):
    response = client.get(
        "/api/v1/health",
        headers={"Origin": "http://127.0.0.1:3123"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:3123"


def test_validation_errors_use_unified_error_shape(client):
    response = client.post("/api/v1/analyze", json={})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["trace_id"]


def test_analyze_text_news_builds_complete_mode_report(client):
    case = _case_by_id("input_cases.json", "I01")
    response = client.post(
        "/api/v1/analyze",
        json={
            "raw_input": case["raw_input"],
            "input_type": case["input_type"],
        },
    )
    assert response.status_code == 200
    report = response.json()
    assert REPORT_KEYS.issubset(report.keys())
    assert report["mode"] == "complete_mode"
    assert report["event"]["mode"] == "complete_mode"
    assert "海州市市场监管局" in report["event"]["title"]
    assert report["sources"]
    assert any(item["verdict"] == "supported" for item in report["claim_results"])
    assert len(report["timeline"]) >= 2


def test_analyze_question_only_can_surface_partial_mode_with_retrieval_evidence(client):
    case = _case_by_id("input_cases.json", "I03")
    response = client.post(
        "/api/v1/analyze",
        json={
            "raw_input": case["raw_input"],
            "input_type": case["input_type"],
        },
    )
    assert response.status_code == 200
    report = response.json()
    assert report["mode"] == "partial_mode"
    assert report["event"]["source_name"] == "用户问题输入"
    assert any(item["verdict"] == "refuted" for item in report["claim_results"])
    assert report["sources"]


def test_analyze_url_fallback_keeps_risk_language_but_can_still_surface_partial_mode(client):
    case = _case_by_id("input_cases.json", "I05")
    response = client.post(
        "/api/v1/analyze",
        json={
            "raw_input": case["raw_input"],
            "input_type": case["input_type"],
            "mock_fetch_result": case["mock_fetch_result"],
        },
    )
    assert response.status_code == 200
    report = response.json()
    assert report["mode"] == "partial_mode"
    assert any("保守输出" in item for item in report["risks"])
    assert any(item["verdict"] == "supported" for item in report["claim_results"])
    assert report["sources"]


def test_analyze_url_extraction_success_populates_event_fields(monkeypatch, client):
    html = """
    <html>
      <head>
        <title>海州市市场监管局通报海州新鲜屋酸奶抽检结果</title>
        <meta property="og:site_name" content="海州市市场监管局" />
        <meta property="article:published_time" content="2026-03-01T09:00:00+08:00" />
        <meta name="description" content="海州市市场监管局通报称，海州新鲜屋部分酸奶批次超过保质期。" />
      </head>
      <body>
        <article>
          <p>2026年3月1日，海州市市场监管局发布通报称，在例行抽检中发现海州新鲜屋连锁门店有2批次酸奶超过保质期，涉事门店已停业整改。</p>
          <p>目前未发现大规模食物中毒病例。</p>
        </article>
      </body>
    </html>
    """

    def fake_fetch(self, url: str) -> httpx.Response:
        return _html_response(url, html)

    monkeypatch.setattr(UrlContentExtractor, "_fetch", fake_fetch)

    response = client.post(
        "/api/v1/analyze",
        json={
            "raw_input": "https://news.example.com/articles/acid-milk",
            "input_type": "url",
        },
    )

    assert response.status_code == 200
    report = response.json()
    assert report["mode"] == "partial_mode"
    assert report["event"]["title"] == "海州市市场监管局通报海州新鲜屋酸奶抽检结果"
    assert "海州新鲜屋" in report["event"]["summary"]
    assert report["event"]["source_name"] == "海州市市场监管局"
    assert report["event"]["published_at"].startswith("2026-03-01T09:00:00")
    assert report["sources"]
    assert any(item["verdict"] == "supported" for item in report["claim_results"])


def test_analyze_url_extraction_failure_stays_safe(monkeypatch, client):
    def fake_fetch(self, url: str) -> httpx.Response:
        return _html_response(url, "<html><head><title>下载文件</title></head><body></body></html>", content_type="application/pdf")

    monkeypatch.setattr(UrlContentExtractor, "_fetch", fake_fetch)

    response = client.post(
        "/api/v1/analyze",
        json={
            "raw_input": "https://files.example.com/report.pdf",
            "input_type": "url",
        },
    )

    assert response.status_code == 200
    report = response.json()
    assert report["mode"] == "safe_mode"
    assert report["event"]["source_name"] == "files.example.com"
    assert "抽取不完整" in report["event"]["summary"]
    assert report["risks"]
    assert report["sources"] == []


def test_analyze_url_extraction_timeout_falls_back_without_crashing(monkeypatch, client):
    def fake_fetch(self, url: str) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=httpx.Request("GET", url))

    monkeypatch.setattr(UrlContentExtractor, "_fetch", fake_fetch)

    response = client.post(
        "/api/v1/analyze",
        json={
            "raw_input": "https://news.example.com/slow-page",
            "input_type": "url",
        },
    )

    assert response.status_code == 200
    report = response.json()
    assert report["mode"] == "safe_mode"
    assert "抓取超时" in report["event"]["summary"]
    assert any("抓取超时" in item for item in report["risks"])
    assert report["sources"] == []


def test_text_input_does_not_trigger_url_extractor(monkeypatch, client):
    def fail_extract(self, url: str):
        raise AssertionError("text input should not trigger URL extraction")

    monkeypatch.setattr(UrlContentExtractor, "extract", fail_extract)
    case = _case_by_id("input_cases.json", "I01")

    response = client.post(
        "/api/v1/analyze",
        json={
            "raw_input": case["raw_input"],
            "input_type": case["input_type"],
        },
    )

    assert response.status_code == 200
    report = response.json()
    assert report["mode"] == "complete_mode"
    assert "海州市市场监管局" in report["event"]["title"]


def test_analyze_partial_mode_exposes_conflicting_claims(client):
    case = _case_by_id("input_cases.json", "I06")
    response = client.post(
        "/api/v1/analyze",
        json={
            "raw_input": case["raw_input"],
            "input_type": case["input_type"],
        },
    )
    assert response.status_code == 200
    report = response.json()
    assert report["mode"] == "partial_mode"
    assert any(item["verdict"] == "conflicting" for item in report["claim_results"])


def test_analyze_accepts_frontend_payload_shape(client):
    case = _case_by_id("input_cases.json", "I01")
    response = client.post(
        "/api/v1/analyze",
        json={
            "input": case["raw_input"],
            "input_type": "text",
            "use_demo_case": False,
        },
    )
    assert response.status_code == 200
    report = response.json()
    assert "report" not in report
    assert REPORT_KEYS.issubset(report.keys())
    assert report["mode"] == "complete_mode"


def test_provider_enrichment_updates_event_and_claims(monkeypatch):
    def fake_analyze(self, event):
        assert event.input_type == "text_news"
        return ProviderAnalysis(
            event=ProviderEventDraft(
                title="省市场监管局核查品牌奶制品抽检情况",
                summary="省市场监管局已介入核查，企业回应称正在整改。",
                keywords=["省市场监管局", "抽检", "整改"],
                source_name="省市场监管局",
                published_at="2026-03-08",
            ),
            claims=[
                ClaimItem(claim="省市场监管局已经介入核查。", claim_type="fact"),
                ClaimItem(claim="品牌方的回应明显站不住脚。", claim_type="opinion"),
            ],
        )

    monkeypatch.setattr(KimiProvider, "analyze", fake_analyze)

    with _provider_enabled_client(monkeypatch) as provider_client:
        response = provider_client.post(
            "/api/v1/analyze",
            json={
                "raw_input": "省市场监管部门正核查某品牌奶制品抽检情况，品牌方随后回应并说明整改。",
                "input_type": "text",
            },
        )

    assert response.status_code == 200
    report = response.json()
    assert report["event"]["title"] == "省市场监管局核查品牌奶制品抽检情况"
    assert report["event"]["summary"] == "省市场监管局已介入核查，企业回应称正在整改。"
    assert report["event"]["source_name"] == "省市场监管局"
    assert report["event"]["published_at"].startswith("2026-03-08T00:00:00")
    assert report["claim_results"][0]["claim"] == "省市场监管局已经介入核查。"
    assert report["claim_results"][1]["claim_type"] == "opinion"


def test_provider_failures_fall_back_to_rule_pipeline(monkeypatch):
    def fake_request_completion(self, event):
        raise httpx.ReadTimeout("provider timeout")

    monkeypatch.setattr(KimiProvider, "_request_completion", fake_request_completion)
    case = _case_by_id("input_cases.json", "I01")

    with _provider_enabled_client(monkeypatch) as provider_client:
        response = provider_client.post(
            "/api/v1/analyze",
            json={
                "raw_input": case["raw_input"],
                "input_type": case["input_type"],
            },
        )

    assert response.status_code == 200
    report = response.json()
    assert report["mode"] == "complete_mode"
    assert "海州市市场监管局" in report["event"]["title"]
    assert any(item["verdict"] == "supported" for item in report["claim_results"])


def test_internal_errors_use_unified_error_shape(client):
    response = client.post(
        "/api/v1/analyze",
        json={
            "raw_input": "内部错误测试",
            "request_context": {"force_error": True},
        },
    )
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_server_error"
    assert body["error"]["details"]["error_type"] == "RuntimeError"




