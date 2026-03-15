from __future__ import annotations

import re
from datetime import datetime
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
from backend.app.services.entity_anchor import extract_subject_anchors
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
OFFICIAL_SOURCE_HINTS = (
    "监管局",
    "交通局",
    "教育局",
    "生态环境局",
    "政府",
    "警方",
    "法院",
    "医院",
    "委员会",
    "市场监管",
    "中学",
)
MEDIA_SOURCE_HINTS = (
    "日报",
    "晚报",
    "时报",
    "电视台",
    "新闻",
    "观察",
)
KEYWORD_PHRASES = (
    "海州市市场监管局",
    "清河市交通局",
    "北城区化工厂",
    "海州新鲜屋",
    "晨星生物",
    "停业整改",
    "渡轮停航",
    "生态环境局",
    "裁员40%",
    "酸奶",
    "渡轮",
    "大雾",
    "停课",
    "异味",
    "核查",
    "传闻",
)
KEYWORD_PATTERNS = (
    r"[\u4e00-\u9fa5]{2,20}(?:市场监管局|交通局|教育局|生态环境局|化工厂|公司|医院|政府|警方|委员会|日报|中学|生物|运营公司|平台)",
    r"裁员\d+%",
    r"[\u4e00-\u9fa5A-Za-z0-9]{2,20}(?=(?:明天|今晚|下周|本周|近日|已|已经|将|会|正在)?(?:全线|全面)?(?:停航|停运|停课|裁员|脑出血|去世|死亡|核查|回应|通报|检修|整改|恢复|救治|辟谣))",
)
TIME_PATTERNS = (
    r"\d{4}[-/]\d{1,2}[-/]\d{1,2}",
    r"\d{4}年\d{1,2}月\d{1,2}日",
    r"\d{1,2}月\d{1,2}日(?:上午|下午|凌晨|晚上|晚间|中午)?",
    r"(?:明天|今晚|今早|今天|今日|昨天|昨日|下周|本周|近日|近期)",
)
NOISY_INPUT_MARKERS = (
    "截图",
    "聊天记录",
    "群聊",
    "朋友圈",
    "爆料",
    "网传",
    "短视频",
    "视频",
    "录音",
)
NOISY_PREFIX_PATTERN = re.compile(
    r"^(?:【[^】]+】\s*)?(?:网传|爆料称|截图显示|聊天记录显示|群聊(?:消息)?(?:显示|称)?|朋友圈(?:消息)?(?:显示|称)?|短视频(?:显示|称)?|视频(?:显示|称)?|录音(?:显示|称)?)\s*"
)


def _collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _extract_time_keywords(text: str) -> List[str]:
    ordered: List[str] = []
    seen = set()
    for pattern in TIME_PATTERNS:
        for item in re.findall(pattern, text):
            cleaned = _collapse_whitespace(item).strip("，。！？:：；;")
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                ordered.append(cleaned)
    return ordered[:3]


def _rewrite_noisy_text(text: str) -> str:
    compact = _collapse_whitespace(text)
    compact = re.sub(r"^(?:【[^】]+】\s*)+", "", compact)
    compact = NOISY_PREFIX_PATTERN.sub("", compact)
    carrier_match = re.search(
        r"(?:截图|聊天记录|群聊|爆料|网传|短视频|视频|录音)[^:：]{0,12}[:：](.+)$",
        compact,
    )
    if carrier_match:
        compact = carrier_match.group(1).strip()
    compact = re.sub(r"[\"'“”‘’]+", "", compact)
    return _collapse_whitespace(compact)


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
    compact = _collapse_whitespace(text)
    candidates: List[str] = []

    for phrase in KEYWORD_PHRASES:
        if phrase in compact:
            candidates.append(phrase)

    for pattern in KEYWORD_PATTERNS:
        candidates.extend(re.findall(pattern, compact))

    candidates.extend(extract_subject_anchors(compact))
    candidates.extend(_extract_time_keywords(compact))

    seen = set()
    ordered = []
    for item in candidates:
        cleaned = item.strip("，。！？:：；;【】")
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            ordered.append(cleaned)
    return ordered[:6]


def _extract_date(text: str) -> Optional[str]:
    match = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?", text)
    if match:
        return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    match = re.search(r"(\d{1,2})月(\d{1,2})日", text)
    if match:
        return f"{datetime.now().year}-{int(match.group(1)):02d}-{int(match.group(2)):02d}"
    return None


