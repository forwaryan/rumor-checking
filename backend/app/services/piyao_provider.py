"""Chinese Internet Joint Rumor Debunking Platform (中国互联网联合辟谣平台) provider.

Queries piyao.org.cn for official debunking articles. This is THE authoritative
rumor-debunking source in mainland China — articles here represent formal
government/media verdicts on specific rumors. A hit from this source should
receive S-tier weighting in the verdict engine.

Uses the site's search endpoint with plain httpx. No authentication required.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import UTC, datetime
from urllib.parse import quote_plus

from backend.app.core.config import Settings, get_settings
from backend.app.services.progress import emit_api_call, get_retrieval_stage_key
from backend.app.services.retrieval_models import SearchResult

logger = logging.getLogger(__name__)

_PIYAO_SEARCH_URL = (
    "https://www.piyao.org.cn/s?wd={query}"
)

_ITEM_RE = re.compile(
    r'<div[^>]*class="[^"]*result[^"]*"[^>]*>(.*?)</div>\s*(?=<div[^>]*class="[^"]*result|$)',
    re.DOTALL,
)
_TITLE_LINK_RE = re.compile(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL)
_SNIPPET_RE = re.compile(r'<(?:p|span)[^>]*class="[^"]*(?:content|desc|summary)[^"]*"[^>]*>(.*?)</(?:p|span)>', re.DOTALL)
_DATE_RE = re.compile(r'(\d{4})[-.年/](\d{1,2})[-.月/](\d{1,2})')
_TAG_RE = re.compile(r"<[^>]+>")


class PiyaoSearchProvider:
    name = "piyao"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def enabled(self) -> bool:
        return getattr(self.settings, "piyao_search_enabled", True)

    def search(self, query_text: str, *, max_results: int = 5) -> list[SearchResult]:
        if not self.enabled:
            return []

        stage_key = get_retrieval_stage_key() or "retrieval_initial"
        url = _PIYAO_SEARCH_URL.format(query=quote_plus(query_text))

        emit_api_call(
            stage_key=stage_key,
            call_type="http",
            status="running",
            title="辟谣平台检索",
            summary=f"正在通过中国互联网联合辟谣平台搜索「{query_text[:20]}」。",
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
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                },
                timeout=read_timeout,
                follow_redirects=True,
            )
            elapsed_ms = int((time.monotonic() - t0) * 1000)

            if response.status_code != 200:
                emit_api_call(
                    stage_key=stage_key,
                    call_type="http",
                    status="warning",
                    title="辟谣平台检索失败",
                    summary=f"HTTP {response.status_code}，耗时 {elapsed_ms}ms。",
                    details=[f"status_code={response.status_code}"],
                )
                return []

            html = response.text
            results = self._parse_results(html, query_text, max_results)

            emit_api_call(
                stage_key=stage_key,
                call_type="http",
                status="completed",
                title="辟谣平台检索完成",
                summary=f"获取 {len(results)} 条辟谣平台结果，耗时 {elapsed_ms}ms。",
                details=[f"results={len(results)}", f"elapsed_ms={elapsed_ms}"],
            )
            return results

        except Exception as exc:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            logger.warning("piyao_search_failed error=%s elapsed_ms=%d", exc, elapsed_ms)
            emit_api_call(
                stage_key=stage_key,
                call_type="http",
                status="warning",
                title="辟谣平台检索异常",
                summary=f"{exc.__class__.__name__}，耗时 {elapsed_ms}ms。",
                details=[f"error={exc.__class__.__name__}"],
            )
            return []

    def _parse_results(self, html: str, query_text: str, max_results: int) -> list[SearchResult]:
        results: list[SearchResult] = []

        items = _ITEM_RE.findall(html)
        if not items:
            items = re.findall(r'<li[^>]*>(.*?)</li>', html, re.DOTALL)

        for i, item_html in enumerate(items[:max_results]):
            link_match = _TITLE_LINK_RE.search(item_html)
            if not link_match:
                continue

            href = link_match.group(1).strip()
            title_raw = link_match.group(2).strip()
            title = _TAG_RE.sub("", title_raw).strip()
            if not title:
                continue

            if not href.startswith("http"):
                if href.startswith("/"):
                    href = f"https://www.piyao.org.cn{href}"
                else:
                    continue

            snippet_match = _SNIPPET_RE.search(item_html)
            snippet = _TAG_RE.sub("", snippet_match.group(1)).strip() if snippet_match else ""

            date_match = _DATE_RE.search(item_html)
            published_at = ""
            if date_match:
                try:
                    y, m, d = int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3))
                    published_at = datetime(y, m, d, tzinfo=UTC).isoformat()
                except (ValueError, OverflowError):
                    pass

            results.append(SearchResult(
                result_id=f"piyao_{i}",
                case_id="real_search",
                title=title,
                url=href,
                snippet=snippet[:300],
                source_name="中国互联网联合辟谣平台",
                source_tier="S",
                source_category="official_debunking",
                published_at=published_at,
                query_label=query_text,
            ))

        return results
