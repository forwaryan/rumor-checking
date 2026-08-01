"""Structured trace export — OpenTelemetry-style spans for offline replay.

Records each agent step as a span with start/end timestamps, action, outcome,
and token usage. Supports JSON export for debugging and performance analysis.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TraceSpan:
    """One recorded span in the agent execution trace."""

    action: str
    start_time: float
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
    """

    def __init__(self, run_id: str, metadata: dict[str, Any] | None = None):
        self._record = TraceRecord(run_id=run_id, metadata=metadata or {})
        self._active_span: TraceSpan | None = None

    @property
    def record(self) -> TraceRecord:
        return self._record

    def begin_span(self, action: str, **metadata: Any) -> None:
        """Start a new span for the given action."""
        self._active_span = TraceSpan(
            action=action,
            start_time=time.time(),
            metadata=metadata,
        )

    def end_span(
        self,
        *,
        success: bool,
        error_type: str | None = None,
        error_message: str | None = None,
        token_usage: dict[str, int] | None = None,
    ) -> None:
        """Complete the active span and add it to the trace."""
        if self._active_span is None:
            return
        self._active_span.end_time = time.time()
        self._active_span.success = success
        self._active_span.error_type = error_type
        self._active_span.error_message = error_message
        if token_usage:
            self._active_span.token_usage = token_usage
        self._record.spans.append(self._active_span)
        self._active_span = None

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
