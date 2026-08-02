from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

ProgressCallback = Callable[[dict[str, Any]], None]

_progress_callback: ContextVar[ProgressCallback | None] = ContextVar("progress_callback", default=None)
# The stage_key that owns the retrieval currently in flight. Providers emit their
# own HTTP/LLM sub-events without knowing which pipeline step invoked them, so the
# retrieval service publishes the owning stage here and providers read it back —
# otherwise every provider event lands in a hardcoded "retrieval_initial" card
# regardless of whether it was the initial, follow-up, or investigation round.
_retrieval_stage_key: ContextVar[str | None] = ContextVar("retrieval_stage_key", default=None)


@dataclass
class StageTiming:
    """First-seen `running` timestamp and last-seen terminal timestamp for one stage_key.

    Kept as raw ISO strings so replay corpora can round-trip them without a
    datetime object hanging in memory.
    """

    stage_key: str
    started_at: str | None = None
    ended_at: str | None = None
    final_status: str | None = None
    # Insertion order over stage_keys; used to preserve the natural pipeline
    # order in the final trace since dict iteration is insertion-ordered.
    ordinal: int = 0
    # Retained for future parallel-group awareness — the supervisor emits its
    # branch stages under a common parent stage_key (e.g. "agent_planning"),
    # so a downstream Node can flag ``is_parallel_group=True`` by comparing
    # sibling timings.
    parent_stage_key: str | None = None


class StageTimingCollector:
    """Per-run collector for stage lifecycle timestamps.

    A single instance covers one AnalyzeRequest run — the analyze pipeline
    creates it and installs it via ``set_stage_timing_collector`` before
    calling into the code that emits stage events. The collector is
    ContextVar-scoped so concurrent requests do not clobber each other.
    """

    _RUNNING = "running"
    _TERMINAL_STATUSES = frozenset({"completed", "warning", "error", "skipped"})

    def __init__(self) -> None:
        self._by_stage: dict[str, StageTiming] = {}
        self._next_ordinal = 0

    def record(self, *, stage_key: str, status: str, timestamp: str) -> None:
        entry = self._by_stage.get(stage_key)
        if entry is None:
            entry = StageTiming(stage_key=stage_key, ordinal=self._next_ordinal)
            self._next_ordinal += 1
            self._by_stage[stage_key] = entry
        if status == self._RUNNING and entry.started_at is None:
            entry.started_at = timestamp
        elif status in self._TERMINAL_STATUSES:
            entry.ended_at = timestamp
            entry.final_status = status
            # A terminal status without a prior running (i.e. an emitter that
            # only fires 'completed') still gets a start so the trace shows a
            # non-null started_at — treat this event as both start and end.
            if entry.started_at is None:
                entry.started_at = timestamp

    def get(self, stage_key: str) -> StageTiming | None:
        return self._by_stage.get(stage_key)

    def as_dict(self) -> dict[str, StageTiming]:
        return dict(self._by_stage)

    def earliest_started_at(self) -> str | None:
        """The first `running` timestamp across all recorded stages.

        Used as the run's t=0 anchor when computing per-stage ``offset_ms``.
        """
        starts = [t.started_at for t in self._by_stage.values() if t.started_at]
        return min(starts) if starts else None


_stage_timing_collector: ContextVar[StageTimingCollector | None] = ContextVar(
    "stage_timing_collector", default=None,
)


def set_stage_timing_collector(collector: StageTimingCollector | None) -> Token:
    return _stage_timing_collector.set(collector)


def get_stage_timing_collector() -> StageTimingCollector | None:
    return _stage_timing_collector.get()


def reset_stage_timing_collector(token: Token) -> None:
    _stage_timing_collector.reset(token)


def set_progress_callback(callback: ProgressCallback) -> Token:
    return _progress_callback.set(callback)


def get_progress_callback() -> ProgressCallback | None:
    return _progress_callback.get()


def reset_progress_callback(token: Token) -> None:
    _progress_callback.reset(token)


def set_retrieval_stage_key(stage_key: str | None) -> Token:
    return _retrieval_stage_key.set(stage_key)


def get_retrieval_stage_key() -> str | None:
    return _retrieval_stage_key.get()


def reset_retrieval_stage_key(token: Token) -> None:
    _retrieval_stage_key.reset(token)


def emit_progress(event_type: str, **payload: Any) -> None:
    callback = _progress_callback.get()
    if callback is None:
        return
    event = {
        "type": event_type,
        "emitted_at": datetime.now(UTC).isoformat(),
        **payload,
    }
    callback(event)


def emit_stage(
    *,
    stage_key: str,
    title: str,
    status: str,
    summary: str,
    details: list[str] | None = None,
) -> None:
    timestamp = datetime.now(UTC).isoformat()
    collector = _stage_timing_collector.get()
    if collector is not None:
        collector.record(stage_key=stage_key, status=status, timestamp=timestamp)
    emit_progress(
        "stage",
        stage_key=stage_key,
        title=title,
        status=status,
        summary=summary,
        details=details or [],
    )


def emit_api_call(
    *,
    call_type: str,
    status: str,
    title: str,
    summary: str,
    details: list[str] | None = None,
    stage_key: str | None = None,
) -> None:
    emit_progress(
        "api_call",
        call_type=call_type,
        status=status,
        title=title,
        summary=summary,
        details=details or [],
        stage_key=stage_key,
    )


def emit_retrieval(
    *,
    stage_key: str,
    query_label: str,
    query: str,
    provider_name: str,
    summary: str,
    details: list[str] | None = None,
    results: list[dict[str, Any]] | None = None,
) -> None:
    emit_progress(
        "retrieval",
        stage_key=stage_key,
        query_label=query_label,
        query=query,
        provider_name=provider_name,
        summary=summary,
        details=details or [],
        results=results or [],
    )


def emit_log(
    *,
    title: str,
    summary: str,
    details: list[str] | None = None,
    level: str = "info",
    stage_key: str | None = None,
) -> None:
    emit_progress(
        "log",
        title=title,
        summary=summary,
        details=details or [],
        level=level,
        stage_key=stage_key,
    )
