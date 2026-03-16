from __future__ import annotations

from contextvars import ContextVar, Token
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

ProgressCallback = Callable[[Dict[str, Any]], None]

_progress_callback: ContextVar[Optional[ProgressCallback]] = ContextVar("progress_callback", default=None)


def set_progress_callback(callback: ProgressCallback) -> Token:
    return _progress_callback.set(callback)


def reset_progress_callback(token: Token) -> None:
    _progress_callback.reset(token)


def emit_progress(event_type: str, **payload: Any) -> None:
    callback = _progress_callback.get()
    if callback is None:
        return
    event = {
        "type": event_type,
        "emitted_at": datetime.now(timezone.utc).isoformat(),
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
) -> None:
    emit_progress(
        "retrieval",
        stage_key=stage_key,
        query_label=query_label,
        query=query,
        provider_name=provider_name,
        summary=summary,
        details=details or [],
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
