from __future__ import annotations

import logging
import re
from typing import List, Optional
from urllib.parse import quote_plus, urlparse

from backend.app.core.config import Settings, get_settings
from backend.app.services.progress import emit_api_call
from backend.app.services.retrieval_models import (
    SearchResult,
    build_independence_key,
    detect_signal_tags,
    infer_source_category,
)
from backend.app.services.retrieval_provider import _infer_source_tier

logger = logging.getLogger(__name__)

_BAIDU_URL = "https://www.baidu.com/s?wd={query}&rn={count}"
_BING_URL = "https://cn.bing.com/search?q={query}&count={count}"


def _source_name_from_url(url: str) -> str:
    hostname = urlparse(url).netloc.lower()
    return hostname or "unknown-source"


class PlaywrightSearchProvider:
    name = "playwright"

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

    @property
    def enabled(self) -> bool:
        return self.settings.retrieval_provider == "playwright"

    def search(self, query_text: str) -> List[SearchResult]:
        if not self.enabled:
            return []

        # Bing returns real destination URLs directly, so the source domain
        # (and thus tier / independence / provenance) survives; Baidu wraps every
        # hit in a www.baidu.com/link?url= redirect that collapses grounding.
        # Prefer Bing, fall back to Baidu only when Bing yields nothing.
        results = self._search_bing(query_text)
        if not results:
            logger.info("playwright_bing_failed_fallback_to_baidu query=%s", query_text)
            results = self._search_baidu(query_text)
        return results

    def _search_baidu(self, query_text: str) -> List[SearchResult]:
        url = _BAIDU_URL.format(
            query=quote_plus(query_text),
            count=self.settings.retrieval_max_results,
        )
        emit_api_call(
            stage_key="retrieval_initial",
            call_type="browser",
            status="running",
            title="Playwright 百度搜索",
            summary="正在通过 headless 浏览器搜索百度。",
            details=[f"query={query_text}"],
        )
        try:
            html = self._fetch_page(url)
            results = self._parse_baidu(query_text, html)
            emit_api_call(
                stage_key="retrieval_initial",
                call_type="browser",
                status="completed",
                title="百度搜索完成",
                summary=f"百度返回 {len(results)} 条结果。",
                details=[f"query={query_text}", f"count={len(results)}"],
            )
            return results
        except Exception as e:
            logger.warning("playwright_baidu_error query=%s error=%s", query_text, e)
            emit_api_call(
                stage_key="retrieval_initial",
                call_type="browser",
                status="error",
                title="百度搜索失败",
                summary=f"百度搜索出错,将尝试 Bing: {e}",
                details=[f"query={query_text}"],
            )
            return []

    def _search_bing(self, query_text: str) -> List[SearchResult]:
        url = _BING_URL.format(
            query=quote_plus(query_text),
            count=self.settings.retrieval_max_results,
        )
        emit_api_call(
            stage_key="retrieval_initial",
            call_type="browser",
            status="running",
            title="Playwright Bing 搜索",
            summary="正在通过 headless 浏览器搜索 Bing。",
            details=[f"query={query_text}"],
        )
        try:
            html = self._fetch_page(url)
            results = self._parse_bing(query_text, html)
            emit_api_call(
                stage_key="retrieval_initial",
                call_type="browser",
                status="completed",
                title="Bing 搜索完成",
                summary=f"Bing 返回 {len(results)} 条结果。",
                details=[f"query={query_text}", f"count={len(results)}"],
            )
            return results
        except Exception as e:
            logger.warning("playwright_bing_error query=%s error=%s", query_text, e)
            emit_api_call(
                stage_key="retrieval_initial",
                call_type="browser",
                status="error",
                title="Bing 搜索失败",
                summary=f"Bing 搜索出错: {e}",
                details=[f"query={query_text}"],
            )
            return []

    def _fetch_page(self, url: str) -> str:
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
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
            },
            timeout=httpx.Timeout(read_timeout, connect=min(read_timeout, 5.0)),
            follow_redirects=True,
        )
        response.raise_for_status()
        return response.text

    def _resolve_baidu_redirect(self, url: str) -> str:
        # Baidu wraps every hit in http://www.baidu.com/link?url=... which hides
        # the real destination domain (and thus tier/independence/provenance).
        # A HEAD request follows the redirect back to the real URL; on any failure
        # keep the wrapped URL rather than dropping the result.
        if "baidu.com/link?" not in url:
            return url
        import httpx
        connect = min(max(float(self.settings.retrieval_timeout_seconds), 1.0), 5.0)
        try:
            response = httpx.head(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; rumor-checking/1.0)"},
                timeout=httpx.Timeout(connect, connect=connect),
                follow_redirects=True,
            )
            resolved = str(response.url)
            if resolved and "baidu.com/link?" not in resolved:
                return resolved
        except Exception as exc:
            logger.info("baidu_redirect_resolve_failed url=%s error=%s", url[:80], exc)
        return url

    def _parse_baidu(self, query_text: str, html: str) -> List[SearchResult]:
        import html as _html

        results: List[SearchResult] = []
        items = _extract_baidu_items(html)
        for index, item in enumerate(items, start=1):
            if not item.get("title") or not item.get("url"):
                continue
            url = self._resolve_baidu_redirect(_html.unescape(item["url"]))
            title = _clean_text(item["title"])
            snippet = _clean_text(item.get("snippet") or title)
            source_name = item.get("source") or _source_name_from_url(url)

            results.append(
                SearchResult(
                    case_id="real_search",
                    query=query_text,
                    result_id=f"pw-{index}",
                    title=title,
                    url=url,
                    source_name=source_name,
                    published_at=None,
                    snippet=snippet,
                    source_tier=_infer_source_tier(url, source_name),
                    source_category=infer_source_category(url, source_name),
                    independence_key=build_independence_key(url, source_name),
                    signal_tags=detect_signal_tags(title, snippet, source_name),
                )
            )
            if len(results) >= self.settings.retrieval_max_results:
                break

        logger.info("playwright_baidu_results query=%s count=%s", query_text, len(results))
        return results

    def _parse_bing(self, query_text: str, html: str) -> List[SearchResult]:
        results: List[SearchResult] = []
        items = _extract_bing_items(html)
        for index, item in enumerate(items, start=1):
            if not item.get("title") or not item.get("url"):
                continue
            url = item["url"]
            title = _clean_text(item["title"])
            snippet = _clean_text(item.get("snippet") or title)
            source_name = _source_name_from_url(url)

            results.append(
                SearchResult(
                    case_id="real_search",
                    query=query_text,
                    result_id=f"pw-{index}",
                    title=title,
                    url=url,
                    source_name=source_name,
                    published_at=None,
                    snippet=snippet,
                    source_tier=_infer_source_tier(url, source_name),
                    source_category=infer_source_category(url, source_name),
                    independence_key=build_independence_key(url, source_name),
                    signal_tags=detect_signal_tags(title, snippet, source_name),
                )
            )
            if len(results) >= self.settings.retrieval_max_results:
                break

        logger.info("playwright_bing_results query=%s count=%s", query_text, len(results))
        return results


