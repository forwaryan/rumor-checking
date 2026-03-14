from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

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
