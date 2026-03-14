from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from backend.app.core.config import Settings, get_settings
from backend.app.models.schemas import NormalizedEvent
from backend.app.services.contract_utils import ensure_datetime_string
from backend.app.services.mock_retriever import MockRetriever
from backend.app.services.retrieval_cache import RetrievalCache
from backend.app.services.retrieval_deduper import chronological_sort_key, merge_search_results
from backend.app.services.retrieval_models import RetrievalBundle, SearchResult
from backend.app.services.retrieval_provider import GdeltNewsProvider

logger = logging.getLogger(__name__)
UTC = timezone.utc

QUESTION_REWRITE_REPLACEMENTS = (
    (r"[？?]", " "),
    (r"^(请问|想问一下|想问|有人知道|网传|听说)", ""),
    (r"(是真的吗|真的假的|属实吗|是真的吗啊)$", ""),
    (r"是不是", ""),
    (r"有没有", ""),
    (r"最近", ""),
    (r"有一个", ""),
    (r"死掉了", "死亡"),
    (r"死掉", "死亡"),
)
QUESTION_STOPWORDS = {
    "是不是",
    "有没有",
    "最近",
    "消息",
    "传闻",
    "事件",
    "新闻",
    "事情",
    "一个",
    "有一个",
}


class RetrievalService:
    def __init__(
        self,
        settings: Optional[Settings] = None,
        mock_retriever: Optional[MockRetriever] = None,
        provider: Optional[GdeltNewsProvider] = None,
        cache: Optional[RetrievalCache] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.mock_retriever = mock_retriever or MockRetriever(settings=self.settings)
        self.provider = provider or GdeltNewsProvider(settings=self.settings)
        self.cache = cache or RetrievalCache(
            cache_root=self.settings.retrieval_cache_dir,
            ttl_seconds=self.settings.retrieval_cache_ttl_seconds,
        )

    def retrieve_for_event(
        self,
        event: NormalizedEvent,
        *,
        request_context: Optional[dict[str, Any]] = None,
    ) -> RetrievalBundle:
        request_context = request_context or {}
        query = self._build_query(event, request_context=request_context)
        bypass_cache = self._as_bool(request_context.get("bypass_retrieval_cache"))
        cache_only = self._as_bool(request_context.get("retrieval_cache_only"))
        allow_stale_cache = self._as_bool(request_context.get("allow_stale_retrieval_cache"))
        cache_enabled = self.settings.retrieval_cache_enabled and not bypass_cache
        allow_real_retrieval = (
            self.provider.enabled
            and bool(query)
            and event.input_type in {"text_news", "question_only", "url_news"}
        )

        if allow_real_retrieval:
            if cache_enabled:
                cached_bundle = self.cache.read(
                    query_text=query,
                    provider_name=self.provider.name,
                    allow_stale=cache_only and allow_stale_cache,
                )
                if cached_bundle is not None:
                    logger.info("retrieval_cache_hit provider=%s query=%s", self.provider.name, query)
                    return cached_bundle

            if cache_only:
                return self._fallback_or_empty(
                    event=event,
                    query=query,
                    fallback_reason="retrieval_cache_only_miss",
                    provider_requested=True,
                )

            try:
                raw_results = self.provider.search(query)
            except Exception as exc:
                logger.warning("real_retrieval_failed provider=%s error_type=%s", self.provider.name, exc.__class__.__name__)
                if cache_enabled and self.settings.retrieval_cache_allow_stale_on_error:
                    stale_bundle = self.cache.read(query_text=query, provider_name=self.provider.name, allow_stale=True)
                    if stale_bundle is not None:
                        logger.info("retrieval_cache_stale_hit provider=%s query=%s", self.provider.name, query)
                        return stale_bundle
                return self._fallback_or_empty(
                    event=event,
                    query=query,
                    fallback_reason="real_retrieval_failed",
                    provider_requested=True,
                )

            if raw_results:
                bundle = self._build_bundle(query, raw_results)
                if cache_enabled:
                    self.cache.write(query_text=query, provider_name=self.provider.name, bundle=bundle)
                return bundle

            return self._fallback_or_empty(
                event=event,
                query=query,
                fallback_reason="real_retrieval_empty",
                provider_requested=True,
            )

        if self.settings.retrieval_provider == "mock":
            return self.mock_retriever.retrieve_for_event(event).with_runtime_metadata(
                cache_status="not_used",
                retrieved_at=ensure_datetime_string(datetime.now(UTC).isoformat()),
            )

        if self.settings.retrieval_provider == "off":
            return self._empty_bundle(query or event.raw_input.strip(), provider_name="off")

        return self._fallback_or_empty(
            event=event,
            query=query,
            fallback_reason="retrieval_provider_unavailable",
            provider_requested=False,
        )

    def _build_bundle(self, query: str, raw_results: list[SearchResult]) -> RetrievalBundle:
        retrieved_at = ensure_datetime_string(datetime.now(UTC).isoformat())
        runtime_results = [
            item.with_runtime_metadata(provider_name=self.provider.name, retrieved_at=retrieved_at)
            for item in raw_results
        ]
        canonical_results = merge_search_results(runtime_results)
        high_trust_count = sum(1 for item in canonical_results if item.is_high_trust)
        mode_hint = "complete_or_partial" if high_trust_count >= 2 else "partial"
        return RetrievalBundle(
            query=query,
            matched_case_id="real_search",
            mode_hint=mode_hint,
            raw_results=tuple(sorted(runtime_results, key=chronological_sort_key)),
            canonical_results=tuple(sorted(canonical_results, key=chronological_sort_key)),
            provider_name=self.provider.name,
            cache_key=self.cache.build_cache_key(query_text=query, provider_name=self.provider.name),
            cache_status="miss",
            retrieved_at=retrieved_at,
        )

    def _build_query(self, event: NormalizedEvent, *, request_context: dict[str, Any]) -> str:
        forced_query = request_context.get("force_retrieval_query")
        if isinstance(forced_query, str) and forced_query.strip():
            return forced_query.strip()

        if event.input_type == "question_only":
            return self._rewrite_question_query(event.raw_input)

        ordered_parts: list[str] = []
        seen = set()
        for part in [event.title, event.summary, *event.keywords[:4]]:
            if not part:
                continue
            compact = re.sub(r"\s+", " ", part).strip()
            if compact and compact not in seen:
                seen.add(compact)
                ordered_parts.append(compact)
        return " ".join(ordered_parts) or event.raw_input.strip()

    def _fallback_or_empty(
        self,
        *,
        event: NormalizedEvent,
        query: str,
        fallback_reason: str,
        provider_requested: bool,
    ) -> RetrievalBundle:
        if self.settings.retrieval_fallback_to_mock:
            fallback_bundle = self.mock_retriever.retrieve_for_event(event)
            return fallback_bundle.with_runtime_metadata(
                cache_status="not_used",
                fallback_used=provider_requested,
                fallback_reason=fallback_reason,
                retrieved_at=ensure_datetime_string(datetime.now(UTC).isoformat()),
            )
        provider_name = self.provider.name if provider_requested else self.settings.retrieval_provider
        return self._empty_bundle(
            query or event.raw_input.strip(),
            provider_name=provider_name or "off",
            fallback_reason=fallback_reason,
        )

    def _empty_bundle(
        self,
        query: str,
        *,
        provider_name: str,
        fallback_reason: str | None = None,
    ) -> RetrievalBundle:
        return RetrievalBundle(
            query=query,
            matched_case_id="real_search" if provider_name not in {"mock", "off"} else None,
            provider_name=provider_name,
            cache_status="not_used",
            fallback_reason=fallback_reason,
            retrieved_at=ensure_datetime_string(datetime.now(UTC).isoformat()),
        )

    def _rewrite_question_query(self, raw_input: str) -> str:
        query = raw_input.strip()
        for pattern, replacement in QUESTION_REWRITE_REPLACEMENTS:
            query = re.sub(pattern, replacement, query)

        terms = []
        seen = set()
        for term in re.findall(r"[A-Za-z0-9]{2,}|[一-鿿]{2,8}", query):
            cleaned = term.strip()
            if not cleaned or cleaned in QUESTION_STOPWORDS or cleaned in seen:
                continue
            seen.add(cleaned)
            terms.append(cleaned)
            if len(terms) >= 6:
                break

        return " ".join(terms) or raw_input.strip().rstrip("？?")

    def _as_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return False
