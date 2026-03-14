from __future__ import annotations

import pytest

from backend.app.models.schemas import ClaimResult, EvidenceItem, NormalizedEvent, TimelineNode
from backend.app.services.report_builder import ReportBuilder
from backend.eval_regression_tests.conftest import CaseEvaluation, load_eval_fixture, summarize_results


def _u(value: str) -> str:
    return value.encode("ascii").decode("unicode_escape")


REPORT_MODE_CASES = load_eval_fixture("report_mode_cases.json")
DECISIVE_VERDICTS = {"supported", "refuted", "conflicting"}
BOUNDARY_MARKERS = tuple(
    _u(item)
    for item in (
        r"\u4fdd\u5b88",
        r"\u4e0d\u8db3",
        r"\u4e0d\u5b8c\u6574",
        r"\u4e0d\u80fd",
        r"\u5f85\u6838",
        r"\u51b2\u7a81",
        "safe mode",
    )
)
UNKNOWN_MARKERS = tuple(
    _u(item)
    for item in (r"\u4e0d\u8db3", r"\u5f85\u6838", r"\u5c1a\u672a", r"\u672a\u77e5")
)
NEXT_STEP_MARKERS = tuple(
    _u(item)
    for item in (r"\u5efa\u8bae", r"\u8865\u5145", r"\u91cd\u8bd5", r"\u7a0d\u540e")
)
CONFLICT_MARKER = _u(r"\u51b2\u7a81")
TIMELINE_MARKER = _u(r"\u65f6\u95f4\u7ebf")
FALLBACK_MARKER = _u(r"\u4fdd\u5b88")
CONFLICT_NOTE = _u(r"\u5b58\u5728\u51b2\u7a81\u7248\u672c\uff0c\u9700\u8981\u4fdd\u7559\u8fb9\u754c\u3002")
DECISIVE_NOTE = _u(r"\u5df2\u6709\u53ef\u6838\u9a8c\u7ed3\u8bba\u3002")
PENDING_NOTE = _u(r"\u5f53\u524d\u8bc1\u636e\u4e0d\u8db3\u3002")


def _build_evidence(case_id: str, context: dict) -> list[EvidenceItem]:
    if context["evidence_grade"] == "D":
        return []
    source_tier = context["evidence_grade"] if context["evidence_grade"] in {"S", "A", "B", "C"} else "C"
    count = max(1, min(context["decidable_claim_count"] or 1, 2))
    return [
        EvidenceItem(
            title=f"{case_id} evidence {index + 1}",
            url=f"https://example.org/eval-regression/report/{case_id}/{index + 1}",
            source_name="fixed regression fixture",
            published_at=f"2026-03-{index + 1:02d}T09:00:00+08:00",
            snippet=f"{case_id} evidence snippet {index + 1}",
            relevance_reason="Fixed fixture for report-mode regression coverage.",
            source_tier=source_tier,
        )
        for index in range(count)
    ]


def _build_claim_results(case_id: str, context: dict, expected: dict, evidence: list[EvidenceItem]) -> list[ClaimResult]:
    claim_results: list[ClaimResult] = []
    decisive_left = context["decidable_claim_count"]

    if expected.get("must_not_hide_conflicts") and decisive_left > 0:
        claim_results.append(
            ClaimResult(
                claim=f"{case_id} conflicting claim",
                claim_type="fact",
                verdict="conflicting",
                confidence="medium",
                evidence=evidence[:2],
                notes=CONFLICT_NOTE,
            )
        )
        decisive_left -= 1

    verdict_cycle = (("supported", "high"), ("refuted", "high"))
    for index in range(decisive_left):
        verdict, confidence = verdict_cycle[index % len(verdict_cycle)]
        claim_results.append(
            ClaimResult(
                claim=f"{case_id} decisive claim {index + 1}",
                claim_type="fact",
                verdict=verdict,
                confidence=confidence,
                evidence=evidence[:1],
                notes=DECISIVE_NOTE,
            )
        )

    while len(claim_results) < context["claim_count"]:
        claim_results.append(
            ClaimResult(
                claim=f"{case_id} pending claim {len(claim_results) + 1}",
                claim_type="fact",
                verdict="insufficient",
                confidence="low",
                evidence=[],
                notes=PENDING_NOTE,
            )
        )

    return claim_results


