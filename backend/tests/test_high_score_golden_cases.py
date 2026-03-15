from __future__ import annotations

from backend.tests.conftest import load_eval_fixture


HIGH_SCORE_GOLDEN_CASES = (
    {
        "case_id": "GC01",
        "name": "expired-yogurt",
        "group": "demo",
        "expected_mode": "complete_mode",
        "usage": "public_mainline",
        "pytest_selector": "backend/tests/test_high_score_golden_cases.py::test_complete_demo_case_remains_stage_safe",
    },
    {
        "case_id": "GC02",
        "name": "morningstar-question",
        "group": "demo",
        "expected_mode": "partial_mode",
        "usage": "controlled_regression",
        "pytest_selector": "backend/tests/test_high_score_golden_cases.py::test_partial_demo_candidate_stays_question_first",
    },
    {
        "case_id": "GC03",
        "name": "viral-death-ambiguous",
        "group": "demo",
        "expected_mode": "safe_mode",
        "usage": "boundary_only",
        "pytest_selector": "backend/tests/test_high_score_golden_cases.py::test_safe_demo_candidate_refuses_to_overclaim",
    },
    {
        "case_id": "RG01",
        "name": "claim-split-binhai-metro",
        "group": "claim_split",
        "expected_mode": None,
        "usage": "internal_regression",
        "pytest_selector": "backend/tests/test_claim_extractor.py::test_claim_extractor_refines_provider_claims_into_atomic_claims_and_query_hints",
    },
    {
        "case_id": "RG02",
        "name": "mixed-truth-viral-death",
        "group": "mixed_truth",
        "expected_mode": None,
        "usage": "internal_regression",
        "pytest_selector": "backend/tests/test_api.py::test_provider_mixed_claims_surface_true_false_split_and_answer_suggestions",
    },
    {
        "case_id": "RG03",
        "name": "propagation-r01",
        "group": "propagation",
        "expected_mode": None,
        "usage": "internal_regression",
        "pytest_selector": "backend/tests/test_retrieval.py::test_timeline_builder_uses_retrieval_candidates[R01]",
    },
    {
        "case_id": "RG04",
        "name": "score-guardrail",
        "group": "score_guardrail",
        "expected_mode": None,
        "usage": "internal_regression",
        "pytest_selector": "backend/tests/test_high_score_golden_cases.py::test_score_fields_are_either_computed_or_explicitly_empty",
    },
)


def _case_by_id(filename: str, case_id: str):
    cases = load_eval_fixture(filename)
    return next(item for item in cases if item["case_id"] == case_id)


def test_high_score_golden_case_inventory_freezes_demo_regression_and_smoke_entries():
    demo_cases = [item for item in HIGH_SCORE_GOLDEN_CASES if item["group"] == "demo"]
    assert len(demo_cases) == 3
    assert {item["expected_mode"] for item in demo_cases} == {
        "complete_mode",
        "partial_mode",
        "safe_mode",
    }
    assert {item["usage"] for item in demo_cases} == {
        "public_mainline",
        "controlled_regression",
        "boundary_only",
    }

    covered_groups = {item["group"] for item in HIGH_SCORE_GOLDEN_CASES}
    assert {"claim_split", "mixed_truth", "propagation", "score_guardrail"}.issubset(covered_groups)
    for item in HIGH_SCORE_GOLDEN_CASES:
        assert item["pytest_selector"]


def test_complete_demo_case_remains_stage_safe(client):
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
    assert report["timeline"]
    assert report["claim_results"]
    assert report["provenance"]["source_type"] == "backend_mock"
    assert report["provenance"]["evidence_source"] == "retrieval_mock"


def test_partial_demo_candidate_stays_question_first(client):
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
    assert report["event"]["title"] == "晨星生物回应裁员传闻"
    assert report["retrieval_hits"]
    assert any(item["verdict"] == "refuted" for item in report["claim_results"])
    assert report["provenance"]["source_type"] == "backend_mock"
    assert report["provenance"]["event_source"] == "retrieval_resolved"


def test_safe_demo_candidate_refuses_to_overclaim(client):
    response = client.post(
        "/api/v1/analyze",
        json={
            "raw_input": "最近有个女网红脑出血死了真的假的？",
            "input_type": "question",
        },
    )

    assert response.status_code == 200
    report = response.json()
    assert report["mode"] == "safe_mode"
    assert report["sources"] == []
    assert len(report["investigation"]["possibilities"]) >= 2
    assert "不能判定真假" in report["investigation"]["final_conclusion"]
    assert report["overall_credibility_score"] is None
    assert report["overall_credibility_label"] is None
    assert report["score_breakdown"] is None
    assert report["claim_contributions"] is None


def test_score_fields_are_either_computed_or_explicitly_empty(client):
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
    for key in (
        "overall_credibility_score",
        "overall_credibility_label",
        "score_breakdown",
        "claim_contributions",
        "timeline_confidence",
        "independent_source_count",
    ):
        assert key in report

    score = report["overall_credibility_score"]
    label = report["overall_credibility_label"]
    breakdown = report["score_breakdown"]
    claim_contributions = report["claim_contributions"]
    assert score is not None
    assert 0 <= score <= 100
    assert label in {"high_credibility", "medium_credibility"}
    assert score >= 55
    assert breakdown is not None
    assert breakdown["weights"] == {
        "claim": 0.5,
        "source_quality": 0.2,
        "cross_source_agreement": 0.2,
        "timeline": 0.1,
    }
    assert claim_contributions is not None
    assert any(item["contribution_label"] == "supports" for item in claim_contributions)

    timeline_confidence = report["timeline_confidence"]
    assert timeline_confidence is not None
    assert 0 <= timeline_confidence <= 100

    independent_source_count = report["independent_source_count"]
    assert independent_source_count is not None
    assert independent_source_count >= 2


def test_partial_demo_candidate_emits_conservative_score(client):
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
    assert report["overall_credibility_score"] is not None
    assert report["overall_credibility_label"] in {"low_credibility", "mixed", "insufficient_evidence"}
    assert report["overall_credibility_label"] != "high_credibility"
    assert report["score_breakdown"] is not None
    assert report["claim_contributions"] is not None
