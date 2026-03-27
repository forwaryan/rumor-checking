from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Sequence
from urllib.parse import quote_plus, urlparse
from xml.etree import ElementTree

import httpx

from backend.app.services.contract_utils import ensure_datetime_string
from backend.app.services.retrieval_models import SearchResult

FetchText = Callable[[str, float], str]

OFFICIAL_SOURCE_MARKERS = (
    "gov",
    ".gov",
    "政府",
    "监管局",
    "教育局",
    "交通局",
    "公安",
    "法院",
    "检察院",
    "学校",
    "医院",
    "委员会",
    "市场监管",
    "应急管理",
    "官方",
    "company announcement",
    "official site",
)
TRUSTED_MEDIA_MARKERS = (
    "新华社",
    "人民日报",
    "央视",
    "中新网",
    "澎湃",
    "财新",
    "证券时报",
    "新华网",
    "Reuters",
    "Associated Press",
    "AP News",
    "BBC",
    "CNN",
    "Bloomberg",
    "The Wall Street Journal",
    "Daily",
    "Herald",
    "Times",
    "News",
    "日报",
    "晚报",
    "电视台",
    "新闻网",
)
AGGREGATOR_MARKERS = (
    "聚合",
    "快讯",
    "论坛",
    "博客",
    "转载",
    "Yahoo",
    "MSN",
    "Flipboard",
    "搜狐",
    "腾讯新闻",
)
LOW_TRUST_MARKERS = (
    "微博",
    "小红书",
    "贴吧",
    "论坛",
    "博客",
    "自媒体",
    "爆料",
    "rumor",
    "viral",
)


class RetrievalProviderError(RuntimeError):
    pass


class GoogleNewsRSSProvider:
    provider_name = "google_news_rss"

    def __init__(
        self,
        *,
        endpoint_template: str,
        fetch_text: FetchText | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.endpoint_template = endpoint_template
        self.fetch_text = fetch_text or self._default_fetch_text
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def search(self, query_text: str, *, timeout_seconds: float, limit: int) -> Sequence[SearchResult]:
        encoded_query = quote_plus(query_text)
        url = self.endpoint_template.format(query=encoded_query)
        try:
            payload = self.fetch_text(url, timeout_seconds)
        except httpx.TimeoutException as exc:
            raise RetrievalProviderError("provider timeout") from exc
        except httpx.HTTPError as exc:
            raise RetrievalProviderError("provider request failed") from exc
        except Exception as exc:
            raise RetrievalProviderError("provider fetch failed") from exc

        try:
            root = ElementTree.fromstring(payload)
        except ElementTree.ParseError as exc:
            raise RetrievalProviderError("provider returned invalid rss") from exc

        results: list[SearchResult] = []
        retrieved_at = self.clock().astimezone(timezone.utc).isoformat()
        for index, item in enumerate(root.findall(".//item"), start=1):
            if len(results) >= limit:
                break
            title = self._clean_text(item.findtext("title"))
            link = self._clean_text(item.findtext("link"))
            description = self._clean_text(item.findtext("description"))
            source_name = self._extract_source_name(item, title)
            if not title or not link:
                continue

            clean_title = self._strip_source_suffix(title, source_name)
            published_at = self._parse_pub_date(item.findtext("pubDate"))
            snippet = self._build_snippet(description, clean_title)
            source_tier = self._classify_source_tier(link=link, source_name=source_name, title=clean_title, snippet=snippet)
            result_id = self._build_result_id(query_text=query_text, link=link, title=clean_title, index=index)
            results.append(
                SearchResult(
                    case_id=f"live:{self.provider_name}",
                    query=query_text,
                    result_id=result_id,
                    title=clean_title,
                    url=link,
                    source_name=source_name,
                    published_at=published_at,
                    snippet=snippet,
                    source_tier=source_tier,
                    provider_name=self.provider_name,
                    retrieved_at=retrieved_at,
                )
            )
        return results

    def _default_fetch_text(self, url: str, timeout_seconds: float) -> str:
        response = httpx.get(
            url,
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={
                "User-Agent": "rumor-checking/0.1 (+public-rss-retrieval)",
                "Accept": "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8",
            },
        )
        response.raise_for_status()
        return response.text

    def _extract_source_name(self, item: ElementTree.Element, title: str) -> str:
        source_node = item.find("source")
        if source_node is not None and source_node.text:
            source_name = self._clean_text(source_node.text)
            if source_name:
                return source_name
        if " - " in title:
            return title.rsplit(" - ", 1)[-1].strip()
        return "公开来源"

    def _strip_source_suffix(self, title: str, source_name: str) -> str:
        suffix = f" - {source_name}"
        if source_name and title.endswith(suffix):
            return title[: -len(suffix)].strip()
        return title.strip()

    def _build_snippet(self, description: str, title: str) -> str:
        snippet = re.sub(r"\s+", " ", description).strip()
        if not snippet:
            return title
        return snippet[:220]

    def _parse_pub_date(self, value: str | None) -> str:
        if value:
            try:
                parsed = parsedate_to_datetime(value)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.isoformat()
            except (TypeError, ValueError, IndexError):
                pass
        return ensure_datetime_string(value)

    def _classify_source_tier(self, *, link: str, source_name: str, title: str, snippet: str) -> str:
        source_text = f"{source_name} {title} {snippet}".lower()
        domain = urlparse(link).netloc.lower()
        if any(marker.lower() in source_text or marker in domain for marker in OFFICIAL_SOURCE_MARKERS):
            return "S"
        if any(marker.lower() in source_text or marker.lower() in domain for marker in TRUSTED_MEDIA_MARKERS):
            return "A"
        if any(marker.lower() in source_text or marker.lower() in domain for marker in LOW_TRUST_MARKERS):
            return "C"
        if any(marker.lower() in source_text or marker.lower() in domain for marker in AGGREGATOR_MARKERS):
            return "B"
        if domain.endswith((".gov", ".gov.cn", ".edu.cn")):
            return "S"
        if re.search(r"(news|daily|times|post|herald|日报|晚报|电视台|新闻网)", source_name, flags=re.IGNORECASE):
            return "A"
        return "B"

    def _build_result_id(self, *, query_text: str, link: str, title: str, index: int) -> str:
        digest = hashlib.sha1(f"{query_text}|{link}|{title}".encode("utf-8")).hexdigest()[:10]
        return f"gnr-{index}-{digest}"

    def _clean_text(self, value: str | None) -> str:
        if not value:
            return ""
        clean = html.unescape(value)
        clean = re.sub(r"<[^>]+>", " ", clean)
        clean = re.sub(r"\s+", " ", clean)
        return clean.strip()
