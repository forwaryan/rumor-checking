from __future__ import annotations

import re
from typing import List, Optional

from fastapi import status

from backend.app.core.exceptions import AppError
from backend.app.models.schemas import AnalyzeRequest, InternalInputType, MockFetchResult, NormalizedEvent
from backend.app.services.contract_utils import (
    default_source_name,
    default_source_url,
    ensure_datetime_string,
    looks_like_url,
    source_name_from_url,
)
from backend.app.services.scenario_library import match_scenario
from backend.app.services.url_content_extractor import UrlContentExtractor


FRONTEND_INPUT_TYPE_MAP = {
    "text": "text_news",
    "url": "url_news",
    "question": "question_only",
}
URL_FALLBACK_REASON_MAP = {
    "partial": "url_content_incomplete",
    "empty": "url_content_missing",
    "timeout": "url_fetch_timeout",
    "error": "url_fetch_failed",
    "unsupported": "url_content_unsupported",
}
URL_FALLBACK_NOTICE_MAP = {
    "url_content_incomplete": "页面正文抽取不完整，系统已降级为保守模式，建议补充正文原文。",
    "url_content_missing": "页面未抽取到可用正文，当前只能给出保守提示，建议直接粘贴正文原文。",
    "url_fetch_timeout": "页面抓取超时，当前未拿到正文，只能先给出保守提示；可稍后重试或直接粘贴正文。",
    "url_fetch_failed": "页面抓取失败，当前未拿到可核查正文，只能先给出保守提示；可稍后重试或直接粘贴正文。",
    "url_content_unsupported": "该链接不是可直接抽取的 HTML 页面，当前只能保守提示，建议提供可打开的正文页或直接粘贴正文。",
    "url_invalid": "当前输入不是可直接抓取的链接，建议检查 URL 是否完整，或直接粘贴正文原文。",
}


def _collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _infer_input_type(raw_input: str) -> InternalInputType:
    compact = raw_input.strip()
    if looks_like_url(compact):
        return "url_news"
    if compact.endswith(("?", "？")) or "真的吗" in compact:
        return "question_only"
    return "text_news"


def _normalize_requested_input_type(raw_input: str, requested: Optional[str]) -> InternalInputType:
    if not requested or requested == "auto":
        return _infer_input_type(raw_input)
    if requested in FRONTEND_INPUT_TYPE_MAP:
        return FRONTEND_INPUT_TYPE_MAP[requested]
    if requested in {"text_news", "url_news", "url_unknown", "question_only"}:
        return requested  # type: ignore[return-value]
    raise AppError(
        status_code=status.HTTP_400_BAD_REQUEST,
        code="invalid_input_type",
        message="Unsupported input_type.",
        details={"input_type": requested},
    )


def _extract_keywords(text: str) -> List[str]:
    candidates = []
    patterns = [
        r"[一-龥]{2,12}(?:监管局|交通局|教育局|生态环境局|日报|中学|化工厂|生物)",
        r"[一-龥]{2,12}(?:酸奶|渡轮|停课|裁员40%|异味|整改|传闻)",
    ]
    for pattern in patterns:
        candidates.extend(re.findall(pattern, text))

    seen = set()
    ordered = []
    for item in candidates:
        cleaned = item.strip("，。！？：；【】")
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            ordered.append(cleaned)
    return ordered[:6]


def _extract_date(text: str) -> Optional[str]:
    match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
    if match:
        return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    match = re.search(r"(\d{1,2})月(\d{1,2})日", text)
    if match:
        return f"2026-{int(match.group(1)):02d}-{int(match.group(2)):02d}"
    return None


