from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import quote_plus, urlparse

from backend.app.core.config import Settings, get_settings
from backend.app.services.progress import emit_api_call, get_retrieval_stage_key
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


@dataclass
class _FetchMeta:
    url: str
    status_code: int
    latency_ms: int
    body_bytes: int

# Single CJK characters too generic to anchor relevance on: question/filler words
# that survive tokenization but carry no topic ("是真的吗" etc.). A result matching
# only these is not on-topic.
_GENERIC_QUERY_CHARS = set("的了吗呢啊是不有和与或在为对吗真假事件消息新闻网传")

# Multi-char segments too common to serve as compound match units. These appear in
# almost any Chinese article and carry no subject/topic signal. A result matching
# ONLY these (with no entity/action compound) is still noise.
_GENERIC_COMPOUND_STOPWORDS = {
    "最近", "近日", "近期", "目前", "现在", "如今", "已经", "之后",
    "今天", "昨天", "当前", "关于", "有关", "所有", "一些", "很多",
    "可能", "应该", "一个", "这个", "那个", "其中", "的是", "这是",
    "而且", "但是", "因为", "所以", "如果", "虽然", "不过", "然而",
    "其他", "什么", "怎么", "为什么", "哪些", "大家", "他们", "我们",
    "自己", "之前", "以后", "以来", "的人", "的事", "表示", "进行",
}


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

        # Baidu reads a Chinese hot-topic query as a whole phrase; Bing cn
        # tokenizes it down to the highest-IDF single character (e.g. "京东造游轮"
        # -> just "京") and returns encyclopedia noise about that one character. So
        # prefer Baidu, and fall back to Bing only when Baidu yields nothing. Baidu
        # wraps hits in a /link?url= redirect that _resolve_baidu_redirect follows
        # back to the real destination, so grounding (tier/independence) survives.
        results = self._search_baidu(query_text)
        if not results:
            logger.info("playwright_baidu_empty_fallback_to_bing query=%s", query_text)
            results = self._search_bing(query_text)
        return self._drop_tokenization_junk(query_text, results)

    def _query_topical_units(self, query_text: str) -> tuple[set[str], set[str]]:
        """Extract topical units at two granularities:

        - compound: 2-char CJK bigrams and alphanumeric tokens like "30%".
          These carry moderate-to-strong topical signal (e.g. "美团", "裁员").
        - single: individual CJK characters minus generic function words.
          These supplement compound matches but are too weak on their own.

        Returns (compound_units, single_char_units).
        """
        compound: set[str] = set()
        singles: set[str] = set()
        # Alphanumeric tokens (percentages, English names)
        for token in re.findall(r"[A-Za-z0-9%]{2,}", query_text):
            compound.add(token.lower())
        # CJK bigrams from content chars only (skip function-word chars)
        cjk_chars = [c for c in re.findall(r"[一-鿿]", query_text) if c not in _GENERIC_QUERY_CHARS]
        for i in range(len(cjk_chars) - 1):
            bigram = cjk_chars[i] + cjk_chars[i + 1]
            if bigram not in _GENERIC_COMPOUND_STOPWORDS:
                compound.add(bigram)
        # Single CJK chars for fallback scoring
        for char in cjk_chars:
            singles.add(char)
        return compound, singles

    def _looks_like_tokenization_junk(self, compound_units: set[str], single_units: set[str], result: SearchResult) -> bool:
        """A result is junk when it fails to match the query's core subject.

        Matching strategy (ordered):
        1. If any compound unit (entity like "美团", number like "30%") appears → keep.
        2. Otherwise, require ≥3 single-char hits to survive — 2 single chars
           is too easy to satisfy by coincidence (e.g. '裁' + '近' matching an
           unrelated layoff article).
        """
        haystack = f"{result.title} {result.snippet}".lower()
        if any(unit in haystack for unit in compound_units):
            return False
        matched_singles = sum(1 for unit in single_units if unit in haystack)
        return matched_singles < 3

    def _drop_tokenization_junk(self, query_text: str, results: List[SearchResult]) -> List[SearchResult]:
        compound_units, single_units = self._query_topical_units(query_text)
        if not compound_units and len(single_units) < 2:
            return results
        kept = [r for r in results if not self._looks_like_tokenization_junk(compound_units, single_units, r)]
        if not kept:
            logger.info("playwright_junk_filter_kept_all query=%s count=%s", query_text, len(results))
            return results
        if len(kept) < len(results):
            dropped_count = len(results) - len(kept)
            dropped_titles = [r.title[:40] for r in results if self._looks_like_tokenization_junk(compound_units, single_units, r)]
            logger.info("playwright_junk_filter_dropped query=%s kept=%s of=%s", query_text, len(kept), len(results))
            emit_api_call(
                stage_key=get_retrieval_stage_key() or "retrieval_initial",
                call_type="filter",
                status="completed",
                title="相关性过滤",
                summary=f"丢弃 {dropped_count} 条与检索词不相关的结果。",
                details=[f"query={query_text}", f"kept={len(kept)}", f"dropped={dropped_count}"]
                + [f"丢弃: {t}" for t in dropped_titles[:5]],
            )
        return kept

    def _search_baidu(self, query_text: str) -> List[SearchResult]:
        url = _BAIDU_URL.format(
            query=quote_plus(query_text),
            count=self.settings.retrieval_max_results,
        )
        emit_api_call(
            stage_key=get_retrieval_stage_key() or "retrieval_initial",
            call_type="http",
            status="running",
            title="百度检索（HTTP 抓取）",
            summary="正在通过 HTTP 抓取百度搜索结果页。",
            details=[f"url={url}", f"query={query_text}"],
        )
        try:
            html, meta = self._fetch_page(url)
            results = self._parse_baidu(query_text, html)
            emit_api_call(
                stage_key=get_retrieval_stage_key() or "retrieval_initial",
                call_type="http",
                status="completed",
                title="百度搜索完成",
                summary=f"百度返回 {len(results)} 条结果。",
                details=[
                    f"query={query_text}",
                    f"count={len(results)}",
                    f"status={meta.status_code}",
                    f"latency={meta.latency_ms}ms",
                    f"size={meta.body_bytes}B",
                    f"url={meta.url}",
                ],
            )
            return results
        except Exception as e:
            logger.warning("playwright_baidu_error query=%s error=%s", query_text, e)
            emit_api_call(
                stage_key=get_retrieval_stage_key() or "retrieval_initial",
                call_type="http",
                status="error",
                title="百度搜索失败",
                summary=f"百度搜索出错,将尝试 Bing: {e}",
                details=[f"query={query_text}", f"url={url}", f"error={e}"],
            )
            return []

    def _search_bing(self, query_text: str) -> List[SearchResult]:
        url = _BING_URL.format(
            query=quote_plus(query_text),
            count=self.settings.retrieval_max_results,
        )
        emit_api_call(
            stage_key=get_retrieval_stage_key() or "retrieval_initial",
            call_type="http",
            status="running",
            title="Bing 检索（HTTP 抓取）",
            summary="正在通过 HTTP 抓取 Bing 搜索结果页。",
            details=[f"url={url}", f"query={query_text}"],
        )
        try:
            html, meta = self._fetch_page(url)
            results = self._parse_bing(query_text, html)
            emit_api_call(
                stage_key=get_retrieval_stage_key() or "retrieval_initial",
                call_type="http",
                status="completed",
                title="Bing 搜索完成",
                summary=f"Bing 返回 {len(results)} 条结果。",
                details=[
                    f"query={query_text}",
                    f"count={len(results)}",
                    f"status={meta.status_code}",
                    f"latency={meta.latency_ms}ms",
                    f"size={meta.body_bytes}B",
                    f"url={meta.url}",
                ],
            )
            return results
        except Exception as e:
            logger.warning("playwright_bing_error query=%s error=%s", query_text, e)
            emit_api_call(
                stage_key=get_retrieval_stage_key() or "retrieval_initial",
                call_type="http",
                status="error",
                title="Bing 搜索失败",
                summary=f"Bing 搜索出错: {e}",
                details=[f"query={query_text}", f"url={url}", f"error={e}"],
            )
            return []

    def _fetch_page(self, url: str) -> tuple[str, _FetchMeta]:
        import httpx
        read_timeout = max(float(self.settings.retrieval_timeout_seconds), 1.0)
        t0 = time.monotonic()
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
        latency_ms = int((time.monotonic() - t0) * 1000)
        response.raise_for_status()
        body = response.text
        meta = _FetchMeta(
            url=url,
            status_code=response.status_code,
            latency_ms=latency_ms,
            body_bytes=len(body.encode("utf-8")),
        )
        return body, meta

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
                    published_at=item.get("published_at") or "",
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
                    published_at="",
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


