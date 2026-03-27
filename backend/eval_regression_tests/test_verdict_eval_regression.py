from __future__ import annotations

import pytest

from backend.app.models.schemas import AnalyzeRequest, ClaimItem, NormalizedEvent
from backend.app.services.verdict_engine import VerdictEngine
from backend.eval_regression_tests.conftest import CaseEvaluation, load_eval_fixture, summarize_results

DECISIVE_VERDICTS = {"supported", "refuted", "conflicting"}
VERDICT_CASES = load_eval_fixture("verdict_cases.json")


def _event_fixture(case_id: str) -> NormalizedEvent:
    return NormalizedEvent(
        title=f"Verdict regression {case_id}",
        summary="Independent verdict regression fixture.",
        keywords=["eval", "verdict"],
        source_name="fixed regression fixture",
        source_url="https://example.org/eval-regression/verdict",
        published_at="2026-03-14T00:00:00+08:00",
        input_type="text_news",
        mode_hint="partial",
        fallback_used=False,
        raw_input="independent verdict regression fixture",
    )


def _evaluate_case(case: dict) -> CaseEvaluation:
    results, _, _ = VerdictEngine().evaluate(
        request=AnalyzeRequest(
            raw_input=case["claim"],
            input_type="text_news",
            mock_evidence=case["evidence"],
        ),
        event=_event_fixture(case["case_id"]),
        claims=[ClaimItem(claim=case["claim"], claim_type=case["claim_type"])],
    )
    actual = results[0]
    expected = case["expected"]
    mismatches: list[str] = []
    actual_confidence = str(actual.confidence)

    if actual.verdict != expected["verdict"]:
        mismatches.append(f"verdict={actual.verdict!r} did not match expected {expected['verdict']!r}")
    if actual_confidence != expected["confidence"]:
        mismatches.append(
            f"confidence={actual_confidence!r} did not match expected {expected['confidence']!r}"
        )
    if actual.verdict in DECISIVE_VERDICTS and not actual.evidence:
        mismatches.append("decisive verdict was returned without attached evidence")
    if expected["verdict"] == "insufficient" and actual.verdict in DECISIVE_VERDICTS:
        if all(item["source_tier"] == "C" for item in case["evidence"]):
            mismatches.append("low-tier-only evidence should stay insufficient but produced a decisive verdict")
    if expected["verdict"] == "conflicting" and actual.verdict != "conflicting":
        mismatches.append("conflicting sources were collapsed instead of preserved as conflicting")

    return CaseEvaluation(
        case_id=case["case_id"],
        mismatches=mismatches,
        details={
            "actual_verdict": actual.verdict,
            "actual_confidence": actual_confidence,
        },
    )


def test_verdict_eval_regression():
    evaluations = [_evaluate_case(case) for case in VERDICT_CASES]
    summary = summarize_results("verdict_cases.json", evaluations)
    print(summary)
    if any(not item.passed for item in evaluations):
        pytest.fail(summary, pytrace=False)
