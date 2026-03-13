from __future__ import annotations

import logging
import re
from typing import Any, Optional

from backend.app.core.config import Settings, get_settings
from backend.app.models.schemas import NormalizedEvent
from backend.app.services.mock_retriever import MockRetriever
from backend.app.services.result_merger import SearchResultMerger
from backend.app.services.retrieval_cache import RetrievalCache
from backend.app.services.retrieval_models import RetrievalBundle, SearchResult
from backend.app.services.retrieval_provider import GdeltNewsProvider

logger = logging.getLogger(__name__)

QUESTION_REWRITE_REPLACEMENTS = (
    (r"[??]", " "),
    (r"^(??|????|??|????|??|??)", ""),
    (r"(????|????|???|?????)$", ""),
    (r"???", ""),
    (r"???", ""),
    (r"??", ""),
    (r"???", ""),
    (r"???", "??"),
    (r"??", "??"),
)
QUESTION_STOPWORDS = {
    "???",
    "???",
    "??",
    "??",
    "??",
    "??",
    "??",
    "??",
    "??",
    "???",
}


class RetrievalService:
    def __init__(
        self,
        settings: Optional[Settings] = None,
        mock_retriever: Optional[MockRetriever] = None,
        provider: Optional[GdeltNewsProvider] = None,
        cache: Optional[RetrievalCache] = None,
        merger: Optional[SearchResultMerger] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.merger = merger or SearchResultMerger()
        self.mock_retriever = mock_retriever or MockRetriever(settings=self.settings, merger=self.merger)
        self.provider = provider or GdeltNewsProvider(settings=self.settings)
        self.cache = cache or RetrievalCache(settings=self.settings)

    def retrieve_for_event(
        self,
        event: NormalizedEvent,
        *,
        request_context: Optional[dict[str, Any]] = None,
    ) -> RetrievalBundle:
        request_context = request_context or {}
        query = self._build_query(event, request_context=request_context)
        bypass_cache = self._as_bool(request_context.get("bypass_retrieval_cache"))

        if self.provider.enabled and query and event.input_type in {"text_news", "question_only", "url_news"}:
            if not bypass_cache:
                cached_bundle = self.cache.load(self.provider.name, query)
                if cached_bundle is not None:
                    logger.info("retrieval_cache_hit provider=%s query=%s", self.provider.name, query)
                    return cached_bundle

            try:
                raw_results = self.provider.search(query)
            except Exception as exc:
                logger.warning("real_retrieval_failed provider=%s error_type=%s", self.provider.name, exc.__class__.__name__)
                if not bypass_cache:
                    stale_bundle = self.cache.load(self.provider.name, query, allow_stale=True)
                    if stale_bundle is not None:
                        logger.info("retrieval_cache_stale_hit provider=%s query=%s", self.provider.name, query)
                        return stale_bundle
            else:
                if raw_results:
                    bundle = self._build_bundle(query, raw_results)
                    self.cache.save(self.provider.name, query, bundle)
                    return bundle

        return self.mock_retriever.retrieve_for_event(event)

    def _build_bundle(self, query: str, raw_results: list[SearchResult]) -> RetrievalBundle:
        canonical_results = tuple(sorted(self.merger.merge(raw_results), key=self.merger.chronological_sort_key))
        high_trust_count = sum(1 for item in canonical_results if item.is_high_trust)
        mode_hint = "complete_or_partial" if high_trust_count >= 2 else "partial"
        return RetrievalBundle(
            query=query,
            matched_case_id="real_search",
            mode_hint=mode_hint,
            raw_results=tuple(sorted(raw_results, key=self.merger.chronological_sort_key)),
            canonical_results=canonical_results,
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

        return " ".join(terms) or raw_input.strip().rstrip("??")

    def _as_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return False
