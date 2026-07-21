from __future__ import annotations

from contextlib import contextmanager
import json

import httpx
from fastapi.testclient import TestClient

from backend.app.core.config import get_settings
from backend.app.main import create_app
from backend.app.models.schemas import ClaimItem, EvidenceItem, ProviderAnalysis, ProviderEventDraft
from backend.app.services.llm_provider import LlmStructuredProvider
from backend.app.services.url_content_extractor import UrlContentExtractor
from backend.tests.conftest import load_eval_fixture


REPORT_KEYS = {
    "mode",
    "event",
    "timeline",
    "claim_results",
    "final_summary",
    "risks",
    "sources",
    "retrieval_hits",
    "retrieval_diagnostics",
    "investigation",
    "content_check",
    "pipeline_trace",
    "provenance",
}
PROVENANCE_KEYS = {
    "source_type",
    "event_source",
    "claim_source",
    "evidence_source",
    "timeline_source",
    "retrieval_provider",
    "retrieval_cache_status",
    "provider_used",
    "fallback_used",
    "fallback_reasons",
}


def _case_by_id(filename: str, case_id: str):
    cases = load_eval_fixture(filename)
    return next(item for item in cases if item["case_id"] == case_id)


@contextmanager
def _provider_enabled_client(monkeypatch):
    monkeypatch.setenv("ANALYSIS_PROVIDER", "kimi")
    monkeypatch.setenv("LLM_API_KEY", "test-llm-key")
    get_settings.cache_clear()
    try:
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client
    finally:
        get_settings.cache_clear()


@contextmanager
def _configured_client(monkeypatch, **env_overrides):
    for key, value in env_overrides.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
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


def _assert_provenance_shape(report: dict) -> None:
    assert REPORT_KEYS.issubset(report.keys())
    assert PROVENANCE_KEYS.issubset(report["provenance"].keys())


def _assert_investigation_shape(report: dict) -> None:
    investigation = report["investigation"]
    assert investigation is not None
    assert {"question", "reframed_question", "thinking_process", "possibilities", "final_conclusion"}.issubset(investigation.keys())
    assert len(investigation["thinking_process"]) >= 3
    assert investigation["final_conclusion"]


def _assert_pipeline_trace_shape(report: dict) -> None:
    pipeline_trace = report["pipeline_trace"]
    assert pipeline_trace is not None
    steps = pipeline_trace["steps"]
    assert len(steps) >= 6
    required_keys = {"stage_key", "title", "status", "summary", "details"}
    assert {"input_received", "normalize_input", "claim_extraction", "verdict_evaluation", "report_output"}.issubset(
        {step["stage_key"] for step in steps}
    )
    for step in steps:
        assert required_keys.issubset(step.keys())
        assert step["status"] in {"completed", "warning", "skipped", "error"}
        assert isinstance(step["details"], list)


def _assert_content_check_shape(report: dict) -> None:
    content_check = report["content_check"]
    assert content_check is not None
    assert {
        "likely_true",
        "likely_false",
        "controversial",
        "opinions",
        "uncertain",
        "possible_answers",
    }.issubset(content_check.keys())
    for key in ["likely_true", "likely_false", "controversial", "opinions", "uncertain"]:
        assert isinstance(content_check[key], list)
        for item in content_check[key]:
            assert {"claim", "claim_type", "verdict", "confidence", "reason"}.issubset(item.keys())
    for item in content_check["possible_answers"]:
        assert {"angle", "answer"}.issubset(item.keys())


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


