from __future__ import annotations

import pytest

from backend.app.models.schemas import AnalyzeRequest
from backend.app.services.input_normalizer import InputNormalizer
from backend.eval_regression_tests.conftest import CaseEvaluation, load_eval_fixture, summarize_results

INPUT_CASES = load_eval_fixture("input_cases.json")


def _evaluate_case(case: dict) -> CaseEvaluation:
    event = InputNormalizer().normalize(
        AnalyzeRequest(
            raw_input=case["raw_input"],
            input_type=case["input_type"],
            mock_fetch_result=case.get("mock_fetch_result"),
        )
    )
    expected = case["expected"]
    mismatches: list[str] = []

    for field in expected.get("must_have_fields", []):
        value = getattr(event, field)
        if field == "keywords":
            if not value:
                mismatches.append("keywords should not be empty")
            continue
        if not value:
            mismatches.append(f"{field} is missing")

    for token in expected.get("title_contains", []):
        if token not in (event.title or ""):
            mismatches.append(f"title is missing token {token!r}")

    for keyword in expected.get("keywords_should_include", []):
        if keyword not in event.keywords:
            mismatches.append(f"keywords are missing {keyword!r}")

    if bool(event.fallback_used) != bool(expected.get("should_trigger_fallback")):
        mismatches.append(
            f"fallback_used={event.fallback_used} did not match expected {expected.get('should_trigger_fallback')}"
        )

    for field in expected.get("must_not_fake_fields", []):
        value = getattr(event, field)
        if value:
            mismatches.append(f"{field} should stay empty for this case, got {value!r}")

    if event.mode_hint != expected.get("expected_mode_hint"):
        mismatches.append(
            f"mode_hint={event.mode_hint!r} did not match expected {expected.get('expected_mode_hint')!r}"
        )

    return CaseEvaluation(
        case_id=case["case_id"],
        mismatches=mismatches,
        details={
            "input_type": event.input_type,
            "mode_hint": event.mode_hint,
            "fallback_used": str(event.fallback_used),
        },
    )


def test_input_eval_regression():
    evaluations = [_evaluate_case(case) for case in INPUT_CASES]
    summary = summarize_results("input_cases.json", evaluations)
    print(summary)
    if any(not item.passed for item in evaluations):
        pytest.fail(summary, pytrace=False)
