from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from backend.app.core.config import Settings, get_settings
from backend.app.services.retrieval_models import RetrievalBundle, SearchResult

UTC = timezone.utc


class RetrievalCache:
    def __init__(self, settings: Optional[Settings] = None, cache_dir: Optional[Path] = None) -> None:
        self.settings = settings or get_settings()
        self.cache_dir = cache_dir or self.settings.retrieval_cache_dir

    @property
    def enabled(self) -> bool:
        return self.settings.retrieval_cache_enabled

    def load(self, provider_name: str, query: str, *, allow_stale: bool = False) -> Optional[RetrievalBundle]:
        if not self.enabled:
            return None

        path = self._path(provider_name, query)
        if not path.exists():
            return None

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

        created_at = self._parse_datetime(payload.get("created_at"))
        if created_at is None:
            return None

        is_stale = datetime.now(UTC) - created_at > timedelta(hours=self.settings.retrieval_cache_ttl_hours)
        if is_stale and not allow_stale:
            return None

        bundle_payload = payload.get("bundle")
        if not isinstance(bundle_payload, dict):
            return None
        return self._bundle_from_payload(bundle_payload)

    def save(self, provider_name: str, query: str, bundle: RetrievalBundle) -> None:
        if not self.enabled:
            return

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "provider": provider_name,
            "query": query,
            "created_at": datetime.now(UTC).isoformat(),
            "bundle": self._bundle_to_payload(bundle),
        }
        self._path(provider_name, query).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _path(self, provider_name: str, query: str) -> Path:
        digest = hashlib.sha256(f"{provider_name}:{query}".encode("utf-8")).hexdigest()[:16]
        return self.cache_dir / f"{provider_name}-{digest}.json"

    def _bundle_to_payload(self, bundle: RetrievalBundle) -> dict:
        return {
            "query": bundle.query,
            "matched_case_id": bundle.matched_case_id,
            "mode_hint": bundle.mode_hint,
            "raw_results": [self._result_to_payload(item) for item in bundle.raw_results],
            "canonical_results": [self._result_to_payload(item) for item in bundle.canonical_results],
            "expected_origin_result_id": bundle.expected_origin_result_id,
            "expected_turning_point_result_id": bundle.expected_turning_point_result_id,
        }

    def _bundle_from_payload(self, payload: dict) -> RetrievalBundle:
        return RetrievalBundle(
            query=payload.get("query", ""),
            matched_case_id=payload.get("matched_case_id"),
            mode_hint=payload.get("mode_hint", "safe"),
            raw_results=tuple(self._result_from_payload(item) for item in payload.get("raw_results", [])),
            canonical_results=tuple(self._result_from_payload(item) for item in payload.get("canonical_results", [])),
            expected_origin_result_id=payload.get("expected_origin_result_id"),
            expected_turning_point_result_id=payload.get("expected_turning_point_result_id"),
        )

    def _result_to_payload(self, result: SearchResult) -> dict:
        return {
            "case_id": result.case_id,
            "query": result.query,
            "result_id": result.result_id,
            "title": result.title,
            "url": result.url,
            "source_name": result.source_name,
            "published_at": result.published_at,
            "snippet": result.snippet,
            "source_tier": result.source_tier,
            "duplicate_of": result.duplicate_of,
            "canonical_result_id": result.canonical_result_id,
            "duplicate_reason": result.duplicate_reason,
            "merged_result_ids": list(result.merged_result_ids),
            "merged_notes": list(result.merged_notes),
        }

    def _result_from_payload(self, payload: dict) -> SearchResult:
        return SearchResult(
            case_id=payload["case_id"],
            query=payload["query"],
            result_id=payload["result_id"],
            title=payload["title"],
            url=payload["url"],
            source_name=payload["source_name"],
            published_at=payload["published_at"],
            snippet=payload["snippet"],
            source_tier=payload["source_tier"],
            duplicate_of=payload.get("duplicate_of"),
            canonical_result_id=payload.get("canonical_result_id"),
            duplicate_reason=payload.get("duplicate_reason"),
            merged_result_ids=tuple(payload.get("merged_result_ids", [])),
            merged_notes=tuple(payload.get("merged_notes", [])),
        )

    def _parse_datetime(self, value: object) -> Optional[datetime]:
        if not isinstance(value, str):
            return None
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
