"""SearXNG search provider (Rec#2) — supplementary / fallback source.

SearXNG is a self-hosted metasearch engine. It broadens coverage beyond the
domestic-focused providers (Baidu/头条/微信/辟谣): English-language and overseas
official sources that those miss. Useful as a supplement and as a failure
fallback when the primary source returns nothing.

LICENSE — AGPL-3.0 (hard boundary): SearXNG is AGPL. We call a SEPARATE, already-
running SearXNG instance over its HTTP JSON API. We do NOT vendor, import, copy,
or link any SearXNG source into this repository, so this codebase is not a
derivative work. The instance URL is operator-supplied config
(``SEARXNG_BASE_URL``); nothing about the instance is hardcoded.

Default-OFF: enabled only when ``SEARXNG_SEARCH_ENABLED=true`` AND a base URL is
set. When either is missing the provider reports ``enabled = False`` and
``search`` returns ``[]`` — safe to leave unconfigured. Every failure path
degrades to ``[]``; a flaky or unreachable instance never breaks a run.

NOTE (honest status): this is a scaffolded provider. It has not been validated
against a live SearXNG instance in this environment (none is reachable to an
unattended agent). The request/response shape follows SearXNG's documented
``/search?format=json`` contract and is covered by tests with mocked HTTP; a
real-instance smoke test is the remaining step before recommending it for use.
"""
from __future__ import annotations

import logging
import time
from urllib.parse import urlencode

from backend.app.core.config import Settings, get_settings
from backend.app.services.http_reliability import reliable_get
from backend.app.services.progress import emit_api_call, get_retrieval_stage_key
from backend.app.services.retrieval_models import SearchResult

logger = logging.getLogger(__name__)


class SearxngSearchProvider:
    name = "searxng"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def enabled(self) -> bool:
        return bool(
            getattr(self.settings, "searxng_search_enabled", False)
            and getattr(self.settings, "searxng_base_url", "")
        )

    def search(self, query_text: str, *, max_results: int = 8) -> list[SearchResult]:
        if not self.enabled:
            return []

        stage_key = get_retrieval_stage_key() or "retrieval_initial"
        base = self.settings.searxng_base_url
        params = urlencode({"q": query_text, "format": "json", "language": "zh-CN"})
        url = f"{base}/search?{params}"

        emit_api_call(
            stage_key=stage_key,
            call_type="http",
            status="running",
            title="SearXNG 检索",
            summary=f"正在通过 SearXNG 检索「{query_text[:20]}」。",
            details=[f"query={query_text}"],
        )

        t0 = time.monotonic()
        try:
            read_timeout = max(float(self.settings.retrieval_timeout_seconds), 1.0)
            response = reliable_get(
                url,
                headers={"Accept": "application/json"},
                timeout=read_timeout,
                max_retries=getattr(self.settings, "url_fetch_max_retries", 1),
                follow_redirects=True,
            )
            latency_ms = int((time.monotonic() - t0) * 1000)
            if response.status_code != 200:
                emit_api_call(
                    stage_key=stage_key,
                    call_type="http",
                    status="warning",
                    title="SearXNG 检索",
                    summary=f"SearXNG 返回 {response.status_code}，跳过。",
                    details=[f"status={response.status_code}", f"latency_ms={latency_ms}"],
                )
                return []
            payload = response.json()
        except Exception as exc:
            logger.warning("searxng_search_failed query=%s error=%s", query_text[:40], exc)
            emit_api_call(
                stage_key=stage_key,
                call_type="http",
                status="warning",
                title="SearXNG 检索",
                summary="SearXNG 检索失败，已跳过（不影响其他来源）。",
                details=[f"error={type(exc).__name__}"],
            )
            return []

        return self._parse(payload, query_text, max_results)

    def _parse(self, payload: dict, query_text: str, max_results: int) -> list[SearchResult]:
        raw = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(raw, list):
            return []
        results: list[SearchResult] = []
        for i, item in enumerate(raw[:max_results]):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or "").strip()
            if not url or not title:
                continue
            snippet = str(item.get("content") or "").strip()
            results.append(
                SearchResult(
                    case_id="searxng",
                    query=query_text,
                    result_id=f"searxng::{i}",
                    title=title,
                    url=url,
                    source_name=str(item.get("engine") or "searxng").strip() or "searxng",
                    published_at=str(item.get("publishedDate") or "").strip(),
                    snippet=snippet,
                    # Metasearch aggregates unknown-authority sources; default to the
                    # conservative C tier and let downstream authority scoring/rerank
                    # promote genuinely authoritative domains.
                    source_tier="C",
                    provider_name="searxng",
                )
            )
        return results
