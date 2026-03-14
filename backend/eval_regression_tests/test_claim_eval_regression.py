from __future__ import annotations

import pytest

from backend.app.services.claim_extractor import ClaimExtractor
from backend.eval_regression_tests.conftest import CaseEvaluation, load_eval_fixture, summarize_results

CLAIM_CASES = load_eval_fixture("claim_classification_cases.json")


def _evaluate_case(case: dict) -> CaseEvaluation:
    actual = ClaimExtractor().classify(case["claim"])
    mismatches: list[str] = []
    if actual != case["expected_claim_type"]:
        mismatches.append(
            f"claim_type={actual!r} did not match expected {case['expected_claim_type']!r}"
        )
    return CaseEvaluation(
        case_id=case["case_id"],
        mismatches=mismatches,
        details={"actual_claim_type": actual},
    )


def test_claim_eval_regression():
    evaluations = [_evaluate_case(case) for case in CLAIM_CASES]
    summary = summarize_results("claim_classification_cases.json", evaluations)
    print(summary)
    if any(not item.passed for item in evaluations):
        pytest.fail(summary, pytrace=False)
