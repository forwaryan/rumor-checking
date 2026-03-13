from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

import httpx

from backend.app.core.config import Settings, get_settings
from backend.app.models.schemas import ClaimItem, NormalizedEvent, ProviderAnalysis, ProviderEventDraft
from backend.app.services.contract_utils import ensure_datetime_string

logger = logging.getLogger(__name__)

ALLOWED_CLAIM_TYPES = {"fact", "opinion", "prediction", "unverifiable"}
SYSTEM_PROMPT = """
你是谣言研判后端的结构化抽取器。你的任务不是下最终 verdict，而是从输入文本中抽取事件信息和待评估 claims。
你必须返回一个 JSON 对象，不能输出额外解释。
JSON 结构如下：
{
  "event": {
    "title": "string 或 null",
    "summary": "string 或 null",
    "keywords": ["string"],
    "source_name": "string 或 null",
    "published_at": "ISO-8601 datetime 或 YYYY-MM-DD 或 null"
  },
  "claims": [
    {
      "claim": "string",
      "claim_type": "fact|opinion|prediction|unverifiable"
    }
  ]
}
约束：
- 只基于用户输入做结构化抽取，不要假装已经检索互联网。
- claim 最多 5 条，keywords 最多 6 条。
- 如果输入是提问，把提问改写成待核查 claim，但不要编造来源。
- 不确定时使用 null、空数组，或者把 claim_type 设为 unverifiable。
""".strip()


class KimiProvider:
    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

    @property
    def enabled(self) -> bool:
        return self.settings.kimi_enabled

    def analyze(self, event: NormalizedEvent) -> Optional[ProviderAnalysis]:
        if not self.enabled:
            return None
        if event.input_type in {"url_news", "url_unknown"} or event.fallback_used:
            return None

        try:
            content = self._request_completion(event)
            analysis = self._parse_content(content)
        except Exception as exc:
            logger.warning(
                "kimi_provider_failed input_type=%s error_type=%s",
                event.input_type,
                exc.__class__.__name__,
            )
            return None

        if analysis is None:
            logger.warning("kimi_provider_empty_result input_type=%s", event.input_type)
            return None
        return analysis

    def _request_completion(self, event: NormalizedEvent) -> str:
        response = httpx.post(
            f"{self.settings.kimi_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.settings.kimi_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.settings.kimi_model,
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": self._build_user_prompt(event)},
                ],
            },
            timeout=self.settings.provider_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        choice = payload.get("choices", [{}])[0]
        message = choice.get("message", {})
        return self._coerce_content(message.get("content"))

    def _build_user_prompt(self, event: NormalizedEvent) -> str:
        return (
            f"input_type: {event.input_type}\n"
            f"title_hint: {event.title or ''}\n"
            f"summary_hint: {event.summary}\n"
            f"raw_input:\n{event.raw_input}\n"
        )

    def _coerce_content(self, content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip())
            return "\n".join(parts)
        raise ValueError("Unsupported Kimi content format")

    def _parse_content(self, content: str) -> Optional[ProviderAnalysis]:
        payload = self._extract_json_payload(content)
        if payload is None:
            return None

        raw_event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
        provider_event = ProviderEventDraft(
            title=self._clean_optional_string(raw_event.get("title")),
            summary=self._clean_optional_string(raw_event.get("summary")),
            keywords=self._clean_string_list(raw_event.get("keywords")),
            source_name=self._clean_optional_string(raw_event.get("source_name")),
            published_at=self._clean_optional_datetime(raw_event.get("published_at")),
        )

        claims: List[ClaimItem] = []
        raw_claims = payload.get("claims") if isinstance(payload.get("claims"), list) else []
        for item in raw_claims:
            if not isinstance(item, dict):
                continue
            claim_text = self._clean_optional_string(item.get("claim"))
            claim_type = self._clean_optional_string(item.get("claim_type"))
            if not claim_text or claim_type not in ALLOWED_CLAIM_TYPES:
                continue
            claims.append(ClaimItem(claim=claim_text, claim_type=claim_type))
            if len(claims) >= 5:
                break

        if not provider_event.title and not provider_event.summary and not claims:
            return None
        return ProviderAnalysis(event=provider_event, claims=claims)

    def _extract_json_payload(self, content: str) -> Optional[Dict[str, Any]]:
        stripped = content.strip()
        candidates = [stripped]

        fenced_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", stripped, flags=re.DOTALL)
        if fenced_match:
            candidates.insert(0, fenced_match.group(1).strip())

        brace_start = stripped.find("{")
        brace_end = stripped.rfind("}")
        if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
            candidates.append(stripped[brace_start : brace_end + 1])

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        return None

    def _clean_optional_string(self, value: Any) -> Optional[str]:
        if not isinstance(value, str):
            return None
        compact = re.sub(r"\s+", " ", value).strip()
        return compact or None

    def _clean_string_list(self, value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        ordered: List[str] = []
        seen = set()
        for item in value:
            cleaned = self._clean_optional_string(item)
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            ordered.append(cleaned)
            if len(ordered) >= 6:
                break
        return ordered

    def _clean_optional_datetime(self, value: Any) -> Optional[str]:
        cleaned = self._clean_optional_string(value)
        if not cleaned:
            return None
        return ensure_datetime_string(cleaned)