def _build_timeline(case_id: str, count: int) -> list[TimelineNode]:
    node_types = ("origin", "amplification", "turn", "clarification", "peak")
    return [
        TimelineNode(
            node_type=node_types[index % len(node_types)],
            title=f"{case_id} timeline {index + 1}",
            url=f"https://example.org/eval-regression/timeline/{case_id}/{index + 1}",
            source_name="fixed regression fixture",
            published_at=f"2026-03-{index + 1:02d}T10:00:00+08:00",
            summary=f"{case_id} timeline summary {index + 1}",
            why_selected="Fixed fixture for timeline coverage.",
        )
        for index in range(count)
    ]


def _build_event(case_id: str, context: dict) -> NormalizedEvent:
    return NormalizedEvent(
        title=f"{case_id} report mode regression",
        summary=f"{case_id} regression summary",
        keywords=[case_id, "report_mode"],
        source_name="fixed regression fixture",
        source_url=f"https://example.org/eval-regression/report/{case_id}",
        published_at="2026-03-14T00:00:00+08:00",
        input_type=context["input_type"],
        mode_hint="partial",
        fallback_used=context["fallback_used"],
        fallback_reason="url_content_incomplete" if context["fallback_used"] else None,
        raw_input=f"report mode regression {case_id}",
    )


def _section_present(section: str, report) -> bool:
    combined_text = " ".join([report.final_summary, *report.risks])
    if section == "event":
        return report.event is not None
    if section == "timeline":
        return bool(report.timeline)
    if section == "claim_results":
        return bool(report.claim_results)
    if section == "final_summary":
        return bool(report.final_summary.strip())
    if section == "evidence":
        return bool(report.sources)
    if section == "unknowns":
        return any(marker in combined_text for marker in UNKNOWN_MARKERS)
    if section == "next_steps":
        return any(marker in combined_text for marker in NEXT_STEP_MARKERS)
    return False


def _evaluate_case(case: dict) -> CaseEvaluation:
    context = case["context"]
    expected = case["expected"]
    evidence = _build_evidence(case["case_id"], context)
    claim_results = _build_claim_results(case["case_id"], context, expected, evidence)
    timeline = _build_timeline(case["case_id"], context["timeline_node_count"])
    report = ReportBuilder().build(
        event=_build_event(case["case_id"], context),
        claim_results=claim_results,
        timeline=timeline,
        evidence=evidence,
        evidence_grade=context["evidence_grade"],
    )

    mismatches: list[str] = []
    combined_text = " ".join([report.final_summary, *report.risks])

    if report.mode != expected["mode"]:
        mismatches.append(f"mode={report.mode!r} did not match expected {expected['mode']!r}")

    for section in expected.get("required_sections", []):
        if not _section_present(section, report):
            mismatches.append(f"required section {section!r} was not surfaced")

    if expected.get("must_show_boundary") and not any(marker in combined_text for marker in BOUNDARY_MARKERS):
        mismatches.append("boundary language was not surfaced in summary or risks")

    if expected.get("must_not_hide_conflicts"):
        if not any(item.verdict == "conflicting" for item in report.claim_results):
            mismatches.append("fixture did not create a conflicting claim to validate conflict visibility")
        elif not any(CONFLICT_MARKER in risk for risk in report.risks):
            mismatches.append("conflicting evidence was not called out in risks")

    if expected.get("must_not_overstate_timeline") and TIMELINE_MARKER not in combined_text:
        mismatches.append("timeline boundary was not called out")

    if expected.get("must_not_output_strong_verdict"):
        if any(item.verdict in DECISIVE_VERDICTS for item in report.claim_results):
            mismatches.append("safe_mode fixture still exposed a strong verdict")

    if expected.get("must_explicitly_mark_fallback") and FALLBACK_MARKER not in combined_text:
        mismatches.append("fallback case did not explicitly mark conservative output")

    return CaseEvaluation(
        case_id=case["case_id"],
        mismatches=mismatches,
        details={"actual_mode": report.mode, "risk_count": str(len(report.risks))},
    )


def test_report_mode_eval_regression():
    evaluations = [_evaluate_case(case) for case in REPORT_MODE_CASES]
    summary = summarize_results("report_mode_cases.json", evaluations)
    print(summary)
    if any(not item.passed for item in evaluations):
        pytest.fail(summary, pytrace=False)
