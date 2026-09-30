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
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_current_binding: ContextVar[tuple[TraceExporter, TraceSpan | None] | None] = ContextVar(
    "agent_trace_binding", default=None,
)
_INHERIT_PARENT = object()


def get_current_trace() -> TraceExporter | None:
    """Return the exporter bound to this request/task context."""
    binding = _current_binding.get()
    return binding[0] if binding else None


def get_current_parent() -> TraceSpan | None:
    """Return the parent for new request spans in this task context."""
    binding = _current_binding.get()
    return binding[1] if binding else None


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


@dataclass
class _SpanFrame:
    span: TraceSpan
    binding_token: Token
    stack_token: Token = field(init=False, repr=False)


@dataclass
class _UsageFrame:
    usage: dict[str, int]
    stack_token: Token = field(init=False, repr=False)


class TraceExporter:
    """Collects spans during a run and exports the complete trace.

    Integrates with the runner via the hook system — register as a pre/post hook.
    Active spans are local to each context. Use ``copy_context().run`` when
    submitting thread workers so they inherit their caller's parent. Completed
    span writes are guarded by a lock; independent requests never share a stack.
    """

    def __init__(self, run_id: str, metadata: dict[str, Any] | None = None):
        self._record = TraceRecord(run_id=run_id, metadata=metadata or {})
        self._frames: ContextVar[tuple[_SpanFrame, ...]] = ContextVar(
            f"trace_frames_{id(self)}", default=(),
        )
        self._hook_usage: ContextVar[tuple[_UsageFrame, ...]] = ContextVar(
            f"trace_hook_usage_{id(self)}", default=(),
        )
        self._id_counter = itertools.count(1)
        self._lock = threading.Lock()

    @property
    def record(self) -> TraceRecord:
        return self._record

    def _next_span_id(self) -> str:
        return f"span_{next(self._id_counter):04d}"

    def current_span(self) -> TraceSpan | None:
        """Return the active parent in the caller's context."""
        if get_current_trace() is self:
            return get_current_parent()
        frames = self._frames.get()
        return frames[-1].span if frames else None

    @property
    def _active_stack(self) -> list[TraceSpan]:
        """Compatibility snapshot for legacy callers; never a shared stack."""
        return [frame.span for frame in self._frames.get()]

    @contextmanager
    def activate(self, parent: TraceSpan | None | object = _INHERIT_PARENT):
        """Bind this exporter and a parent, restoring the prior binding on exit."""
        if parent is _INHERIT_PARENT:
            parent = self.current_span()
        token = _current_binding.set((self, parent))
        frames_token = self._frames.set(self._frames.get())
        usage_token = self._hook_usage.set(self._hook_usage.get())
        try:
            yield self
        finally:
            # Cancellation can interrupt a pre/post hook pair. Restore the
            # activation boundary even when an inner frame was never closed.
            self._hook_usage.reset(usage_token)
            self._frames.reset(frames_token)
            _current_binding.reset(token)

    def begin_span(self, action: str, **metadata: Any) -> TraceSpan:
        """Start a span under the current context's parent."""
        parent_span = self.current_span()
        with self._lock:
            span_id = self._next_span_id()
        span = TraceSpan(
            action=action,
            start_time=time.time(),
            span_id=span_id,
            parent_span_id=parent_span.span_id if parent_span else None,
            metadata=metadata,
        )
        binding_token = _current_binding.set((self, span))
        frame = _SpanFrame(span=span, binding_token=binding_token)
        frame.stack_token = self._frames.set((*self._frames.get(), frame))
        return span

    def record_child_span(
        self,
        action: str,
        *,
        parent: TraceSpan | None,
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
                parent_span_id=parent.span_id if parent else None,
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
        frames = self._frames.get()
        if not frames:
            return
        frame = frames[-1]
        span = frame.span
        # Reset, rather than setting an empty tuple: contexts hold strong
        # references to their variables, and each exporter owns distinct ones.
        self._frames.reset(frame.stack_token)
        _current_binding.reset(frame.binding_token)
        with self._lock:
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
        except BaseException as exc:
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
        frame = _UsageFrame(usage=self._state_usage(hook_ctx.state))
        frame.stack_token = self._hook_usage.set((*self._hook_usage.get(), frame))
        try:
            self.begin_span(hook_ctx.action)
        except BaseException:
            self._hook_usage.reset(frame.stack_token)
            raise

    @staticmethod
    def _state_usage(state: Any) -> dict[str, int]:
        usage = getattr(state, "token_usage", None)
        return {
            key: getattr(usage, attribute, 0)
            for key, attribute in (
                ("prompt", "prompt_tokens"),
                ("completion", "completion_tokens"),
                ("total", "total_tokens"),
            )
        }

    def _llm_descendant_usage(self, parent: TraceSpan | None) -> dict[str, int]:
        if parent is None:
            return {}
        with self._lock:
            spans = tuple(self._record.spans)
        by_id = {span.span_id: span for span in spans}
        totals: dict[str, int] = {}
        for span in spans:
            if span.metadata.get("span_kind") != "LLM":
                continue
            ancestor = span.parent_span_id
            seen: set[str] = set()
            while ancestor and ancestor not in seen:
                if ancestor == parent.span_id:
                    for key, value in span.token_usage.items():
                        totals[key] = totals.get(key, 0) + value
                    break
                seen.add(ancestor)
                ancestor_span = by_id.get(ancestor)
                ancestor = ancestor_span.parent_span_id if ancestor_span else None
        return totals

    def post_hook(self, hook_ctx: Any) -> None:
        """Post-dispatch hook: completes the span."""
        snapshots = self._hook_usage.get()
        before = snapshots[-1].usage if snapshots else {}
        if snapshots:
            self._hook_usage.reset(snapshots[-1].stack_token)
        outcome = hook_ctx.outcome
        if outcome is None:
            self.end_span(success=False, error_type="no_outcome")
            return
        observed = self._llm_descendant_usage(self.current_span())
        token_info = {
            key: max(0, value - before.get(key, 0) - observed.get(key, 0))
            for key, value in self._state_usage(hook_ctx.state).items()
        }
        self.end_span(
            success=outcome.success,
            error_type=outcome.error_type,
            error_message=outcome.error_message,
            token_usage=token_info,
        )
