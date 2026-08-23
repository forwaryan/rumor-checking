import pytest
from pydantic import ValidationError

from backend.app.models.schemas import ClaimResult, EvidenceItem


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
