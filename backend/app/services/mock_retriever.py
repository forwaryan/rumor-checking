from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations
from pathlib import Path
from typing import Optional

from backend.app.core.config import Settings, get_settings
from backend.app.models.schemas import NormalizedEvent
from backend.app.services.contract_utils import ensure_datetime_string
from backend.app.services.retrieval_models import RetrievalBundle, SearchResult

REPOST_PREFIXES = (
    "\u8f6c\u8f7d",
    "\u8f6c\u53d1",
    "\u805a\u5408\u9875",
    "\u805a\u5408",
    "\u642c\u8fd0",
)
REPOST_SOURCE_MARKERS = ("\u805a\u5408", "\u5feb\u8baf", "\u8f6c\u53d1")
REPOST_LABEL = "repost"
DUPLICATE_LABEL = "duplicate"
NEAR_DUPLICATE_LABEL = "near_duplicate"


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
            return RetrievalBundle(query=query_text)

        canonical_results = self._merge_results(case.results)
        return RetrievalBundle(
            query=case.query,
            matched_case_id=case.case_id,
            mode_hint=case.expected_mode_hint,
            raw_results=tuple(sorted(case.results, key=self._chronological_sort_key)),
            canonical_results=tuple(sorted(canonical_results, key=self._chronological_sort_key)),
            expected_origin_result_id=case.expected_origin_result_id,
            expected_turning_point_result_id=case.expected_turning_point_result_id,
        )

    def _match_case(self, query_text: str) -> Optional[RetrievalCase]:
        compact_query = self._compact(query_text)
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
        if self._compact(case.query) in compact_query:
            return 100
        return sum(1 for term in case.query_terms if term in compact_query)

    def _merge_results(self, results: tuple[SearchResult, ...]) -> list[SearchResult]:
        parent = {item.result_id: item.result_id for item in results}

        def find(result_id: str) -> str:
            while parent[result_id] != result_id:
                parent[result_id] = parent[parent[result_id]]
                result_id = parent[result_id]
            return result_id

        def union(left_id: str, right_id: str) -> None:
            left_root = find(left_id)
            right_root = find(right_id)
            if left_root != right_root:
                parent[right_root] = left_root

        for item in results:
            if item.duplicate_of and item.duplicate_of in parent:
                union(item.result_id, item.duplicate_of)

        for left, right in combinations(results, 2):
            if self._classify_relation(left, right) is not None:
                union(left.result_id, right.result_id)

        groups: dict[str, list[SearchResult]] = defaultdict(list)
        for item in results:
            groups[find(item.result_id)].append(item)

        merged_results: list[SearchResult] = []
        for group_items in groups.values():
            if len(group_items) == 1:
                item = group_items[0]
                merged_results.append(item.with_merge_metadata(canonical_result_id=item.result_id))
                continue

            canonical = max(group_items, key=lambda item: self._canonical_sort_key(item, group_items))
            merged_ids: list[str] = []
            merged_notes: list[str] = []
            for item in sorted(group_items, key=self._chronological_sort_key):
                if item.result_id == canonical.result_id:
                    continue
                merged_ids.append(item.result_id)
                relation = self._classify_relation(item, canonical) or item.duplicate_reason or NEAR_DUPLICATE_LABEL
                merged_notes.append(f"{item.result_id}:{relation}:{item.source_name}")

            merged_results.append(
                canonical.with_merge_metadata(
                    canonical_result_id=canonical.result_id,
                    merged_result_ids=tuple(merged_ids),
                    merged_notes=tuple(merged_notes),
                )
            )

        return merged_results

    def _canonical_sort_key(self, item: SearchResult, group_items: list[SearchResult]) -> tuple[int, int, int, float]:
        explicit_targets = sum(1 for group_item in group_items if group_item.duplicate_of == item.result_id)
        keep_original_bonus = 0 if self._looks_like_repost(item.title, item.source_name) else 1
        return (
            item.tier_weight,
            explicit_targets,
            keep_original_bonus,
            -item.published_dt.timestamp(),
        )

    def _classify_relation(self, left: SearchResult, right: SearchResult) -> Optional[str]:
        if left.result_id == right.result_id:
            return None
        if left.duplicate_of == right.result_id or right.duplicate_of == left.result_id:
            is_repost = self._looks_like_repost(left.title, left.source_name) or self._looks_like_repost(right.title, right.source_name)
            return REPOST_LABEL if is_repost else DUPLICATE_LABEL
        if self._compact(left.url) == self._compact(right.url):
            return DUPLICATE_LABEL
        if self._normalize_title(left.title) == self._normalize_title(right.title):
            is_repost = self._looks_like_repost(left.title, left.source_name) or self._looks_like_repost(right.title, right.source_name)
            return REPOST_LABEL if is_repost else DUPLICATE_LABEL
        if left.published_at[:10] != right.published_at[:10]:
            return None
        if self._titles_overlap(left.title, right.title):
            return NEAR_DUPLICATE_LABEL
        return None

    def _titles_overlap(self, left_title: str, right_title: str) -> bool:
        left_terms = set(self._extract_terms(self._normalize_title(left_title)))
        right_terms = set(self._extract_terms(self._normalize_title(right_title)))
        if not left_terms or not right_terms:
            return False
        shared = left_terms & right_terms
        if len(shared) >= 3:
            return True
        shorter = min(len(left_terms), len(right_terms))
        return shorter > 0 and len(shared) / shorter >= 0.75

    def _normalize_title(self, title: str) -> str:
        compact = title.strip().lower()
        compact = re.sub(
            r"^(\u8f6c\u8f7d|\u8f6c\u53d1|\u805a\u5408\u9875|\u805a\u5408|\u7f51\u4f20|\u7206\u6599)[:?\s-]*",
            "",
            compact,
        )
        return re.sub(r"[\W_]+", "", compact)

    def _extract_terms(self, text: str) -> list[str]:
        return re.findall(r"[a-z0-9%]+|[\u4e00-\u9fff]{2,12}", text)

    def _looks_like_repost(self, title: str, source_name: str) -> bool:
        return title.startswith(REPOST_PREFIXES) or any(prefix in source_name for prefix in REPOST_SOURCE_MARKERS)

    def _compact(self, text: str) -> str:
        return re.sub(r"\s+", "", text).lower()

    def _chronological_sort_key(self, item: SearchResult) -> tuple[str, int, str]:
        return (item.published_at, -item.tier_weight, item.result_id)


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
