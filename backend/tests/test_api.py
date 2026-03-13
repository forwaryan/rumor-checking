from __future__ import annotations

from backend.tests.conftest import load_eval_fixture


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
    report = response.json()["report"]
    assert report["mode"] == "complete_mode"
    assert "海州市市场监管局" in report["event"]["title"]
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
    report = response.json()["report"]
    assert report["mode"] == "safe_mode"
    assert report["event"]["source_name"] is None
    assert all(item["verdict"] is None for item in report["claim_results"] if item["claim_type"] == "fact")


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
    report = response.json()["report"]
    assert report["mode"] == "safe_mode"
    assert report["fallback"]["used"] is True
    assert "补充完整正文" in report["next_steps"][0]


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
    report = response.json()["report"]
    assert report["mode"] == "partial_mode"
    assert any(item["verdict"] == "conflicting" for item in report["claim_results"])


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
