from __future__ import annotations

import re
from collections import Counter, defaultdict, deque

from backend.app.models.schemas import ClaimItem, ClaimResult

_REVIEW_CLAIM_KEY = re.compile(r"[\s，。！？?!；;:：]")


def review_claim_items(request) -> list[ClaimItem]:
    texts = request.request_context.get("review_claim_texts", [])
    if not isinstance(texts, list):
        return []
    types = request.request_context.get("review_claim_types", [])
    selected = []
    for index, text in enumerate(texts):
        if not isinstance(text, str) or not text.strip():
            continue
        claim_type = types[index] if isinstance(types, list) and index < len(types) else None
        if not isinstance(claim_type, str) or claim_type not in {"fact", "opinion", "prediction", "unverifiable"}:
            claim_type = "unverifiable" if "review_claim_types" in request.request_context else "fact"
        selected.append(ClaimItem(claim=text.strip(), claim_type=claim_type))
    return selected[:50]


def select_review_claims(request, claims: list[ClaimItem]) -> list[ClaimItem]:
    """Apply the parent report's claim selection at the extraction boundary."""
    return review_claim_items(request) or claims


def validate_review_claim_scope(request, claims: list[ClaimItem]) -> None:
    """Allow targeted re-judgment, but never evaluate claims outside a recheck."""
    selected = review_claim_items(request)
    if not selected:
        return
    allowed = Counter((item.claim, item.claim_type) for item in selected)
    submitted = Counter((item.claim, item.claim_type) for item in claims)
    if submitted - allowed:
        raise ValueError("Claims must belong to the selected review scope.")


def restrict_review_results(results: list[ClaimResult], request) -> list[ClaimResult]:
    selected = review_claim_items(request)
    if not selected:
        return results
    indexed: dict[tuple[str, str], deque[ClaimResult]] = defaultdict(deque)
    for result in results:
        key = (_REVIEW_CLAIM_KEY.sub("", result.claim).lower(), result.claim_type)
        indexed[key].append(result)
    restricted = []
    for item in selected:
        key = (_REVIEW_CLAIM_KEY.sub("", item.claim).lower(), item.claim_type)
        matched = indexed[key].popleft() if indexed[key] else None
        result = matched or ClaimResult(
            claim=item.claim, claim_type=item.claim_type, verdict="insufficient", confidence="low",
            notes="本轮仅复核所选声明；当前运行尚未产出可追溯的判定。", evidence=[],
        )
        updates = {"claim": item.claim, "claim_type": item.claim_type}
        if item.claim_type != "fact":
            updates.update(verdict="insufficient", confidence="low", truth_probability=None,
                           probability_basis=None, correction=None, evidence_gaps=[],
                           notes="本轮保留原声明类型；观点、预测及不可核实声明不作事实真假强判。")
        restricted.append(result.model_copy(update=updates))
    return restricted