def _clean_text(text: str) -> str:
    import html as _html
    text = re.sub(r"<[^>]+>", "", text)
    text = _html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_baidu_items(html: str) -> List[dict]:
    """Extract search results from Baidu SERP HTML using regex patterns."""
    items: List[dict] = []
    content_left = re.search(r'id="content_left"(.*?)id="content_right"', html, re.DOTALL)
    if not content_left:
        content_left = re.search(r'id="content_left"(.*)', html, re.DOTALL)
    if not content_left:
        return items

    block = content_left.group(1)
    # Split by <h3 anchors — each Baidu result starts with one.
    h3_positions = [m.start() for m in re.finditer(r'<h3[\s>]', block)]
    if not h3_positions:
        return items

    for i, pos in enumerate(h3_positions):
        end = h3_positions[i + 1] if i + 1 < len(h3_positions) else len(block)
        segment = block[pos:end]

        title_match = re.search(r'<h3[^>]*>\s*<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', segment, re.DOTALL)
        if not title_match:
            continue
        url = title_match.group(1)
        title = title_match.group(2)
        snippet = ""
        snippet_match = re.search(
            r'class="[^"]*(?:c-abstract|content-right_8Zs40)[^"]*"[^>]*>(.*?)</(?:div|span|p)>',
            segment,
            re.DOTALL,
        )
        if snippet_match:
            snippet = snippet_match.group(1)
        source = ""
        source_match = re.search(r'class="[^"]*(?:c-color-gray|source_1Vdff)[^"]*"[^>]*>(.*?)</', segment, re.DOTALL)
        if source_match:
            source = _clean_text(source_match.group(1))

        items.append({"url": url, "title": title, "snippet": snippet, "source": source})
        if len(items) >= 15:
            break

    return items


def _extract_bing_items(html: str) -> List[dict]:
    """Extract search results from Bing SERP HTML using regex patterns."""
    items: List[dict] = []
    results_section = re.search(r'id="b_results"(.*?)(?:id="b_context"|$)', html, re.DOTALL)
    if not results_section:
        return items

    block = results_section.group(1)
    li_blocks = re.findall(r'class="b_algo"[^>]*>(.*?)</li>', block, re.DOTALL)

    for li in li_blocks:
        title_match = re.search(r'<h2[^>]*>\s*<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', li, re.DOTALL)
        if not title_match:
            continue
        url = title_match.group(1)
        title = title_match.group(2)
        snippet = ""
        snippet_match = re.search(r'class="[^"]*b_caption[^"]*"[^>]*>.*?<p[^>]*>(.*?)</p>', li, re.DOTALL)
        if snippet_match:
            snippet = snippet_match.group(1)

        items.append({"url": url, "title": title, "snippet": snippet})
        if len(items) >= 15:
            break

    return items
