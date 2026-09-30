"""Reliable HTTP GET for the evidence-fetch chain (borrows Scrapling's reliability
posture — NOT its anti-bot machinery).

The fetch chain was a bare ``httpx.get``: one attempt, one timeout, a fresh
connection each call. A single transient blip — a read timeout, a dropped
connection, a momentary 502 from an overloaded news host — silently lost that
piece of evidence. This adds bounded retry with exponential backoff around the
existing request so transient failures recover instead of dropping evidence.

Public evidence requests validate and pin every redirect destination, retain
Host/TLS identity, ignore environment proxies and reject encoded/oversized bodies.
We do not rotate identities, solve challenges or defeat anti-scraping. Concretely:

  * Retry ONLY transient faults: connect/read timeouts, connection errors, and
    5xx server errors. A 4xx (401/403/404/429) is a definitive answer from the
    server — retrying it wastes time and, for 403/429, would read as hammering a
    host that is asking us to stop. We surface it immediately instead.
  * A hard cap on attempts and a capped backoff, so a flaky host can never turn
    into an unbounded retry storm.

Session isolation: each redirect hop uses its own short-lived client (context-managed),
so a poisoned connection or a per-host cookie from one fetch never leaks into the
next. This is the conservative default; connection *reuse* is a separate,
independently-measurable optimization we are deliberately not bundling here.
"""
from __future__ import annotations

import logging
import time
from urllib.parse import urljoin

import httpx

from backend.app.services.run_control import check_run_control
from backend.app.services.url_validator import resolve_public_ip

logger = logging.getLogger(__name__)

# Transient transport faults worth retrying. NOTE: httpx.HTTPStatusError is NOT
# here — status decisions are made by the caller after inspecting the code, so we
# only retry 5xx explicitly below.
_TRANSIENT_EXC = (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError)

# Backoff is capped so worst-case added latency stays bounded even at high
# retry counts.
_MAX_BACKOFF_SECONDS = 4.0
# Hard ceiling on retries regardless of configuration: one flaky host must never
# be able to hold an evidence fetch for a configurable number of backoff rounds.
MAX_RETRIES = 3
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


def _read_bounded(response: httpx.Response, limit: int, deadline: float) -> bytes:
    encoding = response.headers.get("content-encoding", "identity").strip().lower()
    if encoding not in {"", "identity"}:
        raise ValueError("encoded_public_response_rejected")
    content_length = response.headers.get("content-length")
    if content_length is not None and (not content_length.isdecimal() or int(content_length) > limit):
        raise ValueError("public_response_too_large")
    chunks = [response.content] if response.is_stream_consumed else response.iter_raw()
    body = bytearray()
    for chunk in chunks:
        check_run_control()
        if time.monotonic() >= deadline:
            raise httpx.ReadTimeout("public_response_deadline", request=response.request)
        if len(body) + len(chunk) > limit:
            raise ValueError("public_response_too_large")
        body.extend(chunk)
    return bytes(body)


def _public_get(url: str, *, headers: dict[str, str], timeout: float, follow_redirects: bool,
                max_response_bytes: int) -> httpx.Response:
    for hop in range(6):
        check_run_control()
        address = resolve_public_ip(url)
        logical_url = httpx.URL(url)
        hostname = logical_url.raw_host.decode("ascii")
        safe_headers = {name: value for name, value in headers.items()
                        if name.lower() in {"accept", "accept-language", "user-agent"}}
        safe_headers.update({"Host": logical_url.netloc.decode("ascii"), "Accept-Encoding": "identity"})
        deadline = time.monotonic() + timeout
        with httpx.Client(trust_env=False, follow_redirects=False, verify=True, timeout=timeout) as client:
            request = client.build_request("GET", logical_url.copy_with(host=address), headers=safe_headers,
                                           extensions={"sni_hostname": hostname})
            response = client.send(request, stream=True)
            try:
                if follow_redirects and response.status_code in _REDIRECT_STATUSES:
                    location = response.headers.get("location")
                    if not location or hop == 5:
                        raise ValueError("invalid_public_redirect")
                    url = urljoin(str(logical_url), location)
                    continue
                body = _read_bounded(response, max_response_bytes, deadline)
                response_headers = {name: value for name, value in response.headers.items()
                                    if name.lower() not in {"content-encoding", "content-length", "transfer-encoding", "set-cookie", "connection"}}
                return httpx.Response(response.status_code, headers=response_headers, content=body,
                                      request=httpx.Request("GET", logical_url, headers=safe_headers))
            finally:
                response.close()
    raise ValueError("invalid_public_redirect")


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
    max_response_bytes: int = MAX_RESPONSE_BYTES,
    sleep=time.sleep,
) -> httpx.Response:
    """GET with bounded retry + backoff on transient faults only.

    Retries connect/read timeouts, connection errors, and 5xx responses up to
    ``max_retries`` extra attempts. Returns the response as soon as it is not a
    5xx (the caller decides what a 2xx/3xx/4xx means). Raises the last transient
    exception if every attempt failed at the transport layer.

    A 4xx is returned immediately, never retried. ``sleep`` is injectable so tests
    do not actually wait."""
    if not 0 < max_response_bytes <= MAX_RESPONSE_BYTES:
        raise ValueError("invalid_public_response_limit")
    requested_retries = max(max_retries, 0)
    if requested_retries > MAX_RETRIES:
        logger.warning("reliable_get_retries_clamped requested=%s applied=%s", requested_retries, MAX_RETRIES)
    attempts = min(requested_retries, MAX_RETRIES) + 1
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        check_run_control()
        try:
            response = _public_get(url, headers=headers, timeout=timeout, follow_redirects=follow_redirects,
                                   max_response_bytes=max_response_bytes)
            check_run_control()
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
