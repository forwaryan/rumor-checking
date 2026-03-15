from __future__ import annotations

from backend.app.models.schemas import ClaimItem, NormalizedEvent
from backend.app.services.claim_extractor import ClaimExtractor


def test_claim_extractor_splits_compound_question_into_multiple_claims():
    extractor = ClaimExtractor()
    event = NormalizedEvent(
        summary="某女主播脑出血去世，平台还封锁消息是真是假",
        input_type="question_only",
        raw_input="某女主播脑出血去世，平台还封锁消息是真是假？",
    )

    claims = extractor.extract(
        event,
        provider_claims=[
            ClaimItem(claim="某女主播脑出血去世。", claim_type="fact"),
            ClaimItem(claim="平台封锁消息。", claim_type="fact"),
        ],
    )

    assert len(claims) >= 2
    assert any("脑出血去世" in item.claim for item in claims)
    assert any("平台还封锁消息" in item.claim or "平台封锁消息" in item.claim for item in claims)
