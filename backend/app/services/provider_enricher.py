from __future__ import annotations

from typing import List, Optional, Tuple

from backend.app.models.schemas import ClaimItem, NormalizedEvent
from backend.app.services.kimi_provider import KimiProvider


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


class ProviderEnricher:
    def __init__(self, provider: Optional[KimiProvider] = None) -> None:
        self.provider = provider or KimiProvider()

    def enrich(self, event: NormalizedEvent) -> Tuple[NormalizedEvent, Optional[List[ClaimItem]]]:
        analysis = self.provider.analyze(event)
        if analysis is None:
            return event, None

        updated_fields = {
            "title": analysis.event.title or event.title,
            "summary": analysis.event.summary or event.summary,
            "keywords": _merge_keywords(analysis.event.keywords, event.keywords) or event.keywords,
        }
        if event.input_type == "text_news":
            updated_fields["source_name"] = analysis.event.source_name or event.source_name
            updated_fields["published_at"] = analysis.event.published_at or event.published_at

        enriched_event = event.model_copy(update=updated_fields)
        return enriched_event, analysis.claims or None
