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
    provider_name: str = "mock"
    retrieved_at: Optional[str] = None

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

    def with_runtime_metadata(
        self,
        *,
        provider_name: Optional[str] = None,
        retrieved_at: Optional[str] = None,
    ) -> "SearchResult":
        return replace(
            self,
            provider_name=provider_name or self.provider_name,
            retrieved_at=retrieved_at or self.retrieved_at,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "query": self.query,
            "result_id": self.result_id,
            "title": self.title,
            "url": self.url,
            "source_name": self.source_name,
            "published_at": self.published_at,
            "snippet": self.snippet,
            "source_tier": self.source_tier,
            "duplicate_of": self.duplicate_of,
            "canonical_result_id": self.canonical_result_id,
            "duplicate_reason": self.duplicate_reason,
            "merged_result_ids": list(self.merged_result_ids),
            "merged_notes": list(self.merged_notes),
            "provider_name": self.provider_name,
            "retrieved_at": self.retrieved_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "SearchResult":
        return cls(
            case_id=str(payload.get("case_id") or "live"),
            query=str(payload.get("query") or ""),
            result_id=str(payload["result_id"]),
            title=str(payload.get("title") or ""),
            url=str(payload.get("url") or ""),
            source_name=str(payload.get("source_name") or "未知来源"),
            published_at=str(payload.get("published_at") or ""),
            snippet=str(payload.get("snippet") or ""),
            source_tier=str(payload.get("source_tier") or "C"),
            duplicate_of=payload.get("duplicate_of") if isinstance(payload.get("duplicate_of"), str) else None,
            canonical_result_id=payload.get("canonical_result_id") if isinstance(payload.get("canonical_result_id"), str) else None,
            duplicate_reason=payload.get("duplicate_reason") if isinstance(payload.get("duplicate_reason"), str) else None,
            merged_result_ids=tuple(str(item) for item in payload.get("merged_result_ids", []) or []),
            merged_notes=tuple(str(item) for item in payload.get("merged_notes", []) or []),
            provider_name=str(payload.get("provider_name") or "mock"),
            retrieved_at=payload.get("retrieved_at") if isinstance(payload.get("retrieved_at"), str) else None,
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
    provider_name: str = "mock"
    cache_key: Optional[str] = None
    cache_status: str = "not_used"
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
    retrieved_at: Optional[str] = None

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

    def with_runtime_metadata(
        self,
        *,
        provider_name: Optional[str] = None,
        cache_key: Optional[str] = None,
        cache_status: Optional[str] = None,
        fallback_used: Optional[bool] = None,
        fallback_reason: Optional[str] = None,
        retrieved_at: Optional[str] = None,
    ) -> "RetrievalBundle":
        return replace(
            self,
            provider_name=provider_name or self.provider_name,
            cache_key=cache_key or self.cache_key,
            cache_status=cache_status or self.cache_status,
            fallback_used=self.fallback_used if fallback_used is None else fallback_used,
            fallback_reason=fallback_reason or self.fallback_reason,
            retrieved_at=retrieved_at or self.retrieved_at,
        )

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

    def to_dict(self) -> dict[str, object]:
        return {
            "query": self.query,
            "matched_case_id": self.matched_case_id,
            "mode_hint": self.mode_hint,
            "raw_results": [item.to_dict() for item in self.raw_results],
            "canonical_results": [item.to_dict() for item in self.canonical_results],
            "expected_origin_result_id": self.expected_origin_result_id,
            "expected_turning_point_result_id": self.expected_turning_point_result_id,
            "provider_name": self.provider_name,
            "cache_key": self.cache_key,
            "cache_status": self.cache_status,
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
            "retrieved_at": self.retrieved_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "RetrievalBundle":
        return cls(
            query=str(payload.get("query") or ""),
            matched_case_id=payload.get("matched_case_id") if isinstance(payload.get("matched_case_id"), str) else None,
            mode_hint=str(payload.get("mode_hint") or "safe"),
            raw_results=tuple(SearchResult.from_dict(item) for item in payload.get("raw_results", []) or []),
            canonical_results=tuple(SearchResult.from_dict(item) for item in payload.get("canonical_results", []) or []),
            expected_origin_result_id=payload.get("expected_origin_result_id") if isinstance(payload.get("expected_origin_result_id"), str) else None,
            expected_turning_point_result_id=payload.get("expected_turning_point_result_id") if isinstance(payload.get("expected_turning_point_result_id"), str) else None,
            provider_name=str(payload.get("provider_name") or "mock"),
            cache_key=payload.get("cache_key") if isinstance(payload.get("cache_key"), str) else None,
            cache_status=str(payload.get("cache_status") or "not_used"),
            fallback_used=bool(payload.get("fallback_used", False)),
            fallback_reason=payload.get("fallback_reason") if isinstance(payload.get("fallback_reason"), str) else None,
            retrieved_at=payload.get("retrieved_at") if isinstance(payload.get("retrieved_at"), str) else None,
        )

    def _build_relevance_reason(self, result: SearchResult) -> str:
        text = f"{result.title} {result.snippet}"
        if any(token in text for token in ("回应", "否认", "辟谣", "澄清", "致歉", "说明", "更新", "通报")):
            reason = "该结果补充了后续回应、澄清或纠偏节点。"
        elif result.is_high_trust:
            reason = "高可信来源，直接支撑核心事实。"
        else:
            reason = "该结果用于补充传播链中的扩散节点。"
        if result.merged_result_ids:
            reason += f" 已归并 {len(result.merged_result_ids)} 条转载或近重复结果。"
        return reason
