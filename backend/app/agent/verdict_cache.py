"""Cross-session verdict cache — case-level memory with freshness.

When the same rumor is submitted again within a TTL window, the cached verdict
is returned immediately without re-running the full pipeline. The cache keys
on a claim fingerprint (normalized text hash) and includes a freshness timestamp
so stale verdicts can be expired.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# Default TTL: 6 hours. A rumor's truth status can change as new information
# emerges, so we don't cache forever.
DEFAULT_TTL_SECONDS = 6 * 3600


def fingerprint(text: str) -> str:
    """Create a stable fingerprint from claim text.

    Normalizes whitespace and punctuation, lowercases, then SHA-256 hashes.
    """
    import re
    normalized = re.sub(r"[\s，。！？?!；;:：、""''\"']", "", text).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class CachedVerdict:
    """A cached verdict result."""

    fingerprint: str
    raw_input: str
    verdict: str
    confidence: str
    claim_results_json: str
    cached_at: float
    ttl_seconds: float = DEFAULT_TTL_SECONDS
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_fresh(self) -> bool:
        return (time.time() - self.cached_at) < self.ttl_seconds

    @property
    def age_seconds(self) -> float:
        return time.time() - self.cached_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "raw_input": self.raw_input,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "claim_results_json": self.claim_results_json,
            "cached_at": self.cached_at,
            "ttl_seconds": self.ttl_seconds,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CachedVerdict:
        return cls(
            fingerprint=data["fingerprint"],
            raw_input=data["raw_input"],
            verdict=data["verdict"],
            confidence=data["confidence"],
            claim_results_json=data["claim_results_json"],
            cached_at=data["cached_at"],
            ttl_seconds=data.get("ttl_seconds", DEFAULT_TTL_SECONDS),
            metadata=data.get("metadata", {}),
        )


class VerdictCache(Protocol):
    def get(self, fp: str) -> CachedVerdict | None:
        ...

    def put(self, verdict: CachedVerdict) -> None:
        ...

    def invalidate(self, fp: str) -> None:
        ...


class MemoryVerdictCache:
    """In-memory cache — suitable for single-process deployments."""

    def __init__(self, max_entries: int = 1000):
        self._store: dict[str, CachedVerdict] = {}
        self._max_entries = max_entries
        self._lock = threading.Lock()

    def get(self, fp: str) -> CachedVerdict | None:
        with self._lock:
            entry = self._store.get(fp)
            if entry is None:
                return None
            if not entry.is_fresh:
                del self._store[fp]
                return None
            return entry

    def put(self, verdict: CachedVerdict) -> None:
        with self._lock:
            if len(self._store) >= self._max_entries and verdict.fingerprint not in self._store:
                oldest_key = min(self._store, key=lambda k: self._store[k].cached_at)
                del self._store[oldest_key]
            self._store[verdict.fingerprint] = verdict

    def invalidate(self, fp: str) -> None:
        with self._lock:
            self._store.pop(fp, None)

    @property
    def size(self) -> int:
        return len(self._store)


class DiskVerdictCache:
    """File-backed cache — persists across process restarts.

    Fronted by a small in-process LRU so repeated lookups for the same claim
    within one process (e.g. critic re-checks a claim mid-run) don't re-parse
    JSON from disk each time. The LRU mirrors puts too, so a just-written entry
    is immediately hot without a round-trip. Invalidate clears both sides.
    """

    def __init__(
        self,
        cache_dir: Path,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        *,
        memory_cache_size: int = 128,
    ):
        self._cache_dir = cache_dir
        self._ttl = ttl_seconds
        self._memory = MemoryVerdictCache(max_entries=memory_cache_size)

    def _path(self, fp: str) -> Path:
        return self._cache_dir / f"{fp}.json"

    def get(self, fp: str) -> CachedVerdict | None:
        cached = self._memory.get(fp)
        if cached is not None:
            return cached
        path = self._path(fp)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            verdict = CachedVerdict.from_dict(data)
            if not verdict.is_fresh:
                path.unlink(missing_ok=True)
                return None
            # Warm the in-process cache so the next lookup avoids re-parsing.
            self._memory.put(verdict)
            return verdict
        except (json.JSONDecodeError, KeyError):
            path.unlink(missing_ok=True)
            return None

    def put(self, verdict: CachedVerdict) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._path(verdict.fingerprint).write_text(
            json.dumps(verdict.to_dict(), ensure_ascii=False),
            encoding="utf-8",
        )
        self._memory.put(verdict)

    def invalidate(self, fp: str) -> None:
        self._path(fp).unlink(missing_ok=True)
        self._memory.invalidate(fp)
