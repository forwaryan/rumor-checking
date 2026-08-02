from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from backend.app.core.config import Settings, get_settings
from backend.app.services.contract_utils import ensure_datetime_string, loads_lenient_json
from backend.app.services.progress import emit_api_call, get_retrieval_stage_key
from backend.app.services.retrieval_models import (
    SearchResult,
    build_independence_key,
    detect_signal_tags,
    infer_source_category,
)

logger = logging.getLogger(__name__)

OFFICIAL_HOST_MARKERS = ("gov.cn", ".gov", "police", "court", "edu.cn", "piyao.org.cn")
TOP_TIER_DOMAINS = {
    "news.cn",
    "xinhuanet.com",
    "people.com.cn",
    "cctv.com",
    "gmw.cn",
    "hongxingnews.com",
    "chinanews.com.cn",
    "cnr.cn",
    "southcn.com",
    "ctdsb.net",
    "hangzhou.com.cn",
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "nytimes.com",
    "thepaper.cn",
    "caixin.com",
}
PORTAL_MARKERS = ("news", "ifeng", "sohu", "163.com", "qq.com", "sina", "msn", "yicai")
PLACEHOLDER_HOSTS = {"example.com", "example.org", "example.net", "localhost"}
LLM_WEB_SEARCH_TOOL = {"type": "builtin_function", "function": {"name": "$web_search"}}
LLM_WEB_SEARCH_SYSTEM_PROMPT = """
You are the web retrieval stage for a rumor-checking backend.
You must call $web_search before answering and then return one JSON object with this schema:
{
  "question": "string",
  "verdict_hint": "string or null",
  "results": [
    {
      "title": "string",
      "url": "https://...",
      "source_name": "string or null",
      "published_at": "ISO-8601 / YYYY-MM-DD / null",
      "snippet": "string or null"
    }
  ]
}
Rules:
- You must call $web_search first. If you did not use web search, do not output example or placeholder JSON.
- Keep only public webpages directly relevant to the user's claim. Prioritize official statements, hospital updates, police notices, major news outlets, and direct responses.
- Every `url` must come from the current web search. Never invent links and never use example.com style placeholders.
- If both rumor and rebuttal exist, include both, but place rebuttals or official responses first.
- `verdict_hint` must be a single conservative sentence such as "available public sources currently lean false" or "public evidence is still insufficient".
- Output JSON only. No Markdown.
""".strip()


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    compact = re.sub(r"\s+", " ", value).strip()
    return compact or None


def _source_name_from_url(url: str) -> str:
    hostname = urlparse(url).netloc.lower()
    return hostname or "unknown-source"


def _published_at(raw_value: Any) -> str:
    value = _clean_text(raw_value)
    if not value:
        return ensure_datetime_string(None)
    if re.fullmatch(r"\d{8}T\d{6}Z", value):
        parsed = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        return parsed.isoformat()
    return ensure_datetime_string(value)


def _infer_source_tier(url: str, source_name: str) -> str:
    host = (urlparse(url).netloc or source_name).lower()
    if any(marker in host for marker in OFFICIAL_HOST_MARKERS):
        return "S"
    if any(host == domain or host.endswith(f".{domain}") for domain in TOP_TIER_DOMAINS):
        return "A"
    if any(marker in host for marker in PORTAL_MARKERS):
        return "B"
    return "C"


# Continuous authority score in [0, 100]. Tier gives the anchor; the rest are
# small additive/deductive signals so within-tier ranking is no longer arbitrary.
# Kept intentionally lightweight — see backend/tests/test_authority_score.py for
# the invariants each band pins.
_TIER_BASE_SCORE = {"S": 40.0, "A": 32.0, "B": 20.0, "C": 10.0}
_HOSTING_PLATFORM_MARKERS = (
    ".blog.",
    ".wordpress.com",
    ".wixsite.com",
    ".typepad.com",
    ".blogspot.com",
    ".medium.com",
    ".substack.com",
    ".weebly.com",
    ".over-blog.com",
)
_SUSPICIOUS_TLDS = (".top", ".xyz", ".click", ".buzz", ".loan", ".gq", ".tk", ".cf")
_CLICKBAIT_TITLE_MARKERS = (
    "震惊",
    "全网疯传",
    "删前速看",
    "紧急扩散",
    "紧急提醒",
    "疯狂转发",
    "刚刚曝光",
    "内部消息",
    "别再吃了",
    "危险",
)
_ADVERTORIAL_URL_MARKERS = ("/promotion/", "/advertorial/", "/sponsored/", "/adv/", "/ad/")


