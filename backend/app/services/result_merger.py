from __future__ import annotations

import re
from itertools import combinations
from typing import Optional, Sequence

from backend.app.services.retrieval_models import SearchResult

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


class SearchResultMerger:
    def merge(self, results: Sequence[SearchResult]) -> list[SearchResult]:
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
            if self.classify_relation(left, right) is not None:
                union(left.result_id, right.result_id)

        groups: dict[str, list[SearchResult]] = {}
        for item in results:
            groups.setdefault(find(item.result_id), []).append(item)

        merged_results: list[SearchResult] = []
        for group_items in groups.values():
            if len(group_items) == 1:
                item = group_items[0]
                merged_results.append(item.with_merge_metadata(canonical_result_id=item.result_id))
                continue

            canonical = max(group_items, key=lambda item: self._canonical_sort_key(item, group_items))
            merged_ids: list[str] = []
            merged_notes: list[str] = []
            for item in sorted(group_items, key=self.chronological_sort_key):
                if item.result_id == canonical.result_id:
                    continue
                merged_ids.append(item.result_id)
                relation = self.classify_relation(item, canonical) or item.duplicate_reason or NEAR_DUPLICATE_LABEL
                merged_notes.append(f"{item.result_id}:{relation}:{item.source_name}")

            merged_results.append(
                canonical.with_merge_metadata(
                    canonical_result_id=canonical.result_id,
                    merged_result_ids=tuple(merged_ids),
                    merged_notes=tuple(merged_notes),
                )
            )

        return merged_results

    def classify_relation(self, left: SearchResult, right: SearchResult) -> Optional[str]:
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

    def chronological_sort_key(self, item: SearchResult) -> tuple[str, int, str]:
        return (item.published_at, -item.tier_weight, item.result_id)

    def _canonical_sort_key(self, item: SearchResult, group_items: Sequence[SearchResult]) -> tuple[int, int, int, float]:
        explicit_targets = sum(1 for group_item in group_items if group_item.duplicate_of == item.result_id)
        keep_original_bonus = 0 if self._looks_like_repost(item.title, item.source_name) else 1
        return (
            item.tier_weight,
            explicit_targets,
            keep_original_bonus,
            -item.published_dt.timestamp(),
        )

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
