"""Pure helper functions extracted from LlmAgentReasoner.

Every function here is a stateless transformation — no IO, no LLM calls, no
settings, no side effects beyond `emit_log`. The reasoner class keeps thin
`self._x(...)` methods that delegate here so existing call-sites and tests
(which reach for `reasoner._clean_optional_string`, etc.) keep working.

Splitting these out shrinks agent_reasoner.py's LlmAgentReasoner class by
~200 lines and lets us unit-test the transformations directly without
needing a full reasoner instance.
"""
from __future__ import annotations

import re
from typing import Any

from backend.app.models.schemas import ConfidenceValue, PossibilityItem
from backend.app.services.contract_utils import loads_lenient_json
from backend.app.services.progress import emit_log

ALLOWED_CLAIM_TYPES = {"fact", "opinion", "prediction", "unverifiable"}
ALLOWED_VERDICTS = {"supported", "refuted", "insufficient", "conflicting"}
ALLOWED_CONFIDENCE = {"high", "medium", "low"}
ALLOWED_TIMELINE_TYPES = {"origin", "amplification", "peak", "turn", "clarification"}


def clean_optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    compact = re.sub(r"\s+", " ", value).strip()
    return compact or None


def normalize_follow_up_query(value: Any) -> str | None:
    cleaned = clean_optional_string(value)
    if not cleaned:
        return None
    tokens = re.findall(r"[A-Za-z0-9%._-]{2,}|[\u4e00-\u9fff]{2,16}", cleaned)
    if not tokens:
        return None
    return " ".join(tokens[:10])


def normalize_claim_type(value: Any) -> str:
    cleaned = clean_optional_string(value)
    if cleaned in ALLOWED_CLAIM_TYPES:
        return cleaned
    return "fact"


def normalize_verdict(value: Any) -> str:
    cleaned = clean_optional_string(value)
    if cleaned in ALLOWED_VERDICTS:
        return cleaned
    return "insufficient"


def normalize_confidence(value: Any) -> ConfidenceValue:
    cleaned = clean_optional_string(value)
    if cleaned in ALLOWED_CONFIDENCE:
        return cleaned
    return "low"


def clamp_probability(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        cleaned = clean_optional_string(value)
        if cleaned is None:
            return None
        try:
            value = float(cleaned.rstrip("%"))
        except ValueError:
            return None
    return max(0.0, min(100.0, float(value)))


def normalize_probability_basis(value: Any, *, has_evidence: bool) -> str:
    cleaned = clean_optional_string(value)
    if cleaned in {"evidence", "prior"}:
        # Never let the model claim "evidence" basis when nothing grounded it —
        # keeps the probability honest about where the number came from.
        if cleaned == "evidence" and not has_evidence:
            return "prior"
        return cleaned
    return "evidence" if has_evidence else "prior"


def normalize_probability(
    raw_probability: Any, raw_basis: Any, *, has_evidence: bool
) -> tuple[float | None, str | None]:
    probability = clamp_probability(raw_probability)
    if probability is None:
        return None, None
    basis = normalize_probability_basis(raw_basis, has_evidence=has_evidence)
    return probability, basis


def likelihood_from_probability(probability: float | None) -> str:
    if probability is None:
        return "low"
    if probability >= 66:
        return "high"
    if probability >= 33:
        return "medium"
    return "low"


def normalize_timeline_type(value: Any) -> str:
    cleaned = clean_optional_string(value)
    if cleaned in ALLOWED_TIMELINE_TYPES:
        return cleaned
    return "origin"


def normalize_claim_text(value: Any) -> str | None:
    cleaned = clean_optional_string(value)
    if not cleaned:
        return None
    compact = re.sub(r"\s+", " ", cleaned).strip().rstrip("。！？?!；; ")
    if not compact:
        return None
    return f"{compact}。"


def normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    ordered: list[str] = []
    seen: set[str] = set()
    for item in value:
        cleaned = clean_optional_string(item)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)
    return ordered


def extract_json_payload(content: str) -> dict[str, Any] | None:
    return loads_lenient_json(content)


def json_with_key_usable(key: str):
    """Build an is_valid callback that accepts a completion only when the lenient
    parser recovers a dict containing `key`. A truncated planner response (stream
    cut before the decision field) fails this and triggers a retry instead of
    silently giving up — which, for a planner, means prematurely ending the
    investigation loop."""
    def _check(content: str) -> bool:
        payload = extract_json_payload(content)
        return isinstance(payload, dict) and key in payload
    return _check


def synthesis_content_usable(content: str) -> bool:
    """A synthesis completion is worth keeping only if the lenient parser can
    recover an object with at least one claim. A truncated fragment (stream cut
    mid-JSON) or a claim-less object fails this, triggering a retry rather than a
    silent drop to the rule fallback."""
    payload = extract_json_payload(content)
    if not isinstance(payload, dict):
        return False
    claims = payload.get("claims")
    return isinstance(claims, list) and len(claims) > 0


def build_scenarios(scenarios_payload: Any) -> list[PossibilityItem]:
    """Parse the LLM's mutually-exclusive whole-message scenarios into
    PossibilityItem, clamping probabilities and renormalizing to ~100 when the
    model's numbers drift. Returns [] when nothing parseable, so the caller
    falls back to the rule-based possibilities."""
    if not isinstance(scenarios_payload, list):
        return []
    parsed: list[dict[str, Any]] = []
    for item in scenarios_payload:
        if not isinstance(item, dict):
            continue
        label = clean_optional_string(item.get("label")) or clean_optional_string(item.get("scenario"))
        if not label:
            continue
        probability = clamp_probability(item.get("probability"))
        basis_value = clean_optional_string(item.get("basis"))
        basis = basis_value if basis_value in {"evidence", "prior"} else None
        summary = clean_optional_string(item.get("summary")) or label
        parsed.append(
            {"scenario": label, "probability": probability, "basis": basis, "summary": summary}
        )
        if len(parsed) >= 4:
            break
    if not parsed:
        return []

    total = sum(entry["probability"] for entry in parsed if entry["probability"] is not None)
    counted = [entry for entry in parsed if entry["probability"] is not None]
    if counted and (total <= 0 or abs(total - 100.0) > 1.0):
        emit_log(
            stage_key="agent_synthesis",
            level="info",
            title="情形分布已归一化",
            summary=f"scenarios 概率合计为 {round(total, 1)}，已按比例缩放到 100。",
            details=[],
        )
        if total > 0:
            for entry in counted:
                entry["probability"] = round(entry["probability"] / total * 100.0, 1)

    return [
        PossibilityItem(
            scenario=entry["scenario"],
            likelihood=likelihood_from_probability(entry["probability"]),
            probability=entry["probability"],
            basis=entry["basis"],
            summary=entry["summary"],
        )
        for entry in parsed
    ]