def _authority_score(url: str, source_name: str, tier: str, title: str = "") -> float:
    """Score a source's authority on a 0–100 continuous scale.

    Signals (each independent, then summed and clamped):
    - tier base: S=40 A=32 B=20 C=10
    - whitelist bonus: exact TOP_TIER_DOMAINS or piyao hit → +15
    - HTTPS + independent-domain: +4 each (hosted blog platforms lose the domain bonus)
    - suspicious signals: sketchy TLD -8, advertorial URL segment -10, clickbait title marker -10
    """
    parsed = urlparse(url)
    host = (parsed.netloc or source_name or "").lower()
    if host.startswith("www."):
        host = host[4:]

    score = _TIER_BASE_SCORE.get(tier, 10.0)

    if any(host == domain or host.endswith(f".{domain}") for domain in TOP_TIER_DOMAINS):
        score += 15.0
    if "piyao.org.cn" in host:
        score += 15.0

    if parsed.scheme == "https":
        score += 4.0
    if not any(marker in host for marker in _HOSTING_PLATFORM_MARKERS):
        score += 4.0

    if any(host.endswith(tld) for tld in _SUSPICIOUS_TLDS):
        score -= 8.0

    lowered_path = (parsed.path or "").lower()
    if any(marker in lowered_path for marker in _ADVERTORIAL_URL_MARKERS):
        score -= 10.0

    if title and any(marker in title for marker in _CLICKBAIT_TITLE_MARKERS):
        score -= 10.0

    return max(0.0, min(100.0, score))


def infer_source_signals(url: str, source_name: str, title: str = "") -> tuple[str, float]:
    """One-shot helper: return (tier, authority_score) for a hit."""
    tier = _infer_source_tier(url, source_name)
    return tier, _authority_score(url, source_name, tier, title)


class RetrievalProvider(Protocol):
    name: str
    enabled: bool

    def search(self, query_text: str) -> list[SearchResult]:
        ...


class GdeltNewsProvider:
    name = "gdelt"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def enabled(self) -> bool:
        return self.settings.retrieval_provider == self.name

    def search(self, query_text: str) -> list[SearchResult]:
        if not self.enabled:
            return []

        emit_api_call(
            stage_key=get_retrieval_stage_key() or "retrieval_initial",
            call_type="http",
            status="running",
            title="调用 GDELT API",
            summary="正在请求 GDELT 新闻接口。",
            details=[
                f"endpoint={self.settings.retrieval_gdelt_base_url}",
                f"query={query_text}",
            ],
        )
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
        results = self._parse_articles(query_text, response.json())
        emit_api_call(
            stage_key=get_retrieval_stage_key() or "retrieval_initial",
            call_type="http",
            status="completed",
            title="GDELT API 返回",
            summary=f"GDELT 返回 {len(results)} 条可用结果。",
            details=[
                f"status_code={response.status_code}",
                f"query={query_text}",
            ],
        )
        return results

    def _parse_articles(self, query_text: str, payload: Any) -> list[SearchResult]:
        articles = payload.get("articles") if isinstance(payload, dict) else None
        if not isinstance(articles, list):
            return []

        results: list[SearchResult] = []
        for index, article in enumerate(articles, start=1):
            if not isinstance(article, dict):
                continue

            url = _clean_text(article.get("url"))
            title = _clean_text(article.get("title"))
            if not url or not title:
                continue

            source_name = self._source_name(article, url)
            published_at = _published_at(article.get("seendate") or article.get("date"))
            snippet = _clean_text(article.get("snippet")) or title
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
                    source_tier=_infer_source_tier(url, source_name),
                    source_category=infer_source_category(url, source_name),
                    independence_key=build_independence_key(url, source_name),
                    signal_tags=detect_signal_tags(title, snippet, source_name),
                )
            )
            if len(results) >= self.settings.retrieval_max_results:
                break

        logger.info("gdelt_retrieval_results query=%s count=%s", query_text, len(results))
        return results

    def _source_name(self, article: dict[str, Any], url: str) -> str:
        domain = _clean_text(article.get("domain"))
        if domain:
            return domain
        return _source_name_from_url(url)


