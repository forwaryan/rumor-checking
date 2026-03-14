from __future__ import annotations

import json
import logging
import re
from html import unescape
from typing import Any, Optional

import httpx

from backend.app.core.config import Settings, get_settings
from backend.app.models.schemas import MockFetchResult
from backend.app.services.contract_utils import looks_like_url, source_name_from_url

logger = logging.getLogger(__name__)

USER_AGENT = "rumor-checking-url-fetcher/0.1"
JSON_LD_RE = re.compile(
    r"<script\b[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    flags=re.IGNORECASE | re.DOTALL,
)
META_TAG_RE = re.compile(r"<meta\b[^>]*>", flags=re.IGNORECASE)
TITLE_RE = re.compile(r"<title\b[^>]*>(.*?)</title>", flags=re.IGNORECASE | re.DOTALL)
H1_RE = re.compile(r"<h1\b[^>]*>(.*?)</h1>", flags=re.IGNORECASE | re.DOTALL)
ARTICLE_RE = re.compile(r"<article\b[^>]*>(.*?)</article>", flags=re.IGNORECASE | re.DOTALL)
MAIN_RE = re.compile(r"<main\b[^>]*>(.*?)</main>", flags=re.IGNORECASE | re.DOTALL)
BODY_BLOCK_RE = re.compile(r"<(?:p|h2|h3|li)\b[^>]*>(.*?)</(?:p|h2|h3|li)>", flags=re.IGNORECASE | re.DOTALL)
TIME_RE = re.compile(r"<time\b[^>]*?(?:datetime=[\"']([^\"']+)[\"']|>(.*?)</time>)", flags=re.IGNORECASE | re.DOTALL)
ATTR_RE = re.compile(r"([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s\"'>/]+)")
COMMENT_RE = re.compile(r"<!--.*?-->", flags=re.DOTALL)
UNWANTED_BLOCK_RE = re.compile(
    r"<(script|style|noscript|svg|iframe|footer|nav|aside|form)\b.*?</\1>",
    flags=re.IGNORECASE | re.DOTALL,
)
BLOCK_BREAK_RE = re.compile(r"</?(?:p|div|article|section|main|li|ul|ol|h[1-6]|br)\b[^>]*>", flags=re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")
UNWANTED_TEXT_RE = re.compile(
    r"(相关阅读|相关推荐|上一篇|下一篇|分享到|扫码|广告|版权声明|责任编辑|点击展开|返回顶部)",
    flags=re.IGNORECASE,
)
DATE_RE = re.compile(
    r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})(?:日)?(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?(?:\s*(Z|[+-]\d{2}:?\d{2}))?"
)


