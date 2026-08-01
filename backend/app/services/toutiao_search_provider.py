"""Toutiao (今日头条) search provider via so.toutiao.com.

Fetches the Toutiao search results page with plain httpx and extracts article
data from the embedded SSR JSON script blobs. Toutiao aggregates content from
authoritative outlets (头条辟谣, 光明网, 环球网, 中国互联网联合辟谣平台)
making it valuable for rumor-checking.

No authentication required. Low anti-scraping risk at our query volume (<1 req/min).
"""
from __future__ import annotations

import json
import logging
import re
import time
from urllib.parse import quote_plus

from backend.app.core.config import Settings, get_settings
from backend.app.services.progress import emit_api_call, get_retrieval_stage_key
from backend.app.services.retrieval_models import SearchResult

logger = logging.getLogger(__name__)

_TOUTIAO_URL = "https://so.toutiao.com/search?keyword={query}&pd=information&dvpf=pc&page_num=0"
_SCRIPT_RE = re.compile(r"<script[^>]*>(\{.*?\})</script>", re.DOTALL)


class ToutiaoSearchProvider:
    name = "toutiao"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def enabled(self) -> bool:
        return getattr(self.settings, "toutiao_search_enabled", True)

    def search(self, query_text: str, *, max_results: int = 8) -> list[SearchResult]:
        if not self.enabled:
            return []

        stage_key = get_retrieval_stage_key() or "retrieval_initial"
        url = _TOUTIAO_URL.format(query=quote_plus(query_text))

        emit_api_call(
            stage_key=stage_key,
            call_type="http",
            status="running",
            title="头条检索",
            summary=f"正在检索今日头条「{query_text[:20]}」。",
            details=[f"query={query_text}"],
        )

        t0 = time.monotonic()
        try:
            import httpx

            read_timeout = max(float(self.settings.retrieval_timeout_seconds), 1.0)
            response = httpx.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "Accept-Encoding": "gzip, deflate",
                    "Referer": "https://so.toutiao.com/",
                },
                timeout=httpx.Timeout(read_timeout, connect=min(read_timeout, 5.0)),
                follow_redirects=True,
            )
            latency_ms = int((time.monotonic() - t0) * 1000)
            response.raise_for_status()
            html = response.text

            results = self._parse_results(query_text, html, max_results=max_results)
            emit_api_call(
                stage_key=stage_key,
                call_type="http",
                status="completed",
                title="头条搜索完成",
                summary=f"头条返回 {len(results)} 条结果。",
                details=[
                    f"query={query_text}",
                    f"count={len(results)}",
                    f"latency={latency_ms}ms",
                    f"status={response.status_code}",
                ],
            )
            return results

        except Exception as exc:
            latency_ms = int((time.monotonic() - t0) * 1000)
            logger.warning("toutiao_search_error query=%s error=%s latency=%dms", query_text, exc, latency_ms)
            emit_api_call(
                stage_key=stage_key,
                call_type="http",
                status="error",
                title="头条搜索失败",
                summary=f"头条搜索出错: {exc.__class__.__name__}",
                details=[f"query={query_text}", f"error={str(exc)[:100]}", f"latency={latency_ms}ms"],
            )
            return []

    def _parse_results(self, query_text: str, html: str, *, max_results: int) -> list[SearchResult]:
        """Extract articles from SSR JSON blobs embedded in <script> tags."""
        results: list[SearchResult] = []

        for match in _SCRIPT_RE.finditer(html):
            if len(results) >= max_results:
                break
            blob = match.group(1)
            try:
                obj = json.loads(blob)
            except json.JSONDecodeError:
                continue

            data = obj.get("data") if isinstance(obj, dict) else None
            if not isinstance(data, dict):
                continue

            # Fields may be present-but-null in the SSR blob; `.get(k, "")` only
            # defaults on absence, so coerce via `or ""` before .strip() — a raw
            # None.strip() here would raise and (caught by search()'s outer
            # except) discard every result in the whole response.
            title = (data.get("title") or "").strip()
            abstract = (data.get("abstract") or "").strip()
            if not title or not abstract:
                continue

            source_name = (data.get("source") or data.get("media_name") or "今日头条").strip() or "今日头条"
            article_url = (data.get("article_url") or data.get("url") or "").strip()
            if not article_url:
                continue

            published_at = data.get("datetime") or data.get("publish_time")
            # Keep only string timestamps; numeric epochs and other types would
            # violate the SearchResult contract downstream.
            if not isinstance(published_at, str):
                published_at = None

            results.append(SearchResult(
                case_id="toutiao_search",
                query=query_text,
                result_id=f"tt_{len(results)}",
                title=title,
                url=article_url,
                source_name=source_name,
                published_at=published_at,
                snippet=abstract[:200] if abstract != title else title,
                source_tier="B",
            ))

        return results
