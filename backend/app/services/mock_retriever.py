from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from backend.app.core.config import Settings, get_settings
from backend.app.models.schemas import NormalizedEvent
from backend.app.services.contract_utils import ensure_datetime_string
from backend.app.services.retrieval_deduper import chronological_sort_key, compact_text, merge_search_results
from backend.app.services.retrieval_models import RetrievalBundle, SearchResult


@dataclass(frozen=True)
class RetrievalCase:
    case_id: str
    query: str
    query_terms: tuple[str, ...]
    results: tuple[SearchResult, ...]
    min_related_results: int
    min_high_trust_results: int
    expected_origin_result_id: Optional[str]
    expected_turning_point_result_id: Optional[str]
    expected_mode_hint: str


class MockRetriever:
    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

    def retrieve_for_event(self, event: NormalizedEvent) -> RetrievalBundle:
        query_text = " ".join(
            part
            for part in [
                event.raw_input,
                event.title,
                event.summary,
                " ".join(event.keywords),
            ]
            if part
        )
        return self.retrieve(query_text)

    def retrieve(self, query_text: str) -> RetrievalBundle:
        case = self._match_case(query_text)
        if case is None:
            return RetrievalBundle(query=query_text, provider_name="mock")

        canonical_results = merge_search_results(case.results)
        return RetrievalBundle(
            query=case.query,
            matched_case_id=case.case_id,
            mode_hint=case.expected_mode_hint,
            raw_results=tuple(sorted(case.results, key=chronological_sort_key)),
            canonical_results=tuple(sorted(canonical_results, key=chronological_sort_key)),
            expected_origin_result_id=case.expected_origin_result_id,
            expected_turning_point_result_id=case.expected_turning_point_result_id,
            provider_name="mock",
        )

    def _match_case(self, query_text: str) -> Optional[RetrievalCase]:
        compact_query = compact_text(query_text)
        best_case: Optional[RetrievalCase] = None
        best_score = 0
        for case in _load_cases(self.settings.evals_root):
            score = self._score_case_match(compact_query, case)
            if score > best_score:
                best_case = case
                best_score = score

        if best_case is None or best_score < 2:
            return None
        return best_case

    def _score_case_match(self, compact_query: str, case: RetrievalCase) -> int:
        if compact_text(case.query) in compact_query:
            return 100
        return sum(1 for term in case.query_terms if term in compact_query)


@lru_cache()
def _load_cases(evals_root: Path) -> tuple[RetrievalCase, ...]:
    payload = json.loads((evals_root / "retrieval_cases.json").read_text(encoding="utf-8-sig"))
    cases: list[RetrievalCase] = []
    for raw_case in payload:
        query = raw_case["query"]
        results = tuple(
            SearchResult(
                case_id=raw_case["case_id"],
                query=query,
                result_id=item["result_id"],
                title=item["title"],
                url=item["url"],
                source_name=item["source_name"],
                published_at=ensure_datetime_string(item["published_at"]),
                snippet=item["snippet"],
                source_tier=item["source_tier"],
                duplicate_of=item.get("is_duplicate_of"),
                provider_name="mock",
            )
            for item in raw_case["mock_search_results"]
        )
        expected = raw_case["expected"]
        cases.append(
            RetrievalCase(
                case_id=raw_case["case_id"],
                query=query,
                query_terms=tuple(term for term in re.split(r"\s+", query) if len(term) >= 2),
                results=results,
                min_related_results=expected["min_related_results"],
                min_high_trust_results=expected["min_high_trust_results"],
                expected_origin_result_id=expected["expected_origin_result_id"],
                expected_turning_point_result_id=expected["expected_turning_point_result_id"],
                expected_mode_hint=expected["expected_mode_hint"],
            )
        )
    return tuple(cases)