class UrlContentExtractor:
    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

    def extract(self, url: str) -> MockFetchResult:
        normalized_url = url.strip()
        source_name = source_name_from_url(normalized_url)
        if not looks_like_url(normalized_url):
            return MockFetchResult(
                status="error",
                source_name=source_name,
                final_url=normalized_url,
                fallback_reason="url_invalid",
                error_message="invalid_url",
            )

        try:
            response = self._fetch(normalized_url)
        except httpx.TimeoutException:
            logger.warning("url_fetch_timeout url=%s", normalized_url)
            return MockFetchResult(
                status="timeout",
                source_name=source_name,
                final_url=normalized_url,
                fallback_reason="url_fetch_timeout",
                error_message="timeout",
            )
        except httpx.HTTPError as exc:
            logger.warning("url_fetch_failed url=%s error_type=%s", normalized_url, exc.__class__.__name__)
            return MockFetchResult(
                status="error",
                source_name=source_name,
                final_url=normalized_url,
                fallback_reason="url_fetch_failed",
                error_message=exc.__class__.__name__,
            )
        except Exception as exc:
            logger.warning("url_extract_unexpected_error url=%s error_type=%s", normalized_url, exc.__class__.__name__)
            return MockFetchResult(
                status="error",
                source_name=source_name,
                final_url=normalized_url,
                fallback_reason="url_fetch_failed",
                error_message=exc.__class__.__name__,
            )

        final_url = str(response.url)
        source_name = source_name_from_url(final_url) or source_name
        content_type = response.headers.get("content-type", "").lower()
        html = response.text[: self.settings.url_fetch_max_chars]

        if not self._looks_like_html(content_type, html):
            return MockFetchResult(
                status="unsupported",
                source_name=source_name,
                final_url=final_url,
                content_type=content_type or None,
                fallback_reason="url_content_unsupported",
                error_message="unsupported_content_type",
            )

        return self._extract_from_html(
            html=html,
            final_url=final_url,
            content_type=content_type,
            fallback_source_name=source_name,
        )

    def _fetch(self, url: str) -> httpx.Response:
        response = httpx.get(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
            },
            follow_redirects=True,
            timeout=self.settings.url_fetch_timeout_seconds,
        )
        response.raise_for_status()
        return response

    def _extract_from_html(
        self,
        *,
        html: str,
        final_url: str,
        content_type: str,
        fallback_source_name: Optional[str],
    ) -> MockFetchResult:
        meta = self._extract_meta_map(html)
        json_ld_nodes = self._extract_json_ld_nodes(html)

        title = self._pick_first(
            meta.get("og:title"),
            meta.get("twitter:title"),
            meta.get("title"),
            *(self._clean_optional_string(node.get("headline")) for node in json_ld_nodes if isinstance(node, dict)),
            *(self._clean_optional_string(node.get("name")) for node in json_ld_nodes if isinstance(node, dict)),
            self._extract_tag_text(TITLE_RE, html),
            self._extract_tag_text(H1_RE, html),
        )
        source_name = self._pick_first(
            meta.get("og:site_name"),
            meta.get("application-name"),
            meta.get("al:android:app_name"),
            *(self._extract_name_field(node.get("publisher")) for node in json_ld_nodes if isinstance(node, dict)),
            *(self._extract_name_field(node.get("author")) for node in json_ld_nodes if isinstance(node, dict)),
            fallback_source_name,
        )
        published_at = self._pick_first(
            self._normalize_date_candidate(meta.get("article:published_time")),
            self._normalize_date_candidate(meta.get("article:modified_time")),
            self._normalize_date_candidate(meta.get("publishdate")),
            self._normalize_date_candidate(meta.get("pubdate")),
            self._normalize_date_candidate(meta.get("date")),
            self._normalize_date_candidate(meta.get("datepublished")),
            *(self._normalize_date_candidate(node.get("datePublished")) for node in json_ld_nodes if isinstance(node, dict)),
            *(self._normalize_date_candidate(node.get("dateCreated")) for node in json_ld_nodes if isinstance(node, dict)),
            *(self._normalize_date_candidate(node.get("dateModified")) for node in json_ld_nodes if isinstance(node, dict)),
            self._normalize_date_candidate(self._extract_time_value(html)),
        )
        description = self._pick_first(
            meta.get("description"),
            meta.get("og:description"),
            meta.get("twitter:description"),
        )
        json_ld_body = self._pick_first(
            *(self._clean_optional_string(node.get("articleBody")) for node in json_ld_nodes if isinstance(node, dict)),
        )
        body = self._extract_body_text(html, json_ld_body=json_ld_body)
        snippet = self._build_snippet(description=description, body=body)
        status = self._determine_status(title=title, body=body, snippet=snippet)
        fallback_reason = None if status == "ok" else self._fallback_reason_for_status(status)

        return MockFetchResult(
            status=status,
            title=title,
            body=body,
            snippet=snippet,
            source_name=source_name,
            published_at=published_at,
            final_url=final_url,
            content_type=content_type or None,
            fallback_reason=fallback_reason,
        )

    def _looks_like_html(self, content_type: str, html: str) -> bool:
        if "html" in content_type or "xhtml" in content_type:
            return True
        sample = html[:500].lower()
        return "<html" in sample or "<article" in sample or "<body" in sample

    def _extract_meta_map(self, html: str) -> dict[str, str]:
        values: dict[str, str] = {}
        for match in META_TAG_RE.finditer(html):
            attrs = self._parse_attrs(match.group(0))
            content = self._clean_optional_string(attrs.get("content") or attrs.get("value"))
            if not content:
                continue
            for key in (attrs.get("property"), attrs.get("name"), attrs.get("itemprop")):
                normalized_key = self._clean_optional_string(key)
                if normalized_key:
                    values[normalized_key.lower()] = content
        return values

    def _extract_json_ld_nodes(self, html: str) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        for raw_payload in JSON_LD_RE.findall(html):
            payload = raw_payload.strip()
            if not payload:
                continue
            payload = payload.removeprefix("<!--").removesuffix("-->").strip()
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError:
                continue
            for item in self._walk_json_ld(parsed):
                if isinstance(item, dict):
                    nodes.append(item)
        return nodes

    def _walk_json_ld(self, value: Any) -> list[Any]:
        items: list[Any] = []
        if isinstance(value, dict):
            items.append(value)
            for nested in value.values():
                items.extend(self._walk_json_ld(nested))
        elif isinstance(value, list):
            for nested in value:
                items.extend(self._walk_json_ld(nested))
        return items

    def _extract_body_text(self, html: str, *, json_ld_body: Optional[str]) -> Optional[str]:
        candidates = [self._extract_blocks(fragment) for fragment in ARTICLE_RE.findall(html)]
        candidates.extend(self._extract_blocks(fragment) for fragment in MAIN_RE.findall(html))
        candidates.append(self._extract_blocks(html))

        best_blocks = max(candidates, key=self._score_blocks, default=[])
        body = self._join_blocks(best_blocks)
        if body:
            return body
        return self._truncate(json_ld_body, 4000)

    def _extract_blocks(self, fragment: str) -> list[str]:
        cleaned_fragment = COMMENT_RE.sub(" ", fragment)
        cleaned_fragment = UNWANTED_BLOCK_RE.sub(" ", cleaned_fragment)

        blocks: list[str] = []
        for match in BODY_BLOCK_RE.finditer(cleaned_fragment):
            text = self._clean_html_text(match.group(1))
            if self._is_body_block(text):
                blocks.append(text)

        if not blocks:
            fallback_text = self._clean_html_text(cleaned_fragment)
            for segment in re.split(r"\n{2,}", fallback_text):
                text = self._clean_optional_string(segment)
                if self._is_body_block(text):
                    blocks.append(text)

        return self._dedupe_blocks(blocks)

    def _score_blocks(self, blocks: list[str]) -> int:
        return sum(len(item) for item in blocks) + len(blocks) * 40

    def _join_blocks(self, blocks: list[str]) -> Optional[str]:
        if not blocks:
            return None

        joined: list[str] = []
        total_length = 0
        max_length = min(self.settings.url_fetch_max_chars, 4000)
        for block in blocks:
            compact = self._clean_optional_string(block)
            if not compact:
                continue
            remaining = max_length - total_length
            if remaining <= 0:
                break
            clipped = compact[:remaining].rstrip()
            if not clipped:
                break
            joined.append(clipped)
            total_length += len(clipped)

        if not joined:
            return None
        return "\n\n".join(joined)

    def _build_snippet(self, *, description: Optional[str], body: Optional[str]) -> Optional[str]:
        if description:
            return self._truncate(description, 180)
        if not body:
            return None

        sentences = [item.strip() for item in re.split(r"(?<=[。！？.!?])\s*", body) if item.strip()]
        preview = " ".join(sentences[:2]) if sentences else body
        return self._truncate(preview, 180)

    def _determine_status(self, *, title: Optional[str], body: Optional[str], snippet: Optional[str]) -> str:
        body_length = len(body or "")
        if (title and body_length >= 140) or body_length >= 280:
            return "ok"
        if title or snippet or body_length >= 40:
            return "partial"
        return "empty"

    def _fallback_reason_for_status(self, status: str) -> str:
        mapping = {
            "partial": "url_content_incomplete",
            "empty": "url_content_missing",
        }
        return mapping.get(status, "url_content_missing")

    def _parse_attrs(self, raw_tag: str) -> dict[str, str]:
        attrs: dict[str, str] = {}
        for key, value in ATTR_RE.findall(raw_tag):
            cleaned = value[1:-1] if value[:1] in {'"', "'"} and value[-1:] == value[:1] else value
            attrs[key.lower()] = unescape(cleaned.strip())
        return attrs

    def _extract_tag_text(self, pattern: re.Pattern[str], html: str) -> Optional[str]:
        match = pattern.search(html)
        if not match:
            return None
        return self._clean_html_text(match.group(1))

    def _extract_time_value(self, html: str) -> Optional[str]:
        for candidate in TIME_RE.findall(html):
            for raw_value in candidate:
                cleaned = self._clean_html_text(raw_value)
                if cleaned:
                    return cleaned
        return None

    def _extract_name_field(self, value: Any) -> Optional[str]:
        if isinstance(value, str):
            return self._clean_optional_string(value)
        if isinstance(value, dict):
            return self._clean_optional_string(value.get("name"))
        if isinstance(value, list):
            for item in value:
                candidate = self._extract_name_field(item)
                if candidate:
                    return candidate
        return None

    def _normalize_date_candidate(self, value: Any) -> Optional[str]:
        cleaned = self._clean_optional_string(value)
        if not cleaned:
            return None

        match = DATE_RE.search(cleaned)
        if not match:
            return None

        year, month, day, hour, minute, second, tz = match.groups()
        base = f"{year}-{int(month):02d}-{int(day):02d}"
        if hour is None or minute is None:
            return base

        normalized = f"{base}T{int(hour):02d}:{int(minute):02d}:{int(second or '0'):02d}"
        if tz:
            if tz != "Z" and ":" not in tz:
                tz = f"{tz[:3]}:{tz[3:]}"
            normalized += tz
        return normalized

    def _clean_html_text(self, raw_html: str) -> Optional[str]:
        compact = COMMENT_RE.sub(" ", raw_html)
        compact = BLOCK_BREAK_RE.sub("\n", compact)
        compact = TAG_RE.sub(" ", compact)
        compact = unescape(compact)
        lines = [re.sub(r"\s+", " ", line).strip() for line in compact.splitlines()]
        merged = "\n".join(line for line in lines if line)
        return self._clean_optional_string(merged)

    def _clean_optional_string(self, value: Any) -> Optional[str]:
        if not isinstance(value, str):
            return None
        compact = re.sub(r"\s+", " ", value).strip()
        return compact or None

    def _pick_first(self, *values: Optional[str]) -> Optional[str]:
        for value in values:
            cleaned = self._clean_optional_string(value)
            if cleaned:
                return cleaned
        return None

    def _dedupe_blocks(self, blocks: list[str]) -> list[str]:
        seen = set()
        ordered: list[str] = []
        for block in blocks:
            cleaned = self._clean_optional_string(block)
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            ordered.append(cleaned)
        return ordered

    def _is_body_block(self, text: Optional[str]) -> bool:
        if not text:
            return False
        if UNWANTED_TEXT_RE.search(text):
            return False
        if len(text) >= 30:
            return True
        return len(text) >= 18 and any(marker in text for marker in "。！？.!?")

    def _truncate(self, text: Optional[str], limit: int) -> Optional[str]:
        cleaned = self._clean_optional_string(text)
        if not cleaned:
            return None
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: limit - 3].rstrip() + "..."