class LlmWebSearchProvider:
    name = "kimi"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def enabled(self) -> bool:
        return self.settings.uses_agent_retrieval and bool(self.settings.llm_api_key)

    def search(self, query_text: str) -> list[SearchResult]:
        if not self.enabled:
            raise RuntimeError("LLM web search is not configured.")

        content = self._run_search_loop(query_text)
        results = self._parse_results(query_text, content)
        if content and not results:
            raise RuntimeError("LLM web search returned no usable search results payload.")
        logger.info("llm_web_search_results query=%s count=%s", query_text, len(results))
        return results

    def _run_search_loop(self, query_text: str) -> str:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": LLM_WEB_SEARCH_SYSTEM_PROMPT},
            {"role": "user", "content": self._build_user_prompt(query_text)},
        ]
        tool_used = False

        for _ in range(4):
            message = self._request_completion(messages)
            tool_calls = message.get("tool_calls")
            if isinstance(tool_calls, list) and tool_calls:
                tool_used = True
                messages.append(self._assistant_history_message(message))
                for tool_call in tool_calls:
                    tool_name = self._tool_name(tool_call)
                    tool_arguments = self._tool_arguments(tool_call)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": str(tool_call.get("id") or ""),
                            "name": tool_name,
                            "content": json.dumps(tool_arguments, ensure_ascii=False),
                        }
                    )
                continue

            content = self._coerce_content(message.get("content"))
            if not tool_used:
                logger.warning("llm_web_search_skipped_tool query=%s", query_text)
                raise RuntimeError("LLM web search skipped the required web_search tool.")
            return content

        raise RuntimeError("LLM web search exceeded tool rounds")

    def _request_completion(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        model = self._search_model()
        emit_api_call(
            stage_key=get_retrieval_stage_key() or "retrieval_initial",
            call_type="llm",
            status="running",
            title="调用 LLM web search",
            summary="正在请求 LLM chat/completions，并要求先执行 $web_search。",
            details=[
                f"model={model}",
            ],
        )
        response = httpx.post(
            f"{self.settings.base_url_for_model(model)}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.settings.llm_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "temperature": self._request_temperature(),
                "response_format": {"type": "json_object"},
                "messages": messages,
                "tools": [LLM_WEB_SEARCH_TOOL],
                "max_tokens": 2048,
            },
            timeout=self.settings.retrieval_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        tool_call_count = 0
        choice = payload.get("choices", [{}])[0]
        message = choice.get("message")
        if isinstance(message, dict) and isinstance(message.get("tool_calls"), list):
            tool_call_count = len(message.get("tool_calls") or [])
        emit_api_call(
            stage_key=get_retrieval_stage_key() or "retrieval_initial",
            call_type="llm",
            status="completed",
            title="LLM web search 返回",
            summary="LLM 已返回一轮 tool-calling / JSON 响应。",
            details=[
                f"status_code={response.status_code}",
                f"model={model}",
                f"tool_calls={tool_call_count}",
            ],
        )
        if not isinstance(message, dict):
            raise ValueError("LLM web search returned an invalid message payload")
        return message

    def _search_model(self) -> str:
        return self.settings.llm_search_model.strip()

    def _request_temperature(self) -> float:
        return self.settings.llm_temperature

    def _build_user_prompt(self, query_text: str) -> str:
        return (
            "Search the web for the following rumor-checking question.\n"
            "Prioritize official statements, hospital updates, police notices, major news outlets, direct responses, and debunks.\n"
            "If the search finds both rumor and rebuttal, keep both, but list the rebuttal or official response first.\n"
            "Question:\n"
            f"{query_text.strip()}\n"
        )

    def _assistant_history_message(self, message: dict[str, Any]) -> dict[str, Any]:
        history_message: dict[str, Any] = {
            "role": "assistant",
            "content": self._coerce_content(message.get("content")),
        }
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            history_message["tool_calls"] = tool_calls
        return history_message

    def _tool_name(self, tool_call: dict[str, Any]) -> str:
        function = tool_call.get("function")
        if not isinstance(function, dict):
            return ""
        return str(function.get("name") or "")

    def _tool_arguments(self, tool_call: dict[str, Any]) -> dict[str, Any]:
        function = tool_call.get("function")
        if not isinstance(function, dict):
            return {}
        raw_arguments = function.get("arguments")
        if not isinstance(raw_arguments, str) or not raw_arguments.strip():
            return {}
        try:
            parsed = json.loads(raw_arguments)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _coerce_content(self, content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip())
            return "\n".join(parts)
        return ""

    def _parse_results(self, query_text: str, content: str) -> list[SearchResult]:
        payload = loads_lenient_json(content)
        if payload is None:
            return []

        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            return []

        results: list[SearchResult] = []
        for index, item in enumerate(raw_results, start=1):
            if not isinstance(item, dict):
                continue

            url = _clean_text(item.get("url"))
            title = _clean_text(item.get("title"))
            if not url or not title or self._looks_placeholder_url(url):
                continue

            source_name = _clean_text(item.get("source_name")) or _source_name_from_url(url)
            snippet = _clean_text(item.get("snippet")) or title
            results.append(
                SearchResult(
                    case_id="real_search",
                    query=query_text,
                    result_id=f"web-{index}",
                    title=title,
                    url=url,
                    source_name=source_name,
                    published_at=_published_at(item.get("published_at")),
                    snippet=snippet,
                    source_tier=_infer_source_tier(url, source_name),
                    source_category=infer_source_category(url, source_name),
                    independence_key=build_independence_key(url, source_name),
                    signal_tags=detect_signal_tags(title, snippet, source_name),
                )
            )
            if len(results) >= self.settings.retrieval_max_results:
                break
        return results

    def _looks_placeholder_url(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return True
        host = parsed.netloc.lower()
        if not host:
            return True
        return any(host == placeholder or host.endswith(f".{placeholder}") for placeholder in PLACEHOLDER_HOSTS)