_SHANGHAI_TZ = timezone(timedelta(hours=8))


def _parse_baidu_date(raw: str, *, now: Optional[datetime] = None) -> Optional[str]:
    """Turn Baidu's SERP date markers into an ISO date string (YYYY-MM-DD).

    Baidu prefixes results with a `prefix-time` span that carries one of:
      - "2026年7月16日" / "2026年2月25日" (absolute, chinese)
      - "2026-07-24" (absolute, ISO)
      - "今天" / "昨天" / "前天" (relative day)
      - "6天前" / "3小时前" / "45分钟前" (relative delta)
    Returns None when the text has no parseable date (e.g. empty, or a
    stray "官方" tag baidu occasionally puts in the same slot).
    """
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None

    reference = (now or datetime.now(_SHANGHAI_TZ)).astimezone(_SHANGHAI_TZ)
    today: date = reference.date()

    m = re.search(r"(\d{4})[年\-/](\d{1,2})[月\-/](\d{1,2})", text)
    if m:
        try:
            year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return date(year, month, day).isoformat()
        except ValueError:
            return None

    if "今天" in text:
        return today.isoformat()
    if "昨天" in text:
        return (today - timedelta(days=1)).isoformat()
    if "前天" in text:
        return (today - timedelta(days=2)).isoformat()

    m = re.search(r"(\d+)\s*天前", text)
    if m:
        return (today - timedelta(days=int(m.group(1)))).isoformat()
    m = re.search(r"(\d+)\s*(?:小时|个小时)前", text)
    if m:
        delta = timedelta(hours=int(m.group(1)))
        return (reference - delta).date().isoformat()
    m = re.search(r"(\d+)\s*(?:分钟|分)前", text)
    if m:
        delta = timedelta(minutes=int(m.group(1)))
        return (reference - delta).date().isoformat()

    return None


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

        # Baidu marks each hit with a prefix-time span carrying either an
        # absolute date ("2026年7月16日", "2026-07-24") or a relative marker
        # ("昨天", "6天前"). If that span is absent, look inside the embedded
        # <!--s-data:...prefixTime":"..."--> JSON blob Baidu sometimes uses
        # in the "generalLines" summary layout.
        published_at: Optional[str] = None
        time_match = re.search(r'class="[^"]*prefix-time[^"]*"[^>]*>(.*?)</span>', segment, re.DOTALL)
        if time_match:
            published_at = _parse_baidu_date(_clean_text(time_match.group(1)))
        if not published_at:
            json_time_match = re.search(r'"prefixTime"\s*:\s*"([^"]{1,20})"', segment)
            if json_time_match:
                published_at = _parse_baidu_date(json_time_match.group(1))

        items.append({"url": url, "title": title, "snippet": snippet, "source": source, "published_at": published_at})
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
