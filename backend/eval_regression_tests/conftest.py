from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from backend.app.models.schemas import ReportProvenance

REPO_ROOT = Path(__file__).resolve().parents[2]
EVALS_ROOT = REPO_ROOT / "evals" / "minimal_v1"


@dataclass
class CaseEvaluation:
    case_id: str
    mismatches: list[str] = field(default_factory=list)
    details: dict[str, str] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.mismatches


def load_eval_fixture(filename: str):
    return json.loads((EVALS_ROOT / filename).read_text(encoding="utf-8-sig"))


def build_report_provenance(*, context: dict, evidence_count: int, timeline_count: int) -> ReportProvenance:
    evidence_source = "retrieval_live" if evidence_count else "none"
    if timeline_count == 0:
        timeline_source = "none"
    elif context["evidence_grade"] in {"A", "S"} and context["decidable_claim_count"] >= 2 and not context["fallback_used"]:
        timeline_source = "retrieval"
    else:
        timeline_source = "input_seed"

    fallback_reasons = ["url_content_incomplete"] if context["fallback_used"] else []
    return ReportProvenance(
        source_type="backend_live",
        event_source="input_normalized",
        claim_source="rule",
        evidence_source=evidence_source,
        timeline_source=timeline_source,
        provider_used=False,
        fallback_used=context["fallback_used"],
        fallback_reasons=fallback_reasons,
    )


@pytest.fixture
def report_provenance_factory():
    return build_report_provenance


def summarize_results(label: str, evaluations: list[CaseEvaluation]) -> str:
    total = len(evaluations)
    passed = sum(1 for item in evaluations if item.passed)
    lines = [f"{label} pass rate: {passed}/{total} passed"]
    failures = [item for item in evaluations if not item.passed]
    if not failures:
        lines.append("Failed cases: none")
        return "\n".join(lines)

    lines.append("Failed cases:")
    for item in failures:
        detail_text = ""
        if item.details:
            detail_text = " [" + ", ".join(f"{key}={value}" for key, value in item.details.items()) + "]"
        lines.append(f"- {item.case_id}: {'; '.join(item.mismatches)}{detail_text}")
    return "\n".join(lines)
