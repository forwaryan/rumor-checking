from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from backend.app.models.schemas import MockFetchResult

CACHE_SCHEMA_VERSION = 1
UTC = timezone.utc


class UrlFetchCache:
    def __init__(self, *, cache_root: Path, ttl_seconds: float) -> None:
        self.cache_root = cache_root
        self.ttl_seconds = ttl_seconds

    def build_cache_key(self, *, url: str) -> str:
        normalized_url = url.strip()
        digest = hashlib.sha256(f"v{CACHE_SCHEMA_VERSION}|{normalized_url}".encode("utf-8")).hexdigest()
        return digest[:24]

    def read(self, *, url: str) -> Optional[MockFetchResult]:
        path = self._path_for(url=url)
        if not path.exists():
            return None

        payload = json.loads(path.read_text(encoding="utf-8"))
        expires_at = self._parse_datetime(payload.get("expires_at"))
        if expires_at is not None and expires_at <= datetime.now(UTC):
            return None

        result = payload.get("result")
        if not isinstance(result, dict):
            return None
        return MockFetchResult(**result)

    def write(self, *, url: str, result: MockFetchResult) -> Path:
        path = self._path_for(url=url)
        path.parent.mkdir(parents=True, exist_ok=True)

        created_at = datetime.now(UTC)
        expires_at = created_at + timedelta(seconds=max(self.ttl_seconds, 0))
        payload = {
            "version": CACHE_SCHEMA_VERSION,
            "url": url,
            "cache_key": self.build_cache_key(url=url),
            "created_at": created_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "result": result.model_dump(mode="json"),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _path_for(self, *, url: str) -> Path:
        key = self.build_cache_key(url=url)
        return self.cache_root / f"{key}.json"

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
