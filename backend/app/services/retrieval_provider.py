from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, List, Optional, Protocol
from urllib.parse import urlparse

import httpx

from backend.app.core.config import Settings, get_settings
from backend.app.services.contract_utils import ensure_datetime_string
from backend.app.services.retrieval_models import SearchResult

logger = logging.getLogger(__name__)

OFFICIAL_HOST_MARKERS = ("gov.cn", ".gov", "police", "court", "edu.cn")
TOP_TIER_DOMAINS = {
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
}
PORTAL_MARKERS = ("news", "ifeng", "sohu", "163.com", "qq.com", "sina", "msn", "yicai")


class RetrievalProvider(Protocol):
    name: str
    enabled: bool

    def search(self, query_text: str) -> List[SearchResult]:
        ...


class GdeltNewsProvider:
    name = "gdelt"

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

    @property
    def enabled(self) -> bool:
        return self.settings.retrieval_provider == self.name

    def search(self, query_text: str) -> List[SearchResult]:
        if not self.enabled:
            return []

        response = httpx.get(
            self.settings.retrieval_gdelt_base_url,
            params={
                "query": query_text,
                "mode": "ArtList",
                "format": "json",
                "maxrecords": str(self.settings.retrieval_max_results),
                "sort": "DateDesc",
            },
            timeout=self.settings.retrieval_timeout_seconds,
        )
        response.raise_for_status()
        return self._parse_articles(query_text, response.json())

    def _parse_articles(self, query_text: str, payload: Any) -> List[SearchResult]:
        articles = payload.get("articles") if isinstance(payload, dict) else None
        if not isinstance(articles, list):
            return []

        results: List[SearchResult] = []
        for index, article in enumerate(articles, start=1):
            if not isinstance(article, dict):
                continue

            url = self._clean_text(article.get("url"))
            title = self._clean_text(article.get("title"))
            if not url or not title:
                continue

            source_name = self._source_name(article, url)
            published_at = self._published_at(article.get("seendate") or article.get("date"))
            snippet = self._clean_text(article.get("snippet")) or title
            results.append(
                SearchResult(
                    case_id="real_search",
                    query=query_text,
                    result_id=f"gdelt-{index}",
                    title=title,
                    url=url,
                    source_name=source_name,
                    published_at=published_at,
                    snippet=snippet,
                    source_tier=self._infer_source_tier(url, source_name),
                )
            )
            if len(results) >= self.settings.retrieval_max_results:
                break

        logger.info("gdelt_retrieval_results query=%s count=%s", query_text, len(results))
        return results

    def _source_name(self, article: dict[str, Any], url: str) -> str:
        domain = self._clean_text(article.get("domain"))
        if domain:
            return domain
        hostname = urlparse(url).netloc.lower()
        return hostname or "unknown-source"

    def _published_at(self, raw_value: Any) -> str:
        value = self._clean_text(raw_value)
        if not value:
            return ensure_datetime_string(None)
        if re.fullmatch(r"\d{8}T\d{6}Z", value):
            parsed = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            return parsed.isoformat()
        return ensure_datetime_string(value)

    def _infer_source_tier(self, url: str, source_name: str) -> str:
        host = (urlparse(url).netloc or source_name).lower()
        if any(marker in host for marker in OFFICIAL_HOST_MARKERS):
            return "S"
        if any(host == domain or host.endswith(f".{domain}") for domain in TOP_TIER_DOMAINS):
            return "A"
        if any(marker in host for marker in PORTAL_MARKERS):
            return "B"
        return "C"

    def _clean_text(self, value: Any) -> Optional[str]:
        if not isinstance(value, str):
            return None
        compact = re.sub(r"\s+", " ", value).strip()
        return compact or None
