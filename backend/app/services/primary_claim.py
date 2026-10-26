from __future__ import annotations

from collections.abc import Sequence

from backend.app.models.schemas import ClaimResult
from backend.app.services.entity_anchor import KNOWN_BRANDS, extract_subject_anchors


def primary_fact_claim(original_input: str, claims: Sequence[ClaimResult]) -> ClaimResult | None:
    """Prefer a fact about the named subject over a broader background fact."""
    facts = [item for item in claims if item.claim_type == "fact"]
    if not facts:
        return None
    anchors = extract_subject_anchors(original_input)
    for anchor in anchors:
        if anchor not in KNOWN_BRANDS and not anchor.endswith(("公司", "集团", "生物", "科技", "医院", "学校", "大学")):
            continue
        for item in facts:
            if anchor in extract_subject_anchors(item.claim):
                return item
    return facts[0]
