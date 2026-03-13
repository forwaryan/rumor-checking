from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Optional, Tuple

from backend.app.models.schemas import EvidenceItem, SourceTier

TIER_WEIGHTS = {"S": 4, "A": 3, "B": 2, "C": 1}


@dataclass(frozen=True)
class SearchResult:
    case_id: str
    query: str
    result_id: str
    title: str
    url: str
    source_name: str
    published_at: str
    snippet: str
    source_tier: SourceTier
    duplicate_of: Optional[str] = None
    canonical_result_id: Optional[str] = None
    duplicate_reason: Optional[str] = None
    merged_result_ids: Tuple[str, ...] = ()
    merged_notes: Tuple[str, ...] = ()

    @property
    def canonical_id(self) -> str:
        return self.canonical_result_id or self.result_id

    @property
    def published_dt(self) -> datetime:
        return datetime.fromisoformat(self.published_at)

    @property
    def tier_weight(self) -> int:
        return TIER_WEIGHTS[self.source_tier]

    @property
    def is_high_trust(self) -> bool:
        return self.source_tier in {"S", "A"}

    def with_merge_metadata(
        self,
        *,
        canonical_result_id: Optional[str] = None,
        duplicate_reason: Optional[str] = None,
        merged_result_ids: Tuple[str, ...] = (),
        merged_notes: Tuple[str, ...] = (),
    ) -> "SearchResult":
        return replace(
            self,
            canonical_result_id=canonical_result_id,
            duplicate_reason=duplicate_reason,
            merged_result_ids=merged_result_ids,
            merged_notes=merged_notes,
        )

    def to_evidence(self, *, relevance_reason: str) -> EvidenceItem:
        return EvidenceItem(
            title=self.title,
            url=self.url,
            source_name=self.source_name,
            published_at=self.published_at,
            snippet=self.snippet,
            relevance_reason=relevance_reason,
            source_tier=self.source_tier,
        )


@dataclass(frozen=True)
class RetrievalBundle:
    query: str
    matched_case_id: Optional[str] = None
    mode_hint: str = "safe"
    raw_results: Tuple[SearchResult, ...] = ()
    canonical_results: Tuple[SearchResult, ...] = ()
    expected_origin_result_id: Optional[str] = None
    expected_turning_point_result_id: Optional[str] = None

    @property
    def related_result_count(self) -> int:
        return len(self.raw_results)

    @property
    def high_trust_result_count(self) -> int:
        return sum(1 for item in self.canonical_results if item.is_high_trust)

    @property
    def evidence_grade(self) -> str:
        if self.high_trust_result_count >= 2:
            return "A"
        if self.high_trust_result_count == 1:
            return "B"
        if self.canonical_results:
            return "C"
        return "D"

    def to_evidence_items(self, limit: int = 4) -> list[EvidenceItem]:
        evidence: list[EvidenceItem] = []
        ordered_results = sorted(
            self.canonical_results,
            key=lambda item: (-item.tier_weight, item.published_at, item.result_id),
        )
        for result in ordered_results[:limit]:
            reason = self._build_relevance_reason(result)
            evidence.append(result.to_evidence(relevance_reason=reason))
        return evidence

    def _build_relevance_reason(self, result: SearchResult) -> str:
        text = f"{result.title} {result.snippet}"
        if any(token in text for token in ("回应", "否认", "澄清", "致歉", "恢复", "说明")):
            reason = "该结果补充了后续回应或澄清节点。"
        elif result.is_high_trust:
            reason = "高可信来源，直接支撑核心事实。"
        else:
            reason = "该结果用于补充传播链中的扩散节点。"
        if result.merged_result_ids:
            reason += f" 已归并 {len(result.merged_result_ids)} 条转载或近重复结果。"
        return reason
