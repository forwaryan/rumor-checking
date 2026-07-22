from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Optional, Tuple
from urllib.parse import urlparse

from backend.app.models.schemas import EvidenceItem, RetrievalDiagnostics, SourceTier

TIER_WEIGHTS = {"S": 4, "A": 3, "B": 2, "C": 1}

OFFICIAL_HOST_MARKERS = ("gov.cn", ".gov", "police", "court", "edu.cn", "hospital", "school")
MAINSTREAM_HOST_MARKERS = (
    "news.cn",
    "xinhuanet.com",
    "people.com.cn",
    "cctv.com",
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "nytimes.com",
    "thepaper.cn",
    "caixin.com",
    "chinanews.com.cn",
)
AGGREGATOR_HOST_MARKERS = (
    "aggregate",
    "aggregator",
    "portal",
    "news",
    "ifeng",
    "sohu",
    "163.com",
    "qq.com",
    "sina",
    "msn",
    "toutiao",
)
RUMOR_SIGNAL_KEYWORDS = ("传闻", "爆料", "网传", "截图", "疯传", "谣言", "leak", "rumor", "viral")
RESPONSE_SIGNAL_KEYWORDS = ("回应", "否认", "辟谣", "核查", "不实", "澄清", "responds", "denies")
CLARIFICATION_SIGNAL_KEYWORDS = ("说明", "通报", "公告", "更新", "clarifies", "statement", "update")
AMPLIFICATION_SIGNAL_KEYWORDS = ("热议", "发酵", "转发", "转载", "刷屏", "扩散", "widely shared")
PEAK_SIGNAL_KEYWORDS = ("热搜", "刷屏", "持续发酵", "集中报道", "峰值", "peak")
OFFICIAL_SIGNAL_KEYWORDS = ("官方", "通报", "公安", "医院", "学校", "政府", "监管局", "委员会")
REPOST_TITLE_PREFIXES = ("转载", "转发", "聚合页", "聚合", "搬运")
REPOST_SOURCE_MARKERS = ("聚合", "快讯", "转发", "搬运")
PLACEHOLDER_INDEPENDENCE_HOSTS = {"example.com", "example.cn", "example.org", "example.net"}


def compact_retrieval_text(text: str) -> str:
    return " ".join(text.split()).strip()


def infer_source_category(url: str, source_name: str) -> str:
    host = ((urlparse(url).netloc or source_name).lower()).strip()
    source = source_name.lower().strip()
    if any(marker in host or marker in source for marker in OFFICIAL_HOST_MARKERS + OFFICIAL_SIGNAL_KEYWORDS):
        return "official"
    if any(host == marker or host.endswith(f".{marker}") or marker in source for marker in MAINSTREAM_HOST_MARKERS):
        return "mainstream_media"
    if any(marker in host or marker in source for marker in AGGREGATOR_HOST_MARKERS + REPOST_SOURCE_MARKERS):
        return "aggregator"
    return "other"


def build_independence_key(url: str, source_name: str) -> str:
    host = (urlparse(url).netloc or "").lower().strip(".")
    if host:
        parts = [item for item in host.split(".") if item]
        if len(parts) >= 3 and ".".join(parts[-2:]) in {"com.cn", "org.cn", "net.cn", "gov.cn", "edu.cn"}:
            root = ".".join(parts[-3:])
        elif len(parts) >= 2:
            root = ".".join(parts[-2:])
        else:
            root = host
        if root in PLACEHOLDER_INDEPENDENCE_HOSTS:
            normalized_source = compact_retrieval_text(source_name.lower())
            if normalized_source:
                return normalized_source
        return root
    return compact_retrieval_text(source_name.lower()) or "unknown-source"


