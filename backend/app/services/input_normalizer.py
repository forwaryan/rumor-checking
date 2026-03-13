from __future__ import annotations

import re
from typing import List, Optional

from fastapi import status

from backend.app.core.exceptions import AppError
from backend.app.models.schemas import AnalyzeRequest, InternalInputType, NormalizedEvent
from backend.app.services.contract_utils import default_source_name, default_source_url, ensure_datetime_string, looks_like_url
from backend.app.services.scenario_library import match_scenario


FRONTEND_INPUT_TYPE_MAP = {
    "text": "text_news",
    "url": "url_news",
    "question": "question_only",
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
    def normalize(self, payload: AnalyzeRequest) -> NormalizedEvent:
        input_type = _normalize_requested_input_type(payload.raw_input, payload.input_type)
        fetch = payload.mock_fetch_result
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
            source_url = payload.raw_input.strip() if looks_like_url(payload.raw_input) else default_source_url(input_type, payload.raw_input)
            source_name = default_source_name(input_type)

            if fetch is None:
                title = "链接内容尚未抽取，当前只能先给出保守提示"
                summary = "当前只拿到用户提供的链接，后端尚未接入真实正文抽取，因此不能直接核查正文内容。建议补充正文或等待 URL 抽取链路完成。"
                fallback_used = True
                fallback_reason = "url_content_missing"
                input_type = "url_unknown"
            else:
                title = fetch.title or scenario.title
                summary_source = fetch.body or fetch.snippet or scenario.summary
                summary = _collapse_whitespace(summary_source)
                source_name = fetch.source_name or default_source_name(input_type)
                published_at = fetch.published_at or None
                fallback_used = fetch.status != "ok" or not (fetch.body or "").strip()
                if fallback_used:
                    fallback_reason = "url_content_incomplete"
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
