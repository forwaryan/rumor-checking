"""Persistent, desensitized model-call ledger (borrowed from CPA-Manager-Plus's
per-call accounting idea).

Complements the in-flight ``TokenUsage`` accumulator: TokenUsage lives for one
request and is lost afterwards, so there is no way to answer "how many calls did
model X take last week, at what latency, how often did it error". This ledger
appends one JSONL line per completion attempt to disk so those questions become
answerable offline.

Desensitization is a hard invariant, not a nicety:
  * NEVER write raw prompts, user input, or completion text — only counts.
  * NEVER write the gateway host, base URL, endpoint, or API key. The model NAME
    is allowed (it is runtime-visible), the place it is served is not.
Every public entry point is best-effort and swallows its own errors: a broken
ledger must never take down a real analysis request. Default-off via
``MODEL_LEDGER_ENABLED``; when disabled ``record_call`` is a cheap no-op.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from backend.app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Keys that must never appear in a ledger record. Belt-and-suspenders: the
# dataclass already constrains the shape, but callers pass values in, so we scrub
# defensively before writing in case a field ever carries something it should not.
_FORBIDDEN_SUBSTRINGS = ("api_key", "authorization", "bearer", "base_url", "endpoint", "host")


@dataclass(frozen=True)
class ModelCallRecord:
    """One completion attempt. All fields are safe to persist and share."""

    timestamp: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_tokens: int
    latency_ms: int
    status: str  # "ok" | "empty" | "error"
    error_class: str | None
    trace_id: str | None
    stage_key: str | None


class ModelLedger:
    """Append-only JSONL writer, guarded by a lock for thread-safe fan-out."""

    def __init__(self, ledger_dir: Path) -> None:
        self._dir = ledger_dir
        self._lock = threading.Lock()

    def _path(self) -> Path:
        # One file per UTC day keeps individual files small and greppable without
        # a rotation daemon. Date comes from the record's own timestamp caller-side
        # in tests; here we derive it from now() only for the filename.
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        return self._dir / f"model-calls-{day}.jsonl"

    def append(self, record: ModelCallRecord) -> None:
        payload = asdict(record)
        # Defensive scrub: drop any field whose KEY hints at a secret, and any
        # string VALUE that looks like it embeds one. Records are constructed from
        # safe fields, so this should never fire — it exists so a future careless
        # caller cannot leak through this path.
        safe = {}
        for key, value in payload.items():
            lowered_key = key.lower()
            if any(bad in lowered_key for bad in _FORBIDDEN_SUBSTRINGS):
                continue
            if isinstance(value, str) and any(bad in value.lower() for bad in _FORBIDDEN_SUBSTRINGS):
                continue
            safe[key] = value
        line = json.dumps(safe, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self._dir.mkdir(parents=True, exist_ok=True)
            with self._path().open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")


_ledger: ModelLedger | None = None
_ledger_lock = threading.Lock()


def get_model_ledger(settings: Settings | None = None) -> ModelLedger | None:
    """Return the process-wide ledger, or None when disabled."""
    settings = settings or get_settings()
    if not settings.model_ledger_enabled:
        return None
    global _ledger
    if _ledger is None:
        with _ledger_lock:
            if _ledger is None:
                _ledger = ModelLedger(settings.model_ledger_dir)
    return _ledger


def record_call(
    *,
    provider: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_tokens: int = 0,
    latency_ms: int = 0,
    status: str = "ok",
    error_class: str | None = None,
    trace_id: str | None = None,
    stage_key: str | None = None,
    settings: Settings | None = None,
) -> None:
    """Best-effort ledger append. No-op when disabled; never raises."""
    try:
        ledger = get_model_ledger(settings)
        if ledger is None:
            return
        ledger.append(
            ModelCallRecord(
                timestamp=datetime.now(UTC).isoformat(),
                provider=provider,
                model=model,
                input_tokens=int(input_tokens or 0),
                output_tokens=int(output_tokens or 0),
                cache_tokens=int(cache_tokens or 0),
                latency_ms=int(latency_ms or 0),
                status=status,
                error_class=error_class,
                trace_id=trace_id,
                stage_key=stage_key,
            )
        )
    except Exception as exc:  # pragma: no cover - defensive; ledger must never break a run
        logger.debug("model_ledger_append_failed model=%s error=%s", model, exc)


def _reset_for_tests() -> None:
    global _ledger
    with _ledger_lock:
        _ledger = None
