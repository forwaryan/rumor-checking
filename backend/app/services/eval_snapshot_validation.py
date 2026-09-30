"""Strict validation for internal replay snapshots, including quarantined data."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

VERDICTS = {"supported", "refuted", "insufficient", "conflicting"}
CLAIM_TYPES = {"fact", "opinion", "prediction", "unverifiable"}


def validate_snapshot(data: object, *, path: Path) -> None:
    def require(condition: bool, field: str, message: str) -> None:
        if not condition:
            raise ValueError(f"{path}: {field}: {message}")

    def text(value: object) -> bool:
        return isinstance(value, str) and bool(value.strip())

    require(isinstance(data, dict), "snapshot", "must be an object")
    required = {"case_id", "recorded_at", "raw_input", "retrieval_results", "expected_claims", "metadata"}
    require(set(data) == required, "snapshot", f"requires exactly these fields: {sorted(required)}")
    for field in ("case_id", "recorded_at", "raw_input"):
        require(text(data[field]), field, "must be nonempty text")
    case_id = data["case_id"]
    require(
        case_id != "." and ".." not in case_id
        and all(character.isalnum() or character in "_-." for character in case_id),
        "case_id", "must be a filename-safe identifier without path components",
    )
    try:
        datetime.fromisoformat(data["recorded_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{path}: recorded_at: invalid ISO timestamp") from exc
    metadata = data["metadata"]
    require(isinstance(metadata, dict), "metadata", "must be an object")
    if "review_status" in metadata:
        require(metadata["review_status"] in ("approved", "reviewed", "quarantined"),
                "metadata.review_status", "must be approved or quarantined (legacy reviewed also accepted)")
    quarantined = metadata.get("review_status") == "quarantined"
    if quarantined:
        require(text(metadata.get("review_reason")), "metadata.review_reason", "required for quarantine")
    results = data["retrieval_results"]
    require(isinstance(results, list), "retrieval_results", "must be an array")
    result_ids: set[str] = set()
    retrieval_urls: set[str] = set()

    def validate_published_at(value: object, field: str) -> None:
        require(isinstance(value, str), field, "must be text; empty is allowed")
        if value:
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(f"{path}: {field}: must be empty or an ISO date/timestamp") from exc

    for index, result in enumerate(results):
        field = f"retrieval_results[{index}]"
        require(isinstance(result, dict), field, "must be an object")
        for key in ("result_id", "url"):
            require(text(result.get(key)), f"{field}.{key}", "must be nonempty text")
        require(result["result_id"] not in result_ids, f"{field}.result_id", "duplicate result_id")
        result_ids.add(result["result_id"])
        retrieval_urls.add(result["url"])
        for key in ("title", "snippet", "source_name", "published_at", "origin_id"):
            if key in result:
                require(isinstance(result[key], str), f"{field}.{key}", "must be text; empty is allowed")
        validate_published_at(result.get("published_at", ""), f"{field}.published_at")
        if "source_tier" in result:
            require(result["source_tier"] in ("S", "A", "B", "C"), f"{field}.source_tier", "invalid tier")

    def evidence_urls(evidence: object, field: str) -> set[str]:
        require(isinstance(evidence, list), field, "must be an array")
        urls: set[str] = set()
        for index, item in enumerate(evidence):
            item_field = f"{field}[{index}]"
            require(isinstance(item, dict), item_field, "must be an object")
            require(text(item.get("url")), f"{item_field}.url", "must be nonempty text")
            require(item["url"] in retrieval_urls, f"{item_field}.url", "absent from retrieval_results")
            if "title" in item:
                require(isinstance(item["title"], str), f"{item_field}.title", "must be text")
            validate_published_at(item.get("published_at", ""), f"{item_field}.published_at")
            urls.add(item["url"])
        return urls

    claims = data["expected_claims"]
    require(isinstance(claims, list) and bool(claims), "expected_claims", "must be a nonempty array")
    for index, claim in enumerate(claims):
        field = f"expected_claims[{index}]"
        require(isinstance(claim, dict), field, "must be an object")
        require(text(claim.get("claim")), f"{field}.claim", "must be nonempty text")
        require(isinstance(claim.get("verdict"), str) and claim["verdict"] in VERDICTS,
                f"{field}.verdict", "invalid verdict")
        require(isinstance(claim.get("claim_type", "fact"), str)
                and claim.get("claim_type", "fact") in CLAIM_TYPES, f"{field}.claim_type", "invalid claim_type")
        if "confidence" in claim:
            require(claim["confidence"] in ("high", "medium", "low"), f"{field}.confidence", "invalid confidence")
        urls = evidence_urls(claim.get("evidence", []), f"{field}.evidence")
        if "evidence_sets" in claim:
            groups = claim["evidence_sets"]
            require(isinstance(groups, list), f"{field}.evidence_sets", "must be an array")
            require(bool(groups) or claim["verdict"] == "insufficient", f"{field}.evidence_sets",
                    "must be nonempty for non-insufficient claims")
            require(bool(groups) or not urls, f"{field}.evidence_sets",
                    "empty groups conflict with nonempty legacy evidence")
            for group_index, group in enumerate(groups):
                group_field = f"{field}.evidence_sets[{group_index}]"
                group_urls = evidence_urls(group, group_field)
                require(bool(group_urls), group_field, "evidence groups must be nonempty")
                urls.update(group_urls)
        require(bool(urls) or claim["verdict"] == "insufficient" or quarantined,
                f"{field}.evidence", "non-insufficient gold must include evidence")
        evaluation = claim.get("evaluation", {})
        require(isinstance(evaluation, dict), f"{field}.evaluation", "must be an object")
        for key in ("score_confidence", "require_high_trust", "require_dated_evidence"):
            if key in evaluation:
                require(isinstance(evaluation[key], bool), f"{field}.evaluation.{key}", "must be boolean")
        if "min_independent_sources" in evaluation:
            minimum = evaluation["min_independent_sources"]
            require(type(minimum) is int and minimum >= 0,
                    f"{field}.evaluation.min_independent_sources", "must be a nonnegative integer")
        if "fresh_after" in evaluation:
            fresh_after = evaluation["fresh_after"]
            require(text(fresh_after), f"{field}.evaluation.fresh_after", "must be an ISO date")
            try:
                date.fromisoformat(fresh_after)
            except ValueError as exc:
                raise ValueError(f"{path}: {field}.evaluation.fresh_after: invalid ISO date") from exc
