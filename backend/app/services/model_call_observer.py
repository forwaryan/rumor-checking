"""Per-request model diagnostics, inspired by claude-tap's request/usage viewer.

Only counts and fixed labels leave this module. Request fingerprints are keyed,
run-local, and never exported; prompts, responses, headers and URLs are not saved.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from backend.app.agent.trace import get_current_parent, get_current_trace
from backend.app.services.model_ledger import record_call

logger = logging.getLogger(__name__)
_REQUEST_FIELDS = (
    "messages", "tools", "model", "temperature", "max_tokens",
    "response_format", "stream", "stream_options",
)


@dataclass
class _RunObservations:
    run_id: str
    key: bytes = field(default_factory=lambda: secrets.token_bytes(32))
    previous: dict[tuple, dict[str, bytes]] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)


_run: ContextVar[_RunObservations | None] = ContextVar("model_observation_run", default=None)
_attempt: ContextVar[tuple[str | None, int]] = ContextVar("model_observation_attempt", default=(None, 1))


@contextmanager
def model_observation_run(run_id: str):
    token = _run.set(_RunObservations(run_id))
    try:
        yield
    finally:
        _run.reset(token)


@contextmanager
def model_call_attempt(stage_key: str | None, attempt: int):
    token = _attempt.set((stage_key, attempt))
    try:
        yield
    finally:
        _attempt.reset(token)


def _count(value: Any) -> int | None:
    # Reject booleans, negative values, NaN, strings, and malformed gateway data.
    return value if type(value) is int and value >= 0 else None


def normalize_usage(usage: Any) -> dict[str, int]:
    """Preserve reported zero versus missing; cached input is a subset of prompt."""
    if not isinstance(usage, dict):
        return {}
    result: dict[str, int] = {}
    for target, aliases in {
        "prompt": ("prompt_tokens", "input_tokens"),
        "completion": ("completion_tokens", "output_tokens"),
        "total": ("total_tokens",),
        "cache_read": ("cached_tokens", "prompt_cache_hit_tokens", "cache_read_input_tokens"),
    }.items():
        for alias in aliases:
            value = _count(usage.get(alias))
            if value is not None:
                result[target] = value
                break
    for key in ("prompt_tokens_details", "input_tokens_details"):
        details = usage.get(key)
        if isinstance(details, dict) and (value := _count(details.get("cached_tokens"))) is not None:
            result["cache_read"] = value
            break
    if "total" not in result and "prompt" in result and "completion" in result:
        result["total"] = result["prompt"] + result["completion"]
    return result


def _text_chars(value: Any) -> int:
    if isinstance(value, str):
        return len(value)
    if isinstance(value, list):
        return sum(len(part["text"]) for part in value if isinstance(part, dict) and isinstance(part.get("text"), str))
    return 0


def _context_summary(request: dict, *, scope: tuple) -> dict[str, Any]:
    messages = request.get("messages")
    messages = messages if isinstance(messages, list) else []
    tools = request.get("tools")
    summary: dict[str, Any] = {
        "message_count": len(messages), "tool_count": len(tools) if isinstance(tools, list) else 0,
        "system_chars": 0, "user_chars": 0, "assistant_chars": 0, "tool_chars": 0,
        "request_bytes": len(json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")),
        "changed": None, "changed_fields": [],
    }
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        role = "system" if role == "developer" else role
        if role in {"system", "user", "assistant", "tool"}:
            summary[f"{role}_chars"] += _text_chars(message.get("content"))
    run = _run.get()
    if run is not None:
        fingerprints = {
            key: hmac.digest(run.key, json.dumps(request[key], ensure_ascii=False, sort_keys=True).encode(), hashlib.sha256)
            for key in _REQUEST_FIELDS if key in request
        }
        with run.lock:
            previous = run.previous.get(scope)
            run.previous[scope] = fingerprints
        if previous is not None:
            changes = [key for key in _REQUEST_FIELDS if previous.get(key) != fingerprints.get(key)]
            summary.update(changed=bool(changes), changed_fields=changes)
    return summary


class ModelCallObservation:
    """One HTTP attempt; all diagnostics are best effort and never suppress errors."""

    def __init__(self, *, settings: Any, provider: str, model: str, stage_key: str | None, request: dict):
        self.settings = settings
        self.provider = provider
        self.model = model
        inherited_stage, self.attempt = _attempt.get()
        self.stage_key = stage_key or inherited_stage
        self.call_id = uuid4().hex
        self.exporter = get_current_trace()
        self.parent = get_current_parent()
        run = _run.get()
        self.run_id = run.run_id if run else (self.exporter.record.run_id if self.exporter else None)
        self.enabled = self.exporter is not None or bool(getattr(settings, "model_ledger_enabled", False))
        self.start_time = time.time()
        self.start_clock = time.monotonic()
        self.usage: dict[str, int] = {}
        self.status_code: int | None = None
        self.status: str | None = None
        self.error_class: str | None = None
        self.response_chars = 0
        self.reasoning_chars = 0
        self.tool_call_count = 0
        self._tool_ids: set[tuple[int, int]] = set()
        self.first_token_ms: float | None = None
        self.context_estimate: dict | None = None
        self.context: dict[str, Any] = {}
        if self.enabled:
            try:
                self.context = _context_summary(request, scope=(
                    self.parent.span_id if self.parent else None, provider, self.stage_key, threading.get_ident(),
                ))
            except Exception:
                logger.debug("model_request_summary_failed")

    def __enter__(self):
        return self

    def _merge_usage(self, raw: Any) -> None:
        incoming = normalize_usage(raw)
        if not incoming:
            return
        explicit_total = _count(raw.get("total_tokens"))
        if explicit_total is None:
            incoming.pop("total", None)
        self.usage.update(incoming)
        # A later cumulative completion count invalidates an earlier derived
        # total. Preserve an explicit total supplied with this update instead.
        if explicit_total is None and {"prompt", "completion"}.intersection(incoming):
            if "prompt" in self.usage and "completion" in self.usage:
                self.usage["total"] = self.usage["prompt"] + self.usage["completion"]

    def response(self, payload: Any, *, status_code: int | None = None) -> None:
        """Observe one non-streamed response without retaining its body."""
        try:
            self.status_code = status_code
            if not isinstance(payload, dict):
                return
            choices = payload.get("choices")
            choices = choices if isinstance(choices, list) else []
            self._merge_usage(payload.get("usage"))
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                if not self.usage:
                    self._merge_usage(choice.get("usage"))
                message = choice.get("message")
                if isinstance(message, dict):
                    self.response_chars += _text_chars(message.get("content"))
                    self.reasoning_chars += _text_chars(message.get("reasoning_content"))
                    calls = message.get("tool_calls")
                    self.tool_call_count += len(calls) if isinstance(calls, list) else 0
        except Exception:
            logger.debug("model_response_summary_failed")

    def chunk(self, payload: Any) -> None:
        """Observe SSE deltas, including usage-only terminal frames and tool deltas."""
        try:
            if not isinstance(payload, dict):
                return
            self._merge_usage(payload.get("usage"))
            choices = payload.get("choices")
            for position, choice in enumerate(choices if isinstance(choices, list) else []):
                if not isinstance(choice, dict):
                    continue
                self._merge_usage(choice.get("usage"))
                if choice.get("finish_reason") == "length":
                    self.status = "truncated"
                delta = choice.get("delta")
                if not isinstance(delta, dict):
                    continue
                content_chars = _text_chars(delta.get("content"))
                reasoning_chars = _text_chars(delta.get("reasoning_content"))
                self.response_chars += content_chars
                self.reasoning_chars += reasoning_chars
                calls = delta.get("tool_calls")
                if isinstance(calls, list):
                    for index, call in enumerate(calls):
                        if isinstance(call, dict):
                            self._tool_ids.add((choice.get("index", position), call.get("index", index)))
                    self.tool_call_count = len(self._tool_ids)
                if self.first_token_ms is None and (content_chars or reasoning_chars or calls):
                    self.first_token_ms = round((time.monotonic() - self.start_clock) * 1000, 2)
        except Exception:
            logger.debug("model_stream_summary_failed")

    def fail(self, exc: BaseException, *, truncated: bool = False) -> None:
        self.status = "truncated" if truncated else "error"
        self.error_class = type(exc).__name__
        response = getattr(exc, "response", None)
        code = getattr(response, "status_code", None)
        if type(code) is int:
            self.status_code = code

    def __exit__(self, exc_type, exc, traceback):
        if exc is not None:
            self.fail(exc)
        try:
            self._finish()
        except Exception:
            logger.debug("model_observation_export_failed")
        return False

    def _finish(self) -> None:
        if not self.enabled:
            return
        status = self.status or ("ok" if self.response_chars or self.tool_call_count else "empty")
        metadata: dict[str, Any] = {
            "span_kind": "LLM", "provider": self.provider, "model": self.model,
            "call_id": self.call_id, "stage_key": self.stage_key, "attempt": self.attempt,
            "status": status, "usage_reported": bool(self.usage),
            "response_chars": self.response_chars, "reasoning_chars": self.reasoning_chars,
            "tool_call_count": self.tool_call_count, "context": self.context,
        }
        if self.first_token_ms is not None:
            metadata["first_token_ms"] = self.first_token_ms
        if self.status_code is not None:
            metadata["status_code"] = self.status_code
        # Each sink is isolated: a broken trace must not prevent ledger export.
        if self.exporter is not None:
            try:
                self.exporter.record_child_span(
                    "llm.chat_completion", parent=self.parent, start_time=self.start_time,
                    end_time=time.time(), success=status == "ok", error_type=self.error_class,
                    token_usage=dict(self.usage), **metadata,
                )
            except Exception:
                logger.debug("model_trace_append_failed")
        record_call(
            provider=self.provider, model=self.model, input_tokens=self.usage.get("prompt", 0),
            output_tokens=self.usage.get("completion", 0), cache_tokens=self.usage.get("cache_read", 0),
            latency_ms=max(0, int((time.monotonic() - self.start_clock) * 1000)),
            status=status, error_class=self.error_class, trace_id=self.run_id,
            stage_key=self.stage_key, settings=self.settings, context_estimate=self.context_estimate,
            call_id=self.call_id, parent_span_id=self.parent.span_id if self.parent else None,
            attempt=self.attempt, usage_reported=bool(self.usage), total_tokens=self.usage.get("total"),
        )


def observe_model_call(*, settings: Any, provider: str, model: str, request: dict,
                       stage_key: str | None = None) -> ModelCallObservation:
    return ModelCallObservation(settings=settings, provider=provider, model=model, stage_key=stage_key, request=request)
