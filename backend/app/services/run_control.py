from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass, field

from backend.app.agent.context_window import estimate_tokens

logger = logging.getLogger(__name__)


class RunStopped(BaseException):
    """Cooperative control flow that must not trigger error retries or fallbacks."""

    def __init__(self, reason: str = "user_cancelled") -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class RunControl:
    cancelled: Callable[[], bool] = lambda: False
    max_llm_calls: int = 0
    max_tokens: int = 0
    deadline: float | None = None
    reserve_callback: Callable[[int], None] | None = None
    stop_callback: Callable[[str], None] | None = None
    clock: Callable[[], float] = time.monotonic
    llm_calls: int = 0
    reserved_tokens: int = 0
    _reason: str | None = field(default=None, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def check(self) -> None:
        with self._lock:
            reason = self._reason
        if reason:
            raise RunStopped(reason)
        try:
            cancelled = self.cancelled()
        except Exception as exc:
            raise RunStopped("control_unavailable") from exc
        if cancelled:
            self.stop("user_cancelled")
        if self.deadline is not None and self.clock() >= self.deadline:
            self.stop("deadline_exceeded")

    def stop(self, reason: str) -> None:
        with self._lock:
            first_stop = self._reason is None
            self._reason = self._reason or reason
            reason = self._reason
        if first_stop and self.stop_callback is not None:
            try:
                self.stop_callback(reason)
            except Exception as exc:
                logger.warning("run_stop_notification_failed error_type=%s", type(exc).__name__)
        raise RunStopped(reason)

    def reserve(self, estimated_tokens: int) -> None:
        self.check()
        amount = max(0, int(estimated_tokens))
        try:
            with self._lock:
                if self._reason:
                    raise RunStopped(self._reason)
                if self.max_llm_calls > 0 and self.llm_calls >= self.max_llm_calls:
                    raise RunStopped("call_budget_exhausted")
                if self.max_tokens > 0 and self.reserved_tokens + amount > self.max_tokens:
                    raise RunStopped("token_budget_exhausted")
                if self.reserve_callback is not None:
                    self.reserve_callback(amount)
                self.llm_calls += 1
                self.reserved_tokens += amount
        except RunStopped as exc:
            self.stop(exc.reason)


_run_control: ContextVar[RunControl | None] = ContextVar("analysis_run_control", default=None)


def set_run_control(control: RunControl | None) -> Token:
    return _run_control.set(control)


def reset_run_control(token: Token) -> None:
    _run_control.reset(token)


def get_run_control() -> RunControl | None:
    control = _run_control.get()
    if control is not None:
        return control
    from backend.app.services.progress import get_progress_callback

    callback = get_progress_callback()
    inherited = getattr(callback, "run_control", None)
    return inherited if isinstance(inherited, RunControl) else None


def check_run_control() -> None:
    control = get_run_control()
    if control is not None:
        control.check()


def reserve_llm_call(*, system_prompt: str, user_prompt: str, max_output_tokens: int) -> None:
    """Reserve conservative estimated input plus maximum output, not billed usage."""
    control = get_run_control()
    if control is not None:
        control.reserve(estimate_tokens(system_prompt) + estimate_tokens(user_prompt) + max(0, max_output_tokens) + 16)
