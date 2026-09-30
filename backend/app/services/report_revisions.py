from __future__ import annotations

import json
import unicodedata
from collections import defaultdict, deque

from backend.app.models.schemas import AnalysisRunComparison, ClaimChange, ClaimResult, Report


def normalize_claim(claim: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", claim).casefold().split())


def _evidence_urls(claim: ClaimResult) -> set[str]:
    return {evidence.url.strip() for evidence in claim.evidence if evidence.url.strip()}


def _source_urls(report: Report, indices: set[int] | None = None) -> set[str]:
    return {
        url for index, claim in enumerate(report.claim_results)
        if indices is None or index in indices
        for url in _evidence_urls(claim)
    }


def _evidence_contents(claim: ClaimResult) -> set[str]:
    return {json.dumps(evidence.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) for evidence in claim.evidence}


def _captured_contents(report: Report, indices: set[int] | None = None) -> dict[tuple[str, str], set[str]]:
    cited_urls = _source_urls(report, indices)
    contents: dict[tuple[str, str], set[str]] = defaultdict(set)
    for snapshot in report.evidence_snapshots:
        if snapshot.url in cited_urls and snapshot.kind == "page_text":
            contents[snapshot.url, snapshot.extractor].add(snapshot.text_sha256)
    return contents


def compare_reports(
    run_id: str,
    parent_run_id: str,
    before: Report,
    after: Report,
    reviewed_indices: list[int],
) -> AnalysisRunComparison:
    remaining: dict[str, deque[tuple[int, ClaimResult]]] = defaultdict(deque)
    for index, claim in enumerate(after.claim_results):
        remaining[normalize_claim(claim.claim)].append((index, claim))
    selected = set(reviewed_indices) if reviewed_indices else set(range(len(before.claim_results)))
    consumed = set()
    changes = []
    for index, previous in enumerate(before.claim_results):
        if index not in selected:
            changes.append(ClaimChange(
                claim=previous.claim, kind="not_rechecked", before_verdict=previous.verdict, after_verdict=None,
            ))
            continue
        matches = remaining[normalize_claim(previous.claim)]
        if not matches:
            changes.append(ClaimChange(
                claim=previous.claim, kind="removed", before_verdict=previous.verdict, after_verdict=None,
                removed_evidence_urls=sorted(_evidence_urls(previous)),
            ))
            continue
        current_index, current = matches.popleft()
        consumed.add(current_index)
        added_urls = sorted(_evidence_urls(current) - _evidence_urls(previous))
        removed_urls = sorted(_evidence_urls(previous) - _evidence_urls(current))
        if (
            previous.verdict != current.verdict or added_urls or removed_urls
            or previous.confidence != current.confidence or previous.truth_probability != current.truth_probability
            or previous.correction != current.correction
            or previous.claim_type != current.claim_type or previous.evidence_gaps != current.evidence_gaps
            or _evidence_contents(previous) != _evidence_contents(current)
        ):
            changes.append(ClaimChange(
                claim=current.claim, kind="changed", before_verdict=previous.verdict, after_verdict=current.verdict,
                added_evidence_urls=added_urls, removed_evidence_urls=removed_urls,
            ))
    for index, current in enumerate(after.claim_results):
        if index not in consumed:
            changes.append(ClaimChange(
                claim=current.claim, kind="added", before_verdict=None, after_verdict=current.verdict,
                added_evidence_urls=sorted(_evidence_urls(current)),
            ))
    before_contents = _captured_contents(before, selected)
    after_contents = _captured_contents(after, consumed)
    changed_sources = sorted({url for url, extractor in before_contents.keys() & after_contents.keys()
                              if before_contents[url, extractor] != after_contents[url, extractor]})
    return AnalysisRunComparison(
        run_id=run_id, parent_run_id=parent_run_id, changes=changes,
        added_source_urls=sorted(_source_urls(after) - _source_urls(before, selected)),
        removed_source_urls=sorted(_source_urls(before, selected) - _source_urls(after)),
        changed_source_urls=changed_sources,
    )