def detect_signal_tags(title: str, snippet: str, source_name: str) -> tuple[str, ...]:
    haystack = f"{title} {snippet} {source_name}".lower()
    tags: list[str] = []
    if any(keyword.lower() in haystack for keyword in RUMOR_SIGNAL_KEYWORDS):
        tags.append("rumor")
    if any(keyword.lower() in haystack for keyword in RESPONSE_SIGNAL_KEYWORDS):
        tags.append("response")
    if any(keyword.lower() in haystack for keyword in CLARIFICATION_SIGNAL_KEYWORDS):
        tags.append("clarification")
    if any(keyword.lower() in haystack for keyword in AMPLIFICATION_SIGNAL_KEYWORDS):
        tags.append("amplification")
    if any(keyword.lower() in haystack for keyword in PEAK_SIGNAL_KEYWORDS):
        tags.append("peak")
    if any(keyword.lower() in haystack for keyword in OFFICIAL_SIGNAL_KEYWORDS):
        tags.append("official")
    return tuple(dict.fromkeys(tags))


def looks_like_repost(title: str, source_name: str) -> bool:
    return title.startswith(REPOST_TITLE_PREFIXES) or any(marker in source_name for marker in REPOST_SOURCE_MARKERS)


@dataclass(frozen=True)
class RetrievalQuerySpec:
    label: str
    query: str
    rationale: str
    claim_hint: str = ""
    cache_scope: Optional[str] = None

    def normalized_query(self) -> str:
        return compact_retrieval_text(self.query)

    def normalized_scope(self) -> str:
        if self.cache_scope:
            return compact_retrieval_text(self.cache_scope)
        base = self.claim_hint or self.query
        return compact_retrieval_text(f"{self.label} {base}")

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "query": self.query,
            "rationale": self.rationale,
            "claim_hint": self.claim_hint,
            "cache_scope": self.cache_scope,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "RetrievalQuerySpec":
        return cls(
            label=str(payload.get("label") or "query"),
            query=str(payload.get("query") or ""),
            rationale=str(payload.get("rationale") or ""),
            claim_hint=str(payload.get("claim_hint") or ""),
            cache_scope=payload.get("cache_scope") if isinstance(payload.get("cache_scope"), str) else None,
        )


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
    source_category: str = "other"
    independence_key: Optional[str] = None
    relation_type: Optional[str] = None
    signal_tags: Tuple[str, ...] = ()
    query_label: Optional[str] = None

    @property
    def canonical_id(self) -> str:
        return self.canonical_result_id or self.result_id

    @property
    def published_dt(self) -> Optional[datetime]:
        if not self.published_at:
            return None
        return datetime.fromisoformat(self.published_at)

    @property
    def tier_weight(self) -> int:
        return TIER_WEIGHTS[self.source_tier]

    @property
    def is_high_trust(self) -> bool:
        return self.source_tier in {"S", "A"}

    @property
    def effective_source_category(self) -> str:
        if self.source_category and self.source_category != "other":
            return self.source_category
        return infer_source_category(self.url, self.source_name)

    @property
    def effective_independence_key(self) -> str:
        return self.independence_key or build_independence_key(self.url, self.source_name)

    @property
    def effective_signal_tags(self) -> tuple[str, ...]:
        return self.signal_tags or detect_signal_tags(self.title, self.snippet, self.source_name)

    @property
    def is_official_source(self) -> bool:
        return self.effective_source_category == "official"

    @property
    def is_mainstream_source(self) -> bool:
        return self.effective_source_category == "mainstream_media"

    @property
    def is_aggregator_source(self) -> bool:
        return self.effective_source_category == "aggregator"

    @property
    def is_repost_like(self) -> bool:
        if self.relation_type == "repost":
            return True
        if self.duplicate_of:
            return True
        return looks_like_repost(self.title, self.source_name) or self.is_aggregator_source

    @property
    def has_rumor_signal(self) -> bool:
        return "rumor" in self.effective_signal_tags

    @property
    def has_response_signal(self) -> bool:
        return "response" in self.effective_signal_tags or "clarification" in self.effective_signal_tags

    @property
    def propagation_score(self) -> int:
        score = 1 + len(self.merged_result_ids)
        if self.is_aggregator_source:
            score += 2
        if "amplification" in self.effective_signal_tags:
            score += 2
        if "peak" in self.effective_signal_tags:
            score += 1
        if self.is_mainstream_source:
            score += 1
        return score

    def with_merge_metadata(
        self,
        *,
        canonical_result_id: Optional[str] = None,
        duplicate_reason: Optional[str] = None,
        merged_result_ids: Tuple[str, ...] = (),
        merged_notes: Tuple[str, ...] = (),
        relation_type: Optional[str] = None,
    ) -> "SearchResult":
        return replace(
            self,
            canonical_result_id=canonical_result_id,
            duplicate_reason=duplicate_reason,
            merged_result_ids=merged_result_ids,
            merged_notes=merged_notes,
            relation_type=relation_type or self.relation_type,
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

    def with_enrichment_metadata(
        self,
        *,
        source_category: Optional[str] = None,
        independence_key: Optional[str] = None,
        relation_type: Optional[str] = None,
        signal_tags: Optional[Tuple[str, ...]] = None,
        query_label: Optional[str] = None,
    ) -> "SearchResult":
        return replace(
            self,
            source_category=source_category or self.source_category,
            independence_key=independence_key or self.independence_key,
            relation_type=relation_type or self.relation_type,
            signal_tags=signal_tags or self.signal_tags,
            query_label=query_label or self.query_label,
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
            "source_category": self.source_category,
            "independence_key": self.independence_key,
            "relation_type": self.relation_type,
            "signal_tags": list(self.signal_tags),
            "query_label": self.query_label,
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
            source_category=str(payload.get("source_category") or "other"),
            independence_key=payload.get("independence_key") if isinstance(payload.get("independence_key"), str) else None,
            relation_type=payload.get("relation_type") if isinstance(payload.get("relation_type"), str) else None,
            signal_tags=tuple(str(item) for item in payload.get("signal_tags", []) or []),
            query_label=payload.get("query_label") if isinstance(payload.get("query_label"), str) else None,
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
    failure_detail: Optional[str] = None
    query_groups: Tuple[RetrievalQuerySpec, ...] = ()
    query_failures: Tuple[str, ...] = ()

    @property
    def related_result_count(self) -> int:
        return len(self.raw_results)

    @property
    def high_trust_result_count(self) -> int:
        return sum(1 for item in self.canonical_results if item.is_high_trust)

    @property
    def independent_source_count(self) -> int:
        return len({item.effective_independence_key for item in self.canonical_results if item.effective_independence_key})

    @property
    def independent_high_trust_source_count(self) -> int:
        return len(
            {
                item.effective_independence_key
                for item in self.canonical_results
                if item.is_high_trust and item.effective_independence_key
            }
        )

    @property
    def official_result_count(self) -> int:
        return sum(1 for item in self.canonical_results if item.is_official_source)

    @property
    def mainstream_result_count(self) -> int:
        return sum(1 for item in self.canonical_results if item.is_mainstream_source)

    @property
    def aggregator_result_count(self) -> int:
        return sum(1 for item in self.canonical_results if item.is_aggregator_source)

    @property
    def conflict_signals(self) -> tuple[str, ...]:
        signals: list[str] = []
        rumor_count = sum(1 for item in self.canonical_results if item.has_rumor_signal)
        response_count = sum(1 for item in self.canonical_results if item.has_response_signal)
        repost_count = sum(1 for item in self.canonical_results if item.is_repost_like)
        if rumor_count and response_count:
            signals.append("rumor_vs_response")
        if repost_count and repost_count < len(self.canonical_results):
            signals.append("origin_vs_repost")
        if self.independent_source_count <= 1 and len(self.canonical_results) >= 3:
            signals.append("single_source_cluster")
        return tuple(signals)

    @property
    def evidence_grade(self) -> str:
        if self.independent_high_trust_source_count >= 2:
            return "A"
        if self.high_trust_result_count >= 1:
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
        failure_detail: Optional[str] = None,
        query_groups: Optional[Tuple[RetrievalQuerySpec, ...]] = None,
        query_failures: Optional[Tuple[str, ...]] = None,
    ) -> "RetrievalBundle":
        return replace(
            self,
            provider_name=provider_name or self.provider_name,
            cache_key=cache_key or self.cache_key,
            cache_status=cache_status or self.cache_status,
            fallback_used=self.fallback_used if fallback_used is None else fallback_used,
            fallback_reason=fallback_reason or self.fallback_reason,
            retrieved_at=retrieved_at or self.retrieved_at,
            failure_detail=failure_detail or self.failure_detail,
            query_groups=query_groups if query_groups is not None else self.query_groups,
            query_failures=query_failures if query_failures is not None else self.query_failures,
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

    def to_retrieval_hit_items(self, limit: int = 8) -> list[EvidenceItem]:
        hits: list[EvidenceItem] = []
        ordered_results = sorted(
            self.canonical_results,
            key=lambda item: (item.published_at, item.tier_weight, item.result_id),
            reverse=True,
        )
        for result in ordered_results[:limit]:
            hits.append(result.to_evidence(relevance_reason=self._build_hit_reason(result)))
        return hits

    def to_diagnostics(self) -> RetrievalDiagnostics:
        failure_detail = self.failure_detail
        if self.query_failures:
            joined_failures = "; ".join(self.query_failures[:3])
            failure_detail = f"{failure_detail}; {joined_failures}" if failure_detail else joined_failures
        return RetrievalDiagnostics(
            query=self.query,
            provider_name=self.provider_name or None,
            cache_status=self.cache_status or None,
            retrieved_at=self.retrieved_at,
            raw_result_count=len(self.raw_results),
            canonical_result_count=len(self.canonical_results),
            failure_detail=failure_detail,
        )

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
            "failure_detail": self.failure_detail,
            "query_groups": [item.to_dict() for item in self.query_groups],
            "query_failures": list(self.query_failures),
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
            failure_detail=payload.get("failure_detail") if isinstance(payload.get("failure_detail"), str) else None,
            query_groups=tuple(RetrievalQuerySpec.from_dict(item) for item in payload.get("query_groups", []) or []),
            query_failures=tuple(str(item) for item in payload.get("query_failures", []) or []),
        )

    def _build_relevance_reason(self, result: SearchResult) -> str:
        reasons: list[str] = []
        category = result.effective_source_category
        if category == "official":
            reasons.append("官方来源直接提及当前事件")
        elif category == "mainstream_media":
            reasons.append("主流媒体给出了可复核报道")
        elif category == "aggregator":
            reasons.append("这是聚合或转载来源，更适合观察传播扩散")
        else:
            reasons.append("该结果与当前问题相关，但仍需继续核对")

        if result.effective_independence_key:
            same_group_count = sum(
                1 for item in self.canonical_results if item.effective_independence_key == result.effective_independence_key
            )
            if same_group_count == 1:
                reasons.append("它属于当前结果中的独立来源")

        if result.has_response_signal:
            reasons.append("文本带有回应、辟谣或澄清信号")
        elif result.has_rumor_signal:
            reasons.append("文本带有传闻或爆料信号")

        if self.conflict_signals and (result.has_rumor_signal or result.has_response_signal):
            reasons.append("当前检索同时存在传闻与回应，需结合高可信来源复核")
        if result.merged_result_ids:
            reasons.append(f"已合并 {len(result.merged_result_ids)} 条重复或转载结果")
        return "；".join(dict.fromkeys(reasons)) + "。"

    def _build_hit_reason(self, result: SearchResult) -> str:
        reasons: list[str] = []
        if result.is_official_source:
            reasons.append("原始命中来自官方来源")
        elif result.is_mainstream_source:
            reasons.append("原始命中来自主流媒体")
        elif result.is_aggregator_source:
            reasons.append("原始命中更像聚合/转载节点")
        else:
            reasons.append("原始命中与问题存在一定相关性")

        if result.query_label:
            reasons.append(f"命中于 {result.query_label} query")
        if result.merged_result_ids:
            reasons.append(f"已合并 {len(result.merged_result_ids)} 条相似结果")
        return "；".join(dict.fromkeys(reasons)) + "。"