class InputNormalizer:
    def __init__(self, url_content_extractor: Optional[UrlContentExtractor] = None) -> None:
        self.url_content_extractor = url_content_extractor or UrlContentExtractor()

    def normalize(self, payload: AnalyzeRequest) -> NormalizedEvent:
        input_type = _normalize_requested_input_type(payload.raw_input, payload.input_type)
        fetch = self._resolve_fetch_result(payload, input_type)
        composite_text = " ".join(
            part
            for part in [
                payload.raw_input,
                getattr(fetch, "title", None),
                getattr(fetch, "body", None),
                getattr(fetch, "snippet", None),
            ]
            if part
        )
        scenario = match_scenario(composite_text)

        fallback_used = False
        fallback_reason = None
        title: Optional[str] = None
        source_name: Optional[str] = None
        source_url: Optional[str] = None
        published_at: Optional[str] = None

        if input_type in {"url_news", "url_unknown"}:
            title, summary, source_name, source_url, published_at, input_type, fallback_used, fallback_reason = self._normalize_url_input(
                payload=payload,
                input_type=input_type,
                fetch=fetch,
            )
        elif input_type == "question_only":
            summary = _collapse_whitespace(payload.raw_input.rstrip("？?"))
            source_name = default_source_name(input_type)
            source_url = default_source_url(input_type, payload.raw_input)
        else:
            title = scenario.title if scenario.scenario_id != "generic" else self._derive_title(payload.raw_input)
            summary = self._derive_summary(payload.raw_input)
            source_name = self._extract_source_name(payload.raw_input) or default_source_name(input_type)
            source_url = default_source_url(input_type, payload.raw_input)
            published_at = _extract_date(payload.raw_input)

        keywords = self._merge_keywords(
            scenario.keywords,
            _extract_keywords(" ".join(filter(None, [title, summary, payload.raw_input]))),
        )

        mode_hint = scenario.default_mode_hint
        if input_type == "question_only":
            mode_hint = "safe"
        elif fallback_used and input_type in {"url_news", "url_unknown"}:
            mode_hint = "safe"

        return NormalizedEvent(
            title=title,
            summary=summary,
            keywords=keywords,
            source_name=source_name,
            source_url=source_url,
            published_at=ensure_datetime_string(published_at) if published_at else None,
            input_type=input_type,
            mode_hint=mode_hint,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            raw_input=payload.raw_input,
        )

    def _resolve_fetch_result(self, payload: AnalyzeRequest, input_type: InternalInputType) -> Optional[MockFetchResult]:
        if input_type not in {"url_news", "url_unknown"}:
            return payload.mock_fetch_result
        if payload.mock_fetch_result is not None:
            return payload.mock_fetch_result
        if looks_like_url(payload.raw_input):
            return self.url_content_extractor.extract(payload.raw_input.strip())
        return None

    def _normalize_url_input(
        self,
        *,
        payload: AnalyzeRequest,
        input_type: InternalInputType,
        fetch: Optional[MockFetchResult],
    ) -> tuple[Optional[str], str, str, str, Optional[str], InternalInputType, bool, Optional[str]]:
        source_url = payload.raw_input.strip() if looks_like_url(payload.raw_input) else default_source_url(input_type, payload.raw_input)
        if fetch and fetch.final_url:
            source_url = fetch.final_url

        source_name = (
            (fetch.source_name if fetch else None)
            or source_name_from_url(source_url)
            or default_source_name(input_type)
        )
        published_at = fetch.published_at if fetch else None

        if fetch is None:
            return (
                "链接页面尚未成功抽取，当前只能先给出保守提示",
                "当前只拿到用户提供的链接，暂未取得可用页面内容，建议稍后重试 URL 抽取或直接粘贴正文原文。",
                source_name,
                source_url,
                published_at,
                "url_unknown",
                True,
                "url_content_missing",
            )

        extracted_text = _collapse_whitespace(fetch.body or fetch.snippet or "")
        title = fetch.title or self._derive_url_title(extracted_text)
        summary = self._derive_summary(extracted_text) if extracted_text else ""

        if fetch.status == "ok" and extracted_text:
            return (
                title or "待核实链接内容",
                summary or "链接页面已抽取，当前可基于页面摘要继续分析。",
                source_name,
                source_url,
                published_at,
                "url_news",
                False,
                None,
            )

        fallback_reason = fetch.fallback_reason or URL_FALLBACK_REASON_MAP.get(fetch.status, "url_fetch_failed")
        fallback_notice = URL_FALLBACK_NOTICE_MAP.get(fallback_reason, URL_FALLBACK_NOTICE_MAP["url_fetch_failed"])
        if summary:
            summary = f"{summary} {fallback_notice}"
        else:
            summary = fallback_notice

        fallback_title = title or self._default_url_title(fetch.status)
        return (
            fallback_title,
            summary,
            source_name,
            source_url,
            published_at,
            "url_unknown",
            True,
            fallback_reason,
        )

    def _derive_summary(self, raw_input: str) -> str:
        stripped = _collapse_whitespace(raw_input)
        if len(stripped) <= 110:
            return stripped
        return stripped[:107] + "..."

    def _derive_title(self, raw_input: str) -> str:
        bracket_match = re.search(r"【([^】]+)】", raw_input)
        if bracket_match:
            return bracket_match.group(1)

        sentence = re.split(r"[。！？]", raw_input, maxsplit=1)[0]
        sentence = sentence.strip()
        return sentence[:28] if sentence else "待核实事件"

    def _derive_url_title(self, extracted_text: str) -> Optional[str]:
        if not extracted_text:
            return None
        title = self._derive_title(extracted_text)
        return title if title != "待核实事件" else None

    def _default_url_title(self, fetch_status: str) -> str:
        if fetch_status == "partial":
            return "链接页面信息抽取不完整，当前只能先给出保守提示"
        if fetch_status == "unsupported":
            return "链接页面暂不支持自动抽取，当前只能先给出保守提示"
        if fetch_status == "timeout":
            return "链接页面抓取超时，当前只能先给出保守提示"
        return "链接页面抽取失败，当前只能先给出保守提示"

    def _extract_source_name(self, raw_input: str) -> Optional[str]:
        match = re.search(r"([一-龥]{2,20}(?:监管局|交通局|教育局|生态环境局|日报|中学|化工厂))", raw_input)
        return match.group(1) if match else None

    def _merge_keywords(self, scenario_keywords: List[str], extracted_keywords: List[str]) -> List[str]:
        seen = set()
        ordered: List[str] = []
        for item in scenario_keywords + extracted_keywords:
            if item and item not in seen:
                seen.add(item)
                ordered.append(item)
        return ordered[:6]