def test_analyze_stream_returns_live_ndjson_events(client):
    response = client.post(
        "/api/v1/analyze/stream",
        json={
            "raw_input": "最近有个女网红脑出血死了真的假的？",
            "input_type": "question",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")

    events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    event_types = [event["type"] for event in events]

    assert event_types[0] == "session"
    assert "stage" in event_types
    assert "report" in event_types
    assert event_types[-1] == "complete"
    assert any(event.get("stage_key") == "normalize_input" for event in events if event["type"] == "stage")
    assert any(event.get("stage_key") == "report_build" for event in events if event["type"] == "stage")


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
    _assert_provenance_shape(report)
    _assert_content_check_shape(report)
    _assert_pipeline_trace_shape(report)
    assert report["mode"] == "complete_mode"
    assert report["event"]["mode"] == "complete_mode"
    assert "海州市市场监管局" in report["event"]["title"]
    assert report["sources"]
    assert any(item["verdict"] in {"supported", "conflicting", "refuted"} for item in report["claim_results"])
    assert len(report["timeline"]) >= 2
    assert report["provenance"]["source_type"] == "backend_mock"
    assert report["provenance"]["claim_source"] == "rule"
    assert report["provenance"]["evidence_source"] == "retrieval_mock"
    assert report["provenance"]["timeline_source"] == "retrieval"


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
    _assert_provenance_shape(report)
    _assert_content_check_shape(report)
    _assert_pipeline_trace_shape(report)
    assert report["mode"] == "partial_mode"
    assert report["event"]["title"] == "晨星生物回应裁员传闻"
    assert report["event"]["source_name"] == "晨星生物"
    assert any(item["verdict"] == "refuted" for item in report["claim_results"])
    assert report["sources"]
    assert report["retrieval_hits"]
    assert report["retrieval_diagnostics"]["canonical_result_count"] >= len(report["retrieval_hits"])
    assert report["retrieval_diagnostics"]["query"]
    assert report["provenance"]["source_type"] == "backend_mock"
    assert report["provenance"]["event_source"] == "retrieval_resolved"
    assert report["provenance"]["evidence_source"] == "retrieval_mock"
    _assert_investigation_shape(report)
    assert report["investigation"]["question"] == case["raw_input"]
    assert any("主说法不成立" in item["scenario"] for item in report["investigation"]["possibilities"])
    assert "不成立" in report["investigation"]["final_conclusion"]
    assert any(step["stage_key"] == "question_resolution" for step in report["pipeline_trace"]["steps"])
    assert any(step["stage_key"] == "follow_up_retrieval" for step in report["pipeline_trace"]["steps"])

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
    _assert_provenance_shape(report)
    _assert_content_check_shape(report)
    _assert_pipeline_trace_shape(report)
    assert report["mode"] == "partial_mode"
    assert any("保守输出" in item for item in report["risks"])
    assert any(item["verdict"] in {"supported", "conflicting", "refuted"} for item in report["claim_results"])
    assert report["sources"]
    assert report["provenance"]["source_type"] == "backend_mock"
    assert report["provenance"]["fallback_used"] is True
    assert "url_content_incomplete" in report["provenance"]["fallback_reasons"]


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
    _assert_provenance_shape(report)
    _assert_content_check_shape(report)
    _assert_pipeline_trace_shape(report)
    assert report["mode"] == "partial_mode"
    assert report["event"]["title"] == "海州市市场监管局通报海州新鲜屋酸奶抽检结果"
    assert "海州新鲜屋" in report["event"]["summary"]
    assert report["event"]["source_name"] == "海州市市场监管局"
    assert report["event"]["published_at"].startswith("2026-03-01T09:00:00")
    assert report["sources"]
    assert any(item["verdict"] in {"supported", "conflicting", "refuted"} for item in report["claim_results"])
    assert report["provenance"]["event_source"] == "url_extract"


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
    _assert_provenance_shape(report)
    _assert_content_check_shape(report)
    _assert_pipeline_trace_shape(report)
    assert report["mode"] == "safe_mode"
    assert report["event"]["source_name"] == "files.example.com"
    assert "抽取不完整" in report["event"]["summary"]
    assert report["risks"]
    assert report["sources"] == []
    assert report["retrieval_hits"] == []
    assert report["retrieval_diagnostics"]["canonical_result_count"] == 0
    assert report["retrieval_diagnostics"]["query"]
    assert report["provenance"]["fallback_used"] is True
    assert report["provenance"]["evidence_source"] == "none"


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
    _assert_provenance_shape(report)
    assert report["mode"] == "safe_mode"
    assert "抓取超时" in report["event"]["summary"]
    assert any("抓取超时" in item for item in report["risks"])
    assert report["sources"] == []
    assert report["retrieval_diagnostics"]["canonical_result_count"] == 0
    assert "url_fetch_timeout" in report["provenance"]["fallback_reasons"]


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


def test_analyze_unmatched_text_input_stays_safe_without_evidence(client):
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
    _assert_provenance_shape(report)
    assert report["mode"] == "safe_mode"
    assert report["sources"] == []
    assert all(item["verdict"] == "insufficient" for item in report["claim_results"])
    assert report["provenance"]["evidence_source"] == "none"
    assert report["provenance"]["timeline_source"] == "input_seed"


def test_analyze_ambiguous_question_lists_possibilities_without_overclaiming(client):
    raw_input = "最近有个女网红脑出血死了真的假的？"
    response = client.post(
        "/api/v1/analyze",
        json={
            "raw_input": raw_input,
            "input_type": "question",
        },
    )
    assert response.status_code == 200
    report = response.json()
    _assert_provenance_shape(report)
    _assert_investigation_shape(report)
    assert report["mode"] == "safe_mode"
    assert report["investigation"]["question"] == raw_input
    assert len(report["investigation"]["possibilities"]) >= 2
    assert any("夸大成了死亡" in item["scenario"] for item in report["investigation"]["possibilities"])
    assert any("事实锚点" in item["scenario"] for item in report["investigation"]["possibilities"])
    assert "不能判定真假" in report["investigation"]["final_conclusion"]


def test_analyze_without_evidence_keeps_safe_mode_and_live_provenance(monkeypatch):
    with _configured_client(
        monkeypatch,
        ANALYSIS_PROVIDER="off",
        KIMI_API_KEY=None,
        RETRIEVAL_PROVIDER="off",
        RETRIEVAL_FALLBACK_TO_MOCK="false",
    ) as test_client:
        response = test_client.post(
            "/api/v1/analyze",
            json={
                "raw_input": "网传某地今晚会出现不明爆炸，但没有给出地点和来源。",
                "input_type": "text",
            },
        )

    assert response.status_code == 200
    report = response.json()
    _assert_provenance_shape(report)
    assert report["mode"] == "safe_mode"
    assert report["sources"] == []
    assert report["provenance"]["source_type"] == "backend_live"
    assert report["provenance"]["evidence_source"] == "none"
    assert report["provenance"]["fallback_used"] is False
    assert all(item["verdict"] == "insufficient" for item in report["claim_results"] if item["claim_type"] == "fact")


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
    _assert_provenance_shape(report)
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

    monkeypatch.setattr(LlmStructuredProvider, "analyze", fake_analyze)

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
    _assert_provenance_shape(report)
    assert report["event"]["title"] == "省市场监管局核查品牌奶制品抽检情况"
    assert report["event"]["summary"] == "省市场监管局已介入核查，企业回应称正在整改。"
    assert report["event"]["source_name"] == "省市场监管局"
    assert report["event"]["published_at"].startswith("2026-03-08T00:00:00")
    assert report["claim_results"][0]["claim"] == "省市场监管局已经介入核查。"
    assert report["claim_results"][1]["claim_type"] == "opinion"
    assert report["provenance"]["provider_used"] is True
    assert report["provenance"]["event_source"] == "provider_enriched"
    assert report["provenance"]["claim_source"] == "provider"


def test_provider_mixed_claims_surface_true_false_split_and_answer_suggestions(monkeypatch):
    def fake_analyze(self, event):
        return ProviderAnalysis(
            event=ProviderEventDraft(
                title="医院回应女主播病情传闻",
                summary="医院确认当事人突发脑出血入院，家属辟谣去世和封锁消息说法。",
                keywords=["女主播", "脑出血", "辟谣"],
                source_name="市第一医院",
                published_at="2026-03-12",
            ),
            claims=[
                ClaimItem(claim="医院确认存在脑出血入院治疗情况。", claim_type="fact"),
                ClaimItem(claim="当事人已经去世。", claim_type="fact"),
                ClaimItem(claim="平台封锁了消息。", claim_type="fact"),
            ],
        )

    monkeypatch.setattr(LlmStructuredProvider, "analyze", fake_analyze)

    mock_evidence = [
        EvidenceItem(
            title="市第一医院通报女主播突发脑出血入院治疗",
            url="https://hospital.example.com/notice-1",
            source_name="市第一医院",
            published_at="2026-03-12T09:00:00+08:00",
            snippet="医院通报称，患者因突发脑出血入院治疗，目前生命体征平稳。",
            relevance_reason="医院直接通报了入院救治情况。",
            source_tier="S",
        ),
        EvidenceItem(
            title="家属辟谣当事人去世和平台封锁消息说法",
            url="https://news.example.com/family-response",
            source_name="news.cn",
            published_at="2026-03-12T12:00:00+08:00",
            snippet="家属表示当事人去世消息不实，平台并未封锁消息，相关说法系误传。",
            relevance_reason="家属直接回应了死亡和封锁消息两条传闻。",
            source_tier="A",
        ),
    ]

    with _provider_enabled_client(monkeypatch) as provider_client:
        response = provider_client.post(
            "/api/v1/analyze",
            json={
                "raw_input": "网传某女主播脑出血去世，平台还封锁消息。",
                "input_type": "text",
                "mock_evidence": [item.model_dump(mode="json") for item in mock_evidence],
            },
        )

    assert response.status_code == 200
    report = response.json()
    _assert_provenance_shape(report)
    _assert_content_check_shape(report)
    assert any(item["claim"] == "医院确认存在脑出血入院治疗情况。" for item in report["content_check"]["likely_true"])
    assert any(item["claim"] == "当事人已经去世。" for item in report["content_check"]["likely_false"])
    assert any(item["claim"] == "平台封锁了消息。" for item in report["content_check"]["likely_false"])
    assert any("半真半假" in item["answer"] or "更像真的部分" in item["answer"] for item in report["content_check"]["possible_answers"])


def test_provider_failures_fall_back_to_rule_pipeline(monkeypatch):
    def fake_request_completion(self, event):
        raise httpx.ReadTimeout("provider timeout")

    monkeypatch.setattr(LlmStructuredProvider, "_request_completion", fake_request_completion)
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
    _assert_provenance_shape(report)
    assert report["mode"] == "complete_mode"
    assert "海州市市场监管局" in report["event"]["title"]
    assert any(item["verdict"] in {"supported", "conflicting", "refuted"} for item in report["claim_results"])
    assert report["provenance"]["provider_used"] is False
    assert report["provenance"]["claim_source"] == "rule"


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

