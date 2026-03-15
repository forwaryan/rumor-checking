from __future__ import annotations

import re
from typing import List, Optional, Tuple

from backend.app.models.schemas import ClaimItem, NormalizedEvent
from backend.app.services.kimi_provider import KimiProvider

GENERIC_TITLE_MARKERS = ("待核实", "相关情况", "截图", "热搜", "网友热议")
GENERIC_SUMMARY_MARKERS = ("引发关注", "有待核实", "仍待核实", "请以官方通报为准", "详情以官方通报为准")
GENERIC_SOURCE_NAMES = {"社交平台", "网友爆料", "网传消息", "网络消息"}
EVENT_ACTION_PATTERN = re.compile(r"通报|回应|辟谣|核查|暂停|恢复|抽检|停课|停运|裁员|召回|否认|证实|救治|溯源")
ENTITY_PATTERN = re.compile(r"[\u4e00-\u9fff]{2,}(局|公司|医院|学校|平台|部门|政府|警方|管理局|运营公司)")


def _clean_text(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    compact = re.sub(r"\s+", " ", value).strip()
    return compact or None


def _merge_keywords(primary: List[str], fallback: List[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for item in primary + fallback:
        cleaned = item.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)
        if len(ordered) >= 6:
            break
    return ordered


def _has_specific_signal(text: str) -> bool:
    return bool(ENTITY_PATTERN.search(text) or EVENT_ACTION_PATTERN.search(text) or re.search(r"\d", text))


def _looks_generic(text: str, *, field: str) -> bool:
    if field == "title":
        return any(marker in text for marker in GENERIC_TITLE_MARKERS) and not _has_specific_signal(text)
    return any(marker in text for marker in GENERIC_SUMMARY_MARKERS) and not _has_specific_signal(text)


def _derive_title_from_summary(summary: Optional[str]) -> Optional[str]:
    cleaned = _clean_text(summary)
    if not cleaned:
        return None
    sentence = re.split(r"[。！？?!]", cleaned, maxsplit=1)[0].strip("，,：:；; ")
    if not sentence:
        return None
    if len(sentence) > 28:
        first_chunk = re.split(r"[，,；;]", sentence, maxsplit=1)[0].strip()
        if 8 <= len(first_chunk) <= 28:
            sentence = first_chunk
        else:
            sentence = sentence[:28]
    if _looks_generic(sentence, field="title"):
        return None
    return sentence


def _text_score(text: Optional[str], *, field: str) -> int:
    cleaned = _clean_text(text)
    if not cleaned:
        return -100

    length = len(cleaned)
    score = 0
    if field == "title":
        score += 18 if 8 <= length <= 24 else max(0, 18 - abs(length - 18))
        if re.search(r"[，,：:；;。！？?!【】]", cleaned):
            score -= 10
        if any(token in cleaned for token in ["回应", "通报", "辟谣", "核查", "停课", "停运", "召回"]):
            score += 4
    else:
        score += 14 if 18 <= length <= 90 else max(0, 14 - abs(length - 48) // 2)
        if re.search(r"[？?【】]", cleaned):
            score -= 8
        if any(token in cleaned for token in ["热搜", "截图", "是真的吗", "网传"]):
            score -= 6
        if any(token in cleaned for token in ["回应", "通报", "辟谣", "核查", "表示", "称"]):
            score += 4

    if _has_specific_signal(cleaned):
        score += 10
    if _looks_generic(cleaned, field=field):
        score -= 18
    return score


def _choose_better_text(field: str, preferred: Optional[str], fallback: Optional[str]) -> Optional[str]:
    preferred_clean = _clean_text(preferred)
    fallback_clean = _clean_text(fallback)
    if not preferred_clean:
        return fallback_clean
    if not fallback_clean:
        return preferred_clean
    preferred_score = _text_score(preferred_clean, field=field)
    fallback_score = _text_score(fallback_clean, field=field)
    return preferred_clean if preferred_score >= fallback_score else fallback_clean


def _choose_source_name(preferred: Optional[str], fallback: Optional[str]) -> Optional[str]:
    preferred_clean = _clean_text(preferred)
    fallback_clean = _clean_text(fallback)
    if preferred_clean and preferred_clean not in GENERIC_SOURCE_NAMES:
        return preferred_clean
    return fallback_clean


class ProviderEnricher:
    def __init__(self, provider: Optional[KimiProvider] = None) -> None:
        self.provider = provider or KimiProvider()

    def enrich(self, event: NormalizedEvent) -> Tuple[NormalizedEvent, Optional[List[ClaimItem]]]:
        analysis = self.provider.analyze(event)
        provider_title = _choose_better_text(
            "title",
            analysis.event.title,
            _derive_title_from_summary(analysis.event.summary),
        )
        updated_fields = {
            "title": _choose_better_text("title", provider_title, event.title),
            "summary": _choose_better_text("summary", analysis.event.summary, event.summary) or event.summary,
            "keywords": _merge_keywords(analysis.event.keywords, event.keywords) or event.keywords,
            "event_source": "provider_enriched",
        }
        if event.input_type == "text_news":
            updated_fields["source_name"] = _choose_source_name(analysis.event.source_name, event.source_name)
            updated_fields["published_at"] = analysis.event.published_at or event.published_at

        enriched_event = event.model_copy(update=updated_fields)
        return enriched_event, analysis.claims
