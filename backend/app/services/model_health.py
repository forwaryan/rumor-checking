"""In-memory health tracking for LLM models behind the gateway.

Ported from HappyClaw's provider-pool reliability model (riba2534/happyclaw):
a per-model state machine that evicts a model after N consecutive failures and
auto-restores it after a time window, so a model that is timing out or returning
empties stops being retried until it has had a chance to recover. Adapted to our
setup: one gateway, several model names (``LLM_MODELS``), no external health pings.

Why this exists: the retry loop in ``agent_reasoner`` and the bare LLM calls in
the verdict/correction path all hammered a single model even when it was reliably
timing out on this gateway (observed with the heavy synthesis prompt). Tracking
health lets callers fail over to the next healthy model instead of exhausting
retries on a known-bad one and dropping to the rule fallback.

State is process-local and thread-safe (``llm_verdict`` judges claims from a
``ThreadPoolExecutor``). It is intentionally NOT persisted — a fresh process
starts with every model healthy, which is the correct default.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx

from backend.app.services.progress import emit_log

if TYPE_CHECKING:
    from backend.app.core.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class _ModelState:
    consecutive_errors: int = 0
    unhealthy_since: float | None = None
    total_failures: int = 0
    total_evictions: int = 0
    total_successes: int = 0


@dataclass
class ModelHealthRegistry:
    """Thread-safe consecutive-failure / time-window health tracker.

    A model is evicted (``healthy`` -> False) once it reaches
    ``failure_threshold`` consecutive failures, and is automatically restored
    after ``recovery_seconds`` have elapsed since eviction. A single success
    restores health immediately. ``recovery_seconds <= 0`` means "never
    auto-recover on time alone" (only a success clears the eviction), which lets
    a deployment disable the time window via config.
    """

    failure_threshold: int = 3
    recovery_seconds: float = 300.0
    _states: dict[str, _ModelState] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _now(self) -> float:
        return time.monotonic()

    def _refresh_locked(self, model: str, state: _ModelState) -> None:
        """Restore a model whose recovery window has elapsed. Caller holds lock."""
        if state.unhealthy_since is None:
            return
        if self.recovery_seconds <= 0:
            return
        if self._now() - state.unhealthy_since >= self.recovery_seconds:
            state.consecutive_errors = 0
            state.unhealthy_since = None

    def is_healthy(self, model: str) -> bool:
        with self._lock:
            state = self._states.get(model)
            if state is None:
                return True
            self._refresh_locked(model, state)
            return state.unhealthy_since is None

    def report_success(self, model: str) -> None:
        with self._lock:
            state = self._states.get(model)
            if state is None:
                return
            state.consecutive_errors = 0
            state.unhealthy_since = None
            state.total_successes += 1

    def report_failure(self, model: str) -> None:
        with self._lock:
            state = self._states.setdefault(model, _ModelState())
            state.consecutive_errors += 1
            state.total_failures += 1
            if state.consecutive_errors >= self.failure_threshold and state.unhealthy_since is None:
                state.unhealthy_since = self._now()
                state.total_evictions += 1

    def order_by_health(self, models: Sequence[str]) -> list[str]:
        """Return ``models`` with healthy ones first, preserving input order
        within each group. Deduplicates while keeping first occurrence.

        Never returns an empty list when given a non-empty one: if every model is
        unhealthy, the original order is returned so the caller still has a
        best-effort candidate to try (mirrors HappyClaw's last-resort fallback).
        """
        seen: set[str] = set()
        healthy: list[str] = []
        unhealthy: list[str] = []
        for model in models:
            if not model or model in seen:
                continue
            seen.add(model)
            (healthy if self.is_healthy(model) else unhealthy).append(model)
        return healthy + unhealthy

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Return a copy of every seen model's health counters. Ops-facing:
        a model never touched is absent (fresh models start healthy by default,
        so the empty state is the correct default). Values are plain dicts so
        callers can json-serialize the result without touching internals."""
        with self._lock:
            out: dict[str, dict[str, Any]] = {}
            for name, state in self._states.items():
                out[name] = {
                    "healthy": state.unhealthy_since is None,
                    "consecutive_errors": state.consecutive_errors,
                    "total_failures": state.total_failures,
                    "total_successes": state.total_successes,
                    "total_evictions": state.total_evictions,
                }
            return out


def diff_snapshot(
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
) -> dict[str, dict[str, int]]:
    """Return per-model failure/success/eviction deltas between two snapshots.

    Used to attribute failover activity to a single analysis run: the registry
    is process-wide and never resets, so a raw snapshot mixes activity from
    every earlier request. Only models with a positive delta on any counter
    appear in the result — no-op models are omitted to keep the summary compact.
    """
    diffs: dict[str, dict[str, int]] = {}
    for name in set(before) | set(after):
        b = before.get(name) or {}
        a = after.get(name) or {}
        failures = int(a.get("total_failures", 0)) - int(b.get("total_failures", 0))
        successes = int(a.get("total_successes", 0)) - int(b.get("total_successes", 0))
        evictions = int(a.get("total_evictions", 0)) - int(b.get("total_evictions", 0))
        if failures or successes or evictions:
            diffs[name] = {
                "failures": failures,
                "successes": successes,
                "evictions": evictions,
            }
    return diffs


_registry: ModelHealthRegistry | None = None
_registry_lock = threading.Lock()


def get_model_health_registry() -> ModelHealthRegistry:
    """Return the process-wide registry, configured from settings on first use."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                from backend.app.core.config import get_settings

                settings = get_settings()
                _registry = ModelHealthRegistry(
                    failure_threshold=settings.model_health_failure_threshold,
                    recovery_seconds=settings.model_health_recovery_seconds,
                )
    return _registry


def _fast_model_candidates(settings: Settings) -> list[str]:
    """Health-ordered non-reasoning models for a one-shot completion.

    The bare LLM calls (verdict/correction) want a fast model: reasoning models
    burn their token budget on chain-of-thought before emitting any answer, which
    read-times-out under a short timeout. We take every non-reasoning model in the
    whitelist, then let the health registry push known-bad ones to the back. If the
    whitelist declares none (only reasoning models configured, or an empty list),
    fall back to the default model so the caller still has one candidate to try."""
    fast = [m for m in settings.available_models if not settings.is_reasoning_model(m)]
    if not fast and settings.llm_model:
        fast = [settings.llm_model]
    return get_model_health_registry().order_by_health(fast)


def complete_once(
    system_prompt: str,
    user_prompt: str,
    *,
    settings: Settings,
    temperature: float,
    max_tokens: int,
    timeout: float,
    include_reasoning: bool = False,
    stage_key: str | None = None,
) -> str:
    """One-shot chat completion with health-aware model failover.

    Shared transport for the non-agent LLM call sites (verdict judging, per-claim
    correction, evidence-based correction) that previously each held their own bare
    ``httpx.post`` against a single hardcoded fast model. Tries fast models in
    health order, reporting success/failure to the shared registry so a model that
    is timing out on this gateway gets evicted and the next one is used instead
    (mirrors the agent reasoner's failover on the streaming path).

    Returns the response ``content`` (stripped), or ``""`` when every candidate
    fails — callers already treat an empty string as "degrade to no-op / rule
    fallback". ``include_reasoning`` also accepts a reasoning model's last CoT
    line when ``content`` is blank (only ``content_check_builder`` needs this).

    When ``stage_key`` is supplied, every candidate switch after the first emits
    a "切换备用模型" progress event under that stage — parity with the agent
    reasoner's failover, so non-agent failovers are also visible in the trace UI.
    """
    candidates = _fast_model_candidates(settings)
    if not candidates or not settings.llm_api_key:
        return ""
    registry = get_model_health_registry()

    prev_model: str | None = None
    for model in candidates:
        if stage_key and prev_model is not None and model != prev_model:
            emit_log(
                stage_key=stage_key,
                title="切换备用模型",
                summary=f"上一个模型未返回可用结果，改用备用模型 {model}。",
                details=[f"model={model}"],
            )
        prev_model = model
        base_url = settings.base_url_for_model(model)
        try:
            resp = httpx.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json={
                    "model": model,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                },
                timeout=timeout,
            )
            if resp.status_code != 200:
                logger.debug("complete_once got HTTP %d on %s", resp.status_code, model)
                registry.report_failure(model)
                continue
            message = resp.json()["choices"][0]["message"]
            content = (message.get("content") or "").strip()
            if not content and include_reasoning:
                reasoning = (message.get("reasoning_content") or "").strip()
                if reasoning:
                    content = reasoning.rsplit("\n", 1)[-1].strip()
        except Exception as exc:
            # Transport error OR a malformed 200 body — either way this model did
            # not usefully answer, so evict it and fail over to the next candidate.
            logger.debug("complete_once failed on %s: %s", model, exc)
            registry.report_failure(model)
            continue

        if content:
            registry.report_success(model)
            return content
        # A 200 with empty content is a model failure on this gateway, not a
        # transport error — evict it and fail over just like a timeout.
        registry.report_failure(model)

    return ""
