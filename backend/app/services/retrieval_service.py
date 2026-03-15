from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import status

from backend.app.core.config import Settings, get_settings
from backend.app.core.exceptions import AppError
from backend.app.models.schemas import NormalizedEvent
from backend.app.services.contract_utils import ensure_datetime_string
from backend.app.services.question_intent import detect_trend_topic, is_broad_trend_question
from backend.app.services.question_text import clean_question_term, strip_question_tail
from backend.app.services.retrieval_cache import RetrievalCache
from backend.app.services.retrieval_deduper import chronological_sort_key, merge_search_results
from backend.app.services.retrieval_models import RetrievalBundle, SearchResult
from backend.app.services.retrieval_provider import KimiWebSearchProvider, RetrievalProvider

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
    (r"\u6b7b\u4e86", "\u6b7b\u4ea1"),
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
QUESTION_KEY_PHRASES = (
    "\u5973\u7f51\u7ea2",
    "\u7537\u7f51\u7ea2",
    "\u7f51\u7ea2",
    "\u4e3b\u64ad",
    "\u660e\u661f",
    "\u6f14\u5458",
    "\u8111\u51fa\u8840",
    "\u8111\u6ea2\u8840",
    "\u6b7b\u4ea1",
    "\u53bb\u4e16",
    "\u75c5\u5371",
    "\u4f4f\u9662",
    "\u62a2\u6551",
    "\u8f9f\u8c23",
    "\u901a\u62a5",
    "\u88c1\u5458",
)

class RetrievalService:
    def __init__(
        self,
        settings: Optional[Settings] = None,
        provider: Optional[RetrievalProvider] = None,
        cache: Optional[RetrievalCache] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.provider = provider or self._build_provider()
        self.cache = cache or RetrievalCache(
            cache_root=self.settings.retrieval_cache_dir,
            ttl_seconds=self.settings.retrieval_cache_ttl_seconds,
        )

    def _build_provider(self) -> RetrievalProvider:
        return KimiWebSearchProvider(settings=self.settings)

    def retrieve_for_event(
        self,
        event: NormalizedEvent,
        *,
        request_context: Optional[dict[str, Any]] = None,
    ) -> RetrievalBundle:
        request_context = request_context or {}
        query = self._build_query(event, request_context=request_context)
        cache_enabled = self.settings.retrieval_cache_enabled

        if not self.provider.enabled:
            raise AppError(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="kimi_not_configured",
                message="Kimi retrieval is required, but Kimi is not configured.",
            )

        if not query:
            raise AppError(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                code="empty_retrieval_query",
                message="The request could not be rewritten into a valid Kimi search query.",
            )

        try:
            raw_results = self.provider.search(query)
        except AppError:
            raise
        except Exception as exc:
            logger.warning("kimi_retrieval_failed provider=%s error_type=%s", self.provider.name, exc.__class__.__name__)
            raise AppError(
                status_code=status.HTTP_502_BAD_GATEWAY,
                code="kimi_retrieval_failed",
                message="Kimi retrieval failed. The request was not downgraded to any non-Kimi path.",
                details={"error_type": exc.__class__.__name__, "failure_detail": self._describe_exception(exc)},
            ) from exc

        if raw_results:
            bundle = self._build_bundle(query, raw_results, cache_status="write_only" if cache_enabled else "not_used")
            if cache_enabled:
                self.cache.write(query_text=query, provider_name=self.provider.name, bundle=bundle)
            return bundle

        return self._empty_bundle(query, provider_name=self.provider.name)

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
            if self.provider.name == "kimi":
                return event.raw_input.strip().rstrip("\uFF1F?")
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

    def _empty_bundle(
        self,
        query: str,
        *,
        provider_name: str,
        fallback_reason: str | None = None,
        failure_detail: str | None = None,
    ) -> RetrievalBundle:
        return RetrievalBundle(
            query=query,
            matched_case_id="real_search",
            provider_name=provider_name,
            cache_status="not_used",
            fallback_reason=fallback_reason,
            retrieved_at=ensure_datetime_string(datetime.now(UTC).isoformat()),
            failure_detail=failure_detail,
        )

    def _rewrite_question_query(self, raw_input: str) -> str:
        if is_broad_trend_question(raw_input):
            topic = detect_trend_topic(raw_input)
            if topic:
                return topic

        query = raw_input.strip()
        for pattern, replacement in QUESTION_REWRITE_REPLACEMENTS:
            query = re.sub(pattern, replacement, query)
        query = strip_question_tail(query)

        terms = []
        seen = set()

        def push(term: str) -> None:
            cleaned = clean_question_term(term.strip())
            if not cleaned or cleaned in QUESTION_STOPWORDS or cleaned in seen:
                return
            seen.add(cleaned)
            terms.append(cleaned)

        for phrase in QUESTION_KEY_PHRASES:
            if phrase in query:
                push(phrase)

        for term in re.findall(r"\d+(?:\.\d+)?%?|[A-Za-z0-9]{2,}", query):
            push(term)

        for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", query):
            if len(chunk) <= 4:
                push(chunk)
            else:
                for window in (4, 3, 2):
                    if len(chunk) < window:
                        continue
                    for index in range(0, len(chunk) - window + 1):
                        push(chunk[index : index + window])
                        if len(terms) >= 8:
                            return " ".join(terms[:8])
            if len(terms) >= 8:
                break

        return " ".join(terms[:8]) or raw_input.strip().rstrip("\uFF1F?")

    def _describe_exception(self, exc: Exception) -> str:
        response = getattr(exc, "response", None)
        if response is not None:
            status_code = getattr(response, "status_code", None)
            reason_phrase = getattr(response, "reason_phrase", None) or ""
            if status_code is not None:
                detail = f"HTTP {status_code} {reason_phrase}".strip()
                return detail
        return exc.__class__.__name__

    def _as_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return False


