"""Structured trace export — OpenTelemetry-style spans for offline replay.

Records each agent step as a span with start/end timestamps, action, outcome,
and token usage. Supports JSON export for debugging and performance analysis.
"""
from __future__ import annotations

import itertools
import json
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TraceSpan:
    """One recorded span in the agent execution trace.

    span_id/parent_span_id form a parent-child tree so a supervisor's child agents
    hang under it in the exported trace, and cost/duration can be aggregated by
    subtree instead of just by flat sum.
    """

    action: str
    start_time: float
    span_id: str = ""
    parent_span_id: str | None = None
    end_time: float = 0.0
    success: bool = False
    error_type: str | None = None
    error_message: str | None = None
    token_usage: dict[str, int] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        return (self.end_time - self.start_time) * 1000

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "action": self.action,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": round(self.duration_ms, 2),
            "success": self.success,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "token_usage": self.token_usage,
            "metadata": self.metadata,
        }


@dataclass
class TraceRecord:
    """Complete execution trace for one agent run."""

    run_id: str
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0
    spans: list[TraceSpan] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        return (self.end_time - self.start_time) * 1000 if self.end_time > 0 else 0.0

    @property
    def total_tokens(self) -> int:
        return sum(s.token_usage.get("total", 0) for s in self.spans)

    @property
    def success_count(self) -> int:
        return sum(1 for s in self.spans if s.success)

    @property
    def failure_count(self) -> int:
        return sum(1 for s in self.spans if not s.success)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": round(self.duration_ms, 2),
            "total_tokens": self.total_tokens,
            "span_count": len(self.spans),
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "spans": [s.to_dict() for s in self.spans],
            "metadata": self.metadata,
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


class TraceExporter:
    """Collects spans during a run and exports the complete trace.

    Integrates with the runner via the hook system — register as a pre/post hook.
    Spans nest via an internal stack: `begin_span` pushes, `end_span` pops. Each
    span's parent is whatever was on top of the stack when it started, so a
    supervisor span wraps its child-agent spans without callers having to thread
    parent ids manually.

    For concurrent code (thread pool workers), pass `parent=` to `begin_span` /
    `span` explicitly — worker threads share the exporter but must not push onto
    the main stack, since parallel pushes would interleave and corrupt parent
    relationships. `record_child_span` is the lock-safe form: it records a
    completed span directly under a specified parent without touching the stack.
    """

    def __init__(self, run_id: str, metadata: dict[str, Any] | None = None):
        self._record = TraceRecord(run_id=run_id, metadata=metadata or {})
        self._active_stack: list[TraceSpan] = []
        self._id_counter = itertools.count(1)
        self._lock = threading.Lock()

    @property
    def record(self) -> TraceRecord:
        return self._record

    def _next_span_id(self) -> str:
        return f"span_{next(self._id_counter):04d}"

    def begin_span(self, action: str, *, parent: TraceSpan | None = None, **metadata: Any) -> TraceSpan:
        """Start a new span for the given action. Nests under the currently-active
        span (if any) so parent-child structure is captured automatically. Pass
        `parent=` to override the stack — required in concurrent workers so
        threads don't fight over the shared stack top."""
        parent_span = parent if parent is not None else (self._active_stack[-1] if self._active_stack else None)
        span = TraceSpan(
            action=action,
            start_time=time.time(),
            span_id=self._next_span_id(),
            parent_span_id=parent_span.span_id if parent_span else None,
            metadata=metadata,
        )
        # Only push onto the stack when we didn't get an explicit parent — the
        # explicit-parent case is for concurrent workers that must not touch it.
        if parent is None:
            self._active_stack.append(span)
        return span

    def record_child_span(
        self,
        action: str,
        *,
        parent: TraceSpan,
        start_time: float,
        end_time: float,
        success: bool,
        error_type: str | None = None,
        error_message: str | None = None,
        token_usage: dict[str, int] | None = None,
        **metadata: Any,
    ) -> TraceSpan:
        """Record a completed child span under `parent` without touching the
        active stack. Safe to call from worker threads: only the span record and
        id counter are shared, both guarded by the lock."""
        with self._lock:
            span = TraceSpan(
                action=action,
                start_time=start_time,
                end_time=end_time,
                span_id=self._next_span_id(),
                parent_span_id=parent.span_id,
                success=success,
                error_type=error_type,
                error_message=error_message,
                token_usage=token_usage or {},
                metadata=metadata,
            )
            self._record.spans.append(span)
        return span

    def end_span(
        self,
        *,
        success: bool,
        error_type: str | None = None,
        error_message: str | None = None,
        token_usage: dict[str, int] | None = None,
    ) -> None:
        """Complete the top active span and add it to the trace."""
        with self._lock:
            if not self._active_stack:
                return
            span = self._active_stack.pop()
            span.end_time = time.time()
            span.success = success
            span.error_type = error_type
            span.error_message = error_message
            if token_usage:
                span.token_usage = token_usage
            self._record.spans.append(span)

    @contextmanager
    def span(self, action: str, **metadata: Any):
        """Context-manager form of begin/end. Records success on clean exit,
        failure with error_type=exception class on unhandled exception."""
        span_obj = self.begin_span(action, **metadata)
        try:
            yield span_obj
        except Exception as exc:
            self.end_span(
                success=False,
                error_type=exc.__class__.__name__,
                error_message=str(exc)[:200],
            )
            raise
        else:
            self.end_span(success=True)

    def finalize(self) -> TraceRecord:
        """Mark the trace as complete and return it."""
        self._record.end_time = time.time()
        return self._record

    def export_to_file(self, path: Path) -> None:
        """Write the trace to a JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._record.to_json(), encoding="utf-8")

    # --- Hook integration ---

    def pre_hook(self, hook_ctx: Any) -> None:
        """Pre-dispatch hook: starts a span."""
        self.begin_span(hook_ctx.action)

    def post_hook(self, hook_ctx: Any) -> None:
        """Post-dispatch hook: completes the span."""
        outcome = hook_ctx.outcome
        if outcome is None:
            self.end_span(success=False, error_type="no_outcome")
            return
        token_info = {}
        state = hook_ctx.state
        if hasattr(state, "token_usage"):
            token_info = {
                "prompt": state.token_usage.prompt_tokens,
                "completion": state.token_usage.completion_tokens,
                "total": state.token_usage.total_tokens,
            }
        self.end_span(
            success=outcome.success,
            error_type=outcome.error_type,
            error_message=outcome.error_message,
            token_usage=token_info,
        )
