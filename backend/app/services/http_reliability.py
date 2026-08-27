"""Reliable HTTP GET for the evidence-fetch chain (borrows Scrapling's reliability
posture — NOT its anti-bot machinery).

The fetch chain was a bare ``httpx.get``: one attempt, one timeout, a fresh
connection each call. A single transient blip — a read timeout, a dropped
connection, a momentary 502 from an overloaded news host — silently lost that
piece of evidence. This adds bounded retry with exponential backoff around the
existing request so transient failures recover instead of dropping evidence.

Explicit scope boundary (the goal's compliance line): we borrow only the
*reliability* design. We DO NOT rotate identities, spoof fingerprints, solve
challenges, or otherwise try to defeat anti-scraping. Concretely:

  * Retry ONLY transient faults: connect/read timeouts, connection errors, and
    5xx server errors. A 4xx (401/403/404/429) is a definitive answer from the
    server — retrying it wastes time and, for 403/429, would read as hammering a
    host that is asking us to stop. We surface it immediately instead.
  * A hard cap on attempts and a capped backoff, so a flaky host can never turn
    into an unbounded retry storm.

Session isolation: each call uses its own short-lived client (context-managed),
so a poisoned connection or a per-host cookie from one fetch never leaks into the
next. This is the conservative default; connection *reuse* is a separate,
independently-measurable optimization we are deliberately not bundling here.
"""
from __future__ import annotations

import logging
import time

import httpx

logger = logging.getLogger(__name__)

# Transient transport faults worth retrying. NOTE: httpx.HTTPStatusError is NOT
# here — status decisions are made by the caller after inspecting the code, so we
# only retry 5xx explicitly below.
_TRANSIENT_EXC = (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError)

# Backoff is capped so worst-case added latency stays bounded even at high
# retry counts.
_MAX_BACKOFF_SECONDS = 4.0


def _backoff_seconds(attempt: int) -> float:
    """Exponential backoff: 0.5s, 1s, 2s, ... capped. attempt is 1-indexed."""
    return min(0.5 * (2 ** (attempt - 1)), _MAX_BACKOFF_SECONDS)


def reliable_get(
    url: str,
    *,
    headers: dict[str, str],
    timeout: float,
    max_retries: int,
    follow_redirects: bool = True,
    sleep=time.sleep,
) -> httpx.Response:
    """GET with bounded retry + backoff on transient faults only.

    Retries connect/read timeouts, connection errors, and 5xx responses up to
    ``max_retries`` extra attempts. Returns the response as soon as it is not a
    5xx (the caller decides what a 2xx/3xx/4xx means). Raises the last transient
    exception if every attempt failed at the transport layer.

    A 4xx is returned immediately, never retried. ``sleep`` is injectable so tests
    do not actually wait."""
    attempts = max(max_retries, 0) + 1
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            # Own client per call => session isolation: no cross-request cookie or
            # connection bleed. Context-managed so it always closes.
            with httpx.Client(follow_redirects=follow_redirects) as client:
                response = client.get(url, headers=headers, timeout=timeout)
            if response.status_code >= 500 and attempt < attempts:
                logger.debug(
                    "reliable_get_5xx url=%s status=%s attempt=%s/%s",
                    url, response.status_code, attempt, attempts,
                )
                sleep(_backoff_seconds(attempt))
                continue
            return response
        except _TRANSIENT_EXC as exc:
            last_exc = exc
            if attempt < attempts:
                logger.debug(
                    "reliable_get_transient url=%s error=%s attempt=%s/%s",
                    url, type(exc).__name__, attempt, attempts,
                )
                sleep(_backoff_seconds(attempt))
                continue
            raise
    # Only reachable if the loop exhausted on repeated 5xx (no exception path).
    if last_exc is not None:  # pragma: no cover - defensive
        raise last_exc
    return response
