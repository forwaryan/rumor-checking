from __future__ import annotations

from backend.tests.conftest import load_eval_fixture


REPORT_KEYS = {"mode", "event", "timeline", "claim_results", "final_summary", "risks", "sources"}


def _case_by_id(filename: str, case_id: str):
    cases = load_eval_fixture(filename)
    return next(item for item in cases if item["case_id"] == case_id)


def test_health_endpoint_returns_service_metadata(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "rumor-checking-backend"


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


def test_analyze_question_only_stays_in_safe_mode(client):
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
    assert report["mode"] == "safe_mode"
    assert report["event"]["source_name"] == "用户问题输入"
    assert all(item["verdict"] == "insufficient" for item in report["claim_results"])


def test_analyze_url_fallback_keeps_report_conservative(client):
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
    assert report["mode"] == "safe_mode"
    assert any("保守输出" in item for item in report["risks"])
    assert report["sources"] == []


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
