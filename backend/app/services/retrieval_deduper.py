from __future__ import annotations

import re
from collections import defaultdict
from itertools import combinations
from typing import Optional, Sequence

from backend.app.services.retrieval_models import SearchResult

REPOST_PREFIXES = ("转载", "转发", "聚合页", "聚合", "搬运")
REPOST_SOURCE_MARKERS = ("聚合", "快讯", "转发")
REPOST_LABEL = "repost"
DUPLICATE_LABEL = "duplicate"
NEAR_DUPLICATE_LABEL = "near_duplicate"


def merge_search_results(results: Sequence[SearchResult]) -> tuple[SearchResult, ...]:
    if not results:
        return ()

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
        if classify_relation(left, right) is not None:
            union(left.result_id, right.result_id)

    groups: dict[str, list[SearchResult]] = defaultdict(list)
    for item in results:
        groups[find(item.result_id)].append(item)

    merged_results: list[SearchResult] = []
    for group_items in groups.values():
        if len(group_items) == 1:
            item = group_items[0]
            merged_results.append(
                item.with_merge_metadata(
                    canonical_result_id=item.result_id,
                    relation_type="repost" if item.is_repost_like else "original",
                )
            )
            continue

        canonical = max(group_items, key=lambda item: canonical_sort_key(item, group_items))
        merged_ids: list[str] = []
        merged_notes: list[str] = []
        for item in sorted(group_items, key=chronological_sort_key):
            if item.result_id == canonical.result_id:
                continue
            merged_ids.append(item.result_id)
            relation = classify_relation(item, canonical) or item.duplicate_reason or NEAR_DUPLICATE_LABEL
            merged_notes.append(f"{item.result_id}:{relation}:{item.source_name}")

        merged_results.append(
            canonical.with_merge_metadata(
                canonical_result_id=canonical.result_id,
                merged_result_ids=tuple(merged_ids),
                merged_notes=tuple(merged_notes),
                relation_type="repost" if canonical.is_repost_like else "original",
            )
        )

    return tuple(sorted(merged_results, key=chronological_sort_key))


def canonical_sort_key(item: SearchResult, group_items: list[SearchResult]) -> tuple[int, int, int, float]:
    explicit_targets = sum(1 for group_item in group_items if group_item.duplicate_of == item.result_id)
    keep_original_bonus = 0 if looks_like_repost(item.title, item.source_name) else 1
    return (
        item.tier_weight,
        explicit_targets,
        keep_original_bonus,
        -item.published_dt.timestamp() if item.published_dt else 0,
    )


def classify_relation(left: SearchResult, right: SearchResult) -> Optional[str]:
    if left.result_id == right.result_id:
        return None
    if left.duplicate_of == right.result_id or right.duplicate_of == left.result_id:
        is_repost = looks_like_repost(left.title, left.source_name) or looks_like_repost(right.title, right.source_name)
        return REPOST_LABEL if is_repost else DUPLICATE_LABEL
    if compact_text(left.url) == compact_text(right.url):
        return DUPLICATE_LABEL
    if normalize_title(left.title) == normalize_title(right.title):
        is_repost = (
            looks_like_repost(left.title, left.source_name)
            or looks_like_repost(right.title, right.source_name)
            or left.is_aggregator_source
            or right.is_aggregator_source
        )
        return REPOST_LABEL if is_repost else DUPLICATE_LABEL
    if not left.published_at or not right.published_at:
        return None
    if left.effective_published_at[:10] != right.effective_published_at[:10]:
        return None
    if titles_overlap(left.title, right.title):
        if left.is_aggregator_source or right.is_aggregator_source:
            return REPOST_LABEL
        return NEAR_DUPLICATE_LABEL
    return None


def titles_overlap(left_title: str, right_title: str) -> bool:
    left_terms = set(extract_terms(normalize_title(left_title)))
    right_terms = set(extract_terms(normalize_title(right_title)))
    if not left_terms or not right_terms:
        return False
    shared = left_terms & right_terms
    if len(shared) >= 3:
        return True
    shorter = min(len(left_terms), len(right_terms))
    return shorter > 0 and len(shared) / shorter >= 0.75


def normalize_title(title: str) -> str:
    compact = title.strip().lower()
    compact = re.sub(r"^(转载|转发|聚合页|聚合|搬运)[:?\s-]*", "", compact)
    return re.sub(r"[\W_]+", "", compact)


def extract_terms(text: str) -> list[str]:
    return re.findall(r"[a-z0-9%]+|[\u4e00-\u9fff]{2,12}", text)


def looks_like_repost(title: str, source_name: str) -> bool:
    return title.startswith(REPOST_PREFIXES) or any(prefix in source_name for prefix in REPOST_SOURCE_MARKERS)


def compact_text(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def chronological_sort_key(item: SearchResult) -> tuple[str, int, str]:
    return (item.effective_published_at, -item.tier_weight, item.result_id)
