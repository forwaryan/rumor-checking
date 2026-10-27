from __future__ import annotations

import re
from collections.abc import Sequence

from backend.app.models.schemas import ClaimResult
from backend.app.services.entity_anchor import ACTION_MARKERS, KNOWN_BRANDS, TEMPORAL_ADVERBS, extract_subject_anchors


def primary_fact_claim(original_input: str, claims: Sequence[ClaimResult]) -> ClaimResult | None:
    """Prefer the asked subject, action and timeframe over related background facts."""
    facts = [item for item in claims if item.claim_type == "fact"]
    if not facts:
        return None
    anchors = extract_subject_anchors(original_input)
    recent = any(marker in original_input for marker in TEMPORAL_ADVERBS)
    actions = [marker for marker in ACTION_MARKERS if marker in original_input]
    input_terms = set(re.findall(r"[一-鿿]{2}|[A-Za-z0-9]{2,}", original_input))

    def relevance(item: ClaimResult) -> tuple[int, int]:
        claim_terms = set(re.findall(r"[一-鿿]{2}|[A-Za-z0-9]{2,}", item.claim))
        return len(input_terms & claim_terms), -len(claim_terms)
    for anchor in anchors:
        if anchor not in KNOWN_BRANDS and not anchor.endswith(("公司", "集团", "生物", "科技", "医院", "学校", "大学")):
            continue
        matching = [item for item in facts if anchor in extract_subject_anchors(item.claim)]
        if matching:
            return max(
                matching,
                key=lambda item: (
                    recent and any(marker in item.claim for marker in TEMPORAL_ADVERBS),
                    any(action in item.claim for action in actions),
                    relevance(item),
                ),
            )
    return max(facts, key=relevance)
