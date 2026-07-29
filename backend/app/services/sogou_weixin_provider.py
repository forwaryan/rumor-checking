"""Sogou WeChat (搜狗微信) search provider.

Scrapes weixin.sogou.com/weixin?type=2 (article search) with plain httpx and
extracts article data from the HTML result list. Sogou WeChat indexes WeChat
Official Account articles — a primary outlet for Chinese fact-checking content
(腾讯较真, 丁香医生, 科普中国, etc.) that rarely surfaces in Baidu/Bing.

No authentication required. Anti-spider protections are minimal for the search
listing page at low request volume (<1 req/min); link-resolution redirects DO
trigger anti-spider and are skipped (we use the sogou redirect URL as-is since
the snippet already carries sufficient evidence text).
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import quote_plus

from backend.app.core.config import Settings, get_settings
from backend.app.services.progress import emit_api_call, get_retrieval_stage_key
from backend.app.services.retrieval_models import SearchResult

logger = logging.getLogger(__name__)

_SOGOU_WEIXIN_URL = (
    "https://weixin.sogou.com/weixin?type=2&query={query}&ie=utf8"
)

_ITEM_RE = re.compile(r"<li[^>]*id=\"sogou_vr[^\"]*\"[^>]*>(.*?)</li>", re.DOTALL)
_HREF_TITLE_RE = re.compile(
    r'<a[^>]*href="([^"]+)"[^>]*target="_blank"[^>]*>(.*?)</a>', re.DOTALL
)
_ACCOUNT_RE = re.compile(r'<a[^>]*class="account"[^>]*>(.*?)</a>', re.DOTALL)
_SNIPPET_RE = re.compile(r'<p class="txt-info">(.*?)</p>', re.DOTALL)
_TIMESTAMP_RE = re.compile(r"timeConvert\('(\d+)'\)")
_TAG_RE = re.compile(r"<[^>]+>")


class SogouWeixinSearchProvider:
    name = "sogou_weixin"

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

    @property
    def enabled(self) -> bool:
        return getattr(self.settings, "sogou_weixin_search_enabled", True)

    def search(self, query_text: str, *, max_results: int = 8) -> List[SearchResult]:
        if not self.enabled:
            return []

        stage_key = get_retrieval_stage_key() or "retrieval_initial"
        url = _SOGOU_WEIXIN_URL.format(query=quote_plus(query_text))

        emit_api_call(
            stage_key=stage_key,
            call_type="http",
            status="running",
            title="微信公众号检索",
            summary=f"正在通过搜狗微信搜索「{query_text[:20]}」。",
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
                    "Referer": "https://weixin.sogou.com/",
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
                title="微信公众号搜索完成",
                summary=f"搜狗微信返回 {len(results)} 条结果。",
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
            logger.warning(
                "sogou_weixin_search_error query=%s error=%s latency=%dms",
                query_text, exc, latency_ms,
            )
            emit_api_call(
                stage_key=stage_key,
                call_type="http",
                status="error",
                title="微信公众号搜索失败",
                summary=f"搜狗微信搜索出错: {exc.__class__.__name__}",
                details=[f"query={query_text}", f"error={str(exc)[:100]}", f"latency={latency_ms}ms"],
            )
            return []

    def _parse_results(self, query_text: str, html: str, *, max_results: int) -> List[SearchResult]:
        results: List[SearchResult] = []

        for match in _ITEM_RE.finditer(html):
            if len(results) >= max_results:
                break
            item_html = match.group(1)

            href_title = _HREF_TITLE_RE.search(item_html)
            if not href_title:
                continue
            raw_href = href_title.group(1)
            raw_title = _TAG_RE.sub("", href_title.group(2)).strip()
            if not raw_title:
                continue

            article_url = raw_href
            if article_url.startswith("/"):
                article_url = f"https://weixin.sogou.com{article_url}"

            account_match = _ACCOUNT_RE.search(item_html)
            source_name = (
                _TAG_RE.sub("", account_match.group(1)).strip()
                if account_match
                else "微信公众号"
            )

            snippet = ""
            snippet_match = _SNIPPET_RE.search(item_html)
            if snippet_match:
                snippet = _TAG_RE.sub("", snippet_match.group(1)).strip()[:200]

            published_at = None
            ts_match = _TIMESTAMP_RE.search(item_html)
            if ts_match:
                try:
                    dt = datetime.fromtimestamp(int(ts_match.group(1)), tz=timezone.utc)
                    published_at = dt.isoformat()
                except (ValueError, OSError):
                    pass

            source_tier = self._classify_tier(source_name, raw_title, snippet)

            results.append(SearchResult(
                case_id="sogou_weixin_search",
                query=query_text,
                result_id=f"wx_{len(results)}",
                title=raw_title,
                url=article_url,
                source_name=source_name,
                published_at=published_at or "",
                snippet=snippet or raw_title,
                source_tier=source_tier,
            ))

        return results

    @staticmethod
    def _classify_tier(source_name: str, title: str, snippet: str) -> str:
        """Classify by ACCOUNT authority, not article text.

        Trust is a property of the source, so we match the official-account name
        only. Matching against title/snippet would let any marketing account earn
        tier A merely by writing "官方"/"公安" in a headline — exactly the kind of
        text a rumor amplifier controls. Unknown accounts default to C (social),
        matching the XHS convention, so an unverified WeChat post never counts as
        tier-B mainstream evidence."""
        name = source_name or ""
        high_trust = (
            "较真", "丁香", "科普中国", "果壳", "中国互联网联合辟谣", "辟谣",
            "人民日报", "新华", "央视", "中新", "澎湃", "光明网", "环球",
            "公安", "政府", "检察", "法院", "疾控", "卫健",
        )
        if any(kw in name for kw in high_trust):
            return "A"
        medium_trust = ("日报", "晚报", "新闻", "电视台", "广播", "都市报")
        if any(kw in name for kw in medium_trust):
            return "B"
        return "C"