def _infer_mode_hint(
    *,
    input_type: InternalInputType,
    summary: str,
    source_name: Optional[str],
    published_at: Optional[str],
    keywords: List[str],
    fallback_used: bool,
) -> str:
    if input_type == "question_only" or fallback_used:
        return "safe"
    media_signal = bool(source_name and any(marker in source_name for marker in MEDIA_SOURCE_HINTS))
    official_signal = bool(source_name and any(marker in source_name for marker in OFFICIAL_SOURCE_HINTS))
    detail_signal = bool(published_at) or len(summary) >= 40 or len(keywords) >= 2
    if media_signal:
        return "partial"
    if official_signal and detail_signal:
        return "complete_or_partial"
    return "partial"


class InputNormalizer:
    def __init__(self, url_content_extractor: Optional[UrlContentExtractor] = None) -> None:
        self.url_content_extractor = url_content_extractor or UrlContentExtractor()

    def normalize(self, payload: AnalyzeRequest) -> NormalizedEvent:
        input_type = _normalize_requested_input_type(payload.raw_input, payload.input_type)
        fetch = self._resolve_fetch_result(payload, input_type)

        fallback_used = False
        fallback_reason = None
        title: Optional[str] = None
        source_name: Optional[str] = None
        source_url: Optional[str] = None
        published_at: Optional[str] = None
        event_source = "input_normalized"

        if input_type in {"url_news", "url_unknown"}:
            title, summary, source_name, source_url, published_at, input_type, fallback_used, fallback_reason, event_source = self._normalize_url_input(
                payload=payload,
                input_type=input_type,
                fetch=fetch,
            )
        elif input_type == "question_only":
            summary = _collapse_whitespace(payload.raw_input.rstrip("?？"))
            source_name = None
            source_url = default_source_url(input_type, payload.raw_input)
        else:
            title = self._derive_title(payload.raw_input)
            summary = self._derive_summary(payload.raw_input)
            source_name = self._extract_source_name(payload.raw_input) or default_source_name(input_type)
            source_url = default_source_url(input_type, payload.raw_input)
            published_at = _extract_date(payload.raw_input)

        keywords = self._dedupe_keywords(
            _extract_keywords(" ".join(filter(None, [title, summary, source_name, payload.raw_input])))
        )
        mode_hint = _infer_mode_hint(
            input_type=input_type,
            summary=summary,
            source_name=source_name,
            published_at=published_at,
            keywords=keywords,
            fallback_used=fallback_used,
        )

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
            event_source=event_source,
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
    ) -> tuple[Optional[str], str, str, str, Optional[str], InternalInputType, bool, Optional[str], str]:
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
                "input_normalized",
            )

        extracted_text = _collapse_whitespace(fetch.body or fetch.snippet or "")
        title = fetch.title or self._derive_url_title(extracted_text)
        summary = self._derive_summary(extracted_text) if extracted_text else ""
        event_source = "url_extract" if any([fetch.title, fetch.body, fetch.snippet]) else "input_normalized"

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
                event_source,
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
            event_source,
        )

    def _derive_summary(self, raw_input: str) -> str:
        stripped = _rewrite_noisy_text(raw_input) if any(marker in raw_input for marker in NOISY_INPUT_MARKERS) else _collapse_whitespace(raw_input)
        sentences = [item.strip() for item in re.split(r"[。！？?!]", stripped) if item.strip()]
        if len(sentences) >= 2:
            candidate = "。".join(sentences[:2])
            if 18 <= len(candidate) <= 110:
                return candidate
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
        match = re.search(
            r"([A-Za-z0-9一-龥]{2,24}(?:市场监管局|监管局|交通局|教育局|生态环境局|运营公司|日报|晚报|电视台|中学|学校|大学|化工厂|集团|公司|医院|政府|警方|平台|委员会))",
            raw_input,
        )
        return match.group(1) if match else None

    def _dedupe_keywords(self, extracted_keywords: List[str]) -> List[str]:
        seen = set()
        ordered: List[str] = []
        for item in extracted_keywords:
            if item and item not in seen:
                seen.add(item)
                ordered.append(item)
        return ordered[:6]
