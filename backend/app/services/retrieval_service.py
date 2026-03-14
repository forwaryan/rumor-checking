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
from backend.app.services.retrieval_provider import GdeltNewsProvider, RetrievalProvider

logger = logging.getLogger(__name__)
UTC = timezone.utc

QUESTION_REWRITE_REPLACEMENTS = (
    (r"[\uFF1F?]", " "),
    (r"^(\u8bf7\u95ee|\u60f3\u95ee\u4e00\u4e0b|\u60f3\u95ee|\u6709\u4eba\u77e5\u9053|\u7f51\u4f20|\u542c\u8bf4)", ""),
    (r"(\u662f\u771f\u7684\u5417|\u771f\u7684\u5047\u7684|\u5c5e\u5b9e\u5417|\u662f\u771f\u7684\u5417\u554a)$", ""),
    (r"\u662f\u4e0d\u662f", ""),
    (r"\u6709\u6ca1\u6709", ""),
    (r"\u6700\u8fd1", ""),
    (r"\u6709\u4e00\u4e2a", ""),
    (r"\u6b7b\u6389\u4e86", "\u6b7b\u4ea1"),
    (r"\u6b7b\u6389", "\u6b7b\u4ea1"),
)
QUESTION_STOPWORDS = {
    "\u662f\u4e0d\u662f",
    "\u6709\u6ca1\u6709",
    "\u6700\u8fd1",
    "\u6d88\u606f",
    "\u4f20\u95fb",
    "\u4e8b\u4ef6",
    "\u65b0\u95fb",
    "\u4e8b\u60c5",
    "\u4e00\u4e2a",
    "\u6709\u4e00\u4e2a",
}

class RetrievalService:
    def __init__(
        self,
        settings: Optional[Settings] = None,
        mock_retriever: Optional[MockRetriever] = None,
        provider: Optional[RetrievalProvider] = None,
        cache: Optional[RetrievalCache] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.mock_retriever = mock_retriever or MockRetriever(settings=self.settings)
        self.provider = provider or self._build_provider()
        self.cache = cache or RetrievalCache(
            cache_root=self.settings.retrieval_cache_dir,
            ttl_seconds=self.settings.retrieval_cache_ttl_seconds,
        )

    def _build_provider(self) -> RetrievalProvider:
        return GdeltNewsProvider(settings=self.settings)

    def retrieve_for_event(
        self,
        event: NormalizedEvent,
        *,
        request_context: Optional[dict[str, Any]] = None,
    ) -> RetrievalBundle:
        request_context = request_context or {}
        query = self._build_query(event, request_context=request_context)
        bypass_cache = self._as_bool(request_context.get("bypass_retrieval_cache") or request_context.get("skip_retrieval_cache") or request_context.get("skip_cache"))
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
                bundle = self._build_bundle(query, raw_results, cache_status="bypassed" if bypass_cache else "miss")
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

    def _build_bundle(self, query: str, raw_results: list[SearchResult], *, cache_status: str) -> RetrievalBundle:
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
            cache_status=cache_status,
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
        for term in re.findall(r"[A-Za-z0-9]{2,}|[\u4e00-\u9fff]{2,8}", query):
            cleaned = term.strip()
            if not cleaned or cleaned in QUESTION_STOPWORDS or cleaned in seen:
                continue
            seen.add(cleaned)
            terms.append(cleaned)
            if len(terms) >= 6:
                break

        return " ".join(terms) or raw_input.strip().rstrip("\uFF1F?")

    def _as_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return False


