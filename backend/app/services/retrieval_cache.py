from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from backend.app.services.retrieval_deduper import compact_text
from backend.app.services.retrieval_models import RetrievalBundle

CACHE_SCHEMA_VERSION = 1
UTC = timezone.utc


class RetrievalCache:
    def __init__(self, *, cache_root: Path, ttl_seconds: float) -> None:
        self.cache_root = cache_root
        self.ttl_seconds = ttl_seconds

    def build_cache_key(self, *, query_text: str, provider_name: str) -> str:
        normalized_query = compact_text(query_text)
        digest = hashlib.sha256(f"v{CACHE_SCHEMA_VERSION}|{provider_name}|{normalized_query}".encode("utf-8")).hexdigest()
        return digest[:24]

    def read(self, *, query_text: str, provider_name: str, allow_stale: bool = False) -> Optional[RetrievalBundle]:
        path = self._path_for(query_text=query_text, provider_name=provider_name)
        if not path.exists():
            return None

        payload = json.loads(path.read_text(encoding="utf-8"))
        expires_at = self._parse_datetime(payload.get("expires_at"))
        now = datetime.now(UTC)
        is_stale = expires_at is not None and expires_at <= now
        if is_stale and not allow_stale:
            return None

        bundle = RetrievalBundle.from_dict(payload["bundle"])
        cache_key = str(payload.get("cache_key") or self.build_cache_key(query_text=query_text, provider_name=provider_name))
        return bundle.with_runtime_metadata(
            cache_key=cache_key,
            cache_status="stale_hit" if is_stale else "hit",
        )

    def write(self, *, query_text: str, provider_name: str, bundle: RetrievalBundle) -> Path:
        path = self._path_for(query_text=query_text, provider_name=provider_name)
        path.parent.mkdir(parents=True, exist_ok=True)

        created_at = datetime.now(UTC)
        expires_at = created_at + timedelta(seconds=max(self.ttl_seconds, 0))
        cache_key = self.build_cache_key(query_text=query_text, provider_name=provider_name)
        payload = {
            "version": CACHE_SCHEMA_VERSION,
            "provider_name": provider_name,
            "query": query_text,
            "normalized_query": compact_text(query_text),
            "cache_key": cache_key,
            "created_at": created_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "bundle": bundle.with_runtime_metadata(cache_key=cache_key).to_dict(),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _path_for(self, *, query_text: str, provider_name: str) -> Path:
        key = self.build_cache_key(query_text=query_text, provider_name=provider_name)
        return self.cache_root / provider_name / f"{key}.json"

    def _parse_datetime(self, value: object) -> Optional[datetime]:
        if not isinstance(value, str) or not value:
            return None
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
