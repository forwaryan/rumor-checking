import pytest
from pydantic import ValidationError

from backend.app.models.schemas import AnalysisRun, AnalysisRunEvent, ClaimResult, EvidenceItem


def _evidence_payload() -> dict:
    return {
        "title": "Official clarification",
        "url": "https://example.com/clarification",
        "source_name": "Example authority",
        "published_at": "2026-08-23T12:00:00+08:00",
        "snippet": "The claim is false.",
        "relevance_reason": "Direct clarification",
    }


def test_evidence_stance_rejects_unknown_values():
    with pytest.raises(ValidationError):
        EvidenceItem(**_evidence_payload(), stance="unknown")


def test_claim_correction_requires_public_shape():
    with pytest.raises(ValidationError):
        ClaimResult(
            claim="Example claim",
            claim_type="fact",
            verdict="refuted",
            confidence="high",
            evidence=[],
            notes="Corrected by an official source.",
            correction={"actual": "Corrected statement"},
        )


@pytest.mark.parametrize("event_id", [0, -1])
def test_run_event_cursor_must_be_positive(event_id):
    with pytest.raises(ValidationError):
        AnalysisRunEvent(event_id=event_id, event={"type": "complete"})


@pytest.mark.parametrize("overrides", [{"run_id": "../run"}, {"status": "supported"}, {"last_event_id": -1}])
def test_run_contract_keeps_execution_state_separate_from_verdict(overrides):
    payload = {
        "run_id": "a" * 32,
        "status": "completed",
        "created_at": "2026-09-13T00:00:00+00:00",
        "updated_at": "2026-09-13T00:00:00+00:00",
        "last_event_id": 2,
        "mode": "deep",
        "input_preview": "A claim",
        "raw_input": "A claim",
        **overrides,
    }
    with pytest.raises(ValidationError):
        AnalysisRun(**payload)
