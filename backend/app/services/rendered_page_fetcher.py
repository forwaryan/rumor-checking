"""Rendered page fetcher: Playwright fallback for JS-rendered pages.

When the static httpx fetch returns partial/empty (client-rendered SPAs like
163.com), this module launches a headless browser, waits for content to render,
and returns the resulting HTML for the extractor to parse.

Playwright is an OPTIONAL dependency. If not installed, calling render_page()
gracefully returns None so the pipeline degrades to static-only without crashing.
HTTP is fulfilled through the public-IP-pinned transport. Redirects are rejected
because interception does not guarantee coverage of redirected requests. The
reserved non-listening proxy endpoint blocks browser transport fallthrough;
this and Chromium flags are defense in depth, not an OS network sandbox.
"""
from __future__ import annotations

import logging
import multiprocessing
import os
import selectors
import signal
import socket
import struct
from contextlib import suppress
from time import monotonic
from urllib.parse import urlsplit

from backend.app.services.http_reliability import MAX_RESPONSE_BYTES, reliable_get
from backend.app.services.run_control import check_run_control
from backend.app.services.url_validator import is_safe_url

logger = logging.getLogger(__name__)

_PLAYWRIGHT_AVAILABLE: bool | None = None
_MAX_REQUESTS = 32
_MAX_TOTAL_BYTES = 4 * 1024 * 1024
_MAX_HTML_BYTES = 2 * 1024 * 1024
_MAX_REASON_BYTES = 64
_IPC_HEADER = struct.Struct("!BBI")
_MAX_IPC_BYTES = 1 + _IPC_HEADER.size + _MAX_REASON_BYTES + _MAX_HTML_BYTES
_MAX_TIMEOUT_MS = 15000
_USER_AGENT = "Mozilla/5.0 (compatible; RumorCheck/1.0)"
_RESPONSE_HEADERS = frozenset({
    "content-type", "content-language", "cache-control", "expires", "last-modified", "etag",
    "content-security-policy", "x-content-type-options", "referrer-policy",
    "access-control-allow-origin", "access-control-allow-methods", "access-control-allow-headers",
    "access-control-expose-headers", "vary",
})


def _check_playwright() -> bool:
    global _PLAYWRIGHT_AVAILABLE
    if _PLAYWRIGHT_AVAILABLE is not None:
        return _PLAYWRIGHT_AVAILABLE
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        _PLAYWRIGHT_AVAILABLE = True
    except ImportError:
        _PLAYWRIGHT_AVAILABLE = False
        logger.info("rendered_page_fetcher_disabled reason=playwright_not_installed")
    return _PLAYWRIGHT_AVAILABLE


class _SafeBridge:
    def __init__(self, deadline: float):
        self.deadline = deadline
        self.requests = 0
        self.bytes = 0
        self.failure = ""

    def remaining_ms(self) -> int:
        remaining = int((self.deadline - monotonic()) * 1000)
        if remaining <= 0:
            self.failure = "deadline_exceeded"
            raise TimeoutError("render_deadline")
        return remaining

    def reject(self, route, reason: str) -> None:
        self.failure = self.failure or reason
        with suppress(Exception):
            route.abort("blockedbyclient")

    def websocket(self, connection) -> None:
        self.failure = self.failure or "blocked_websocket"
        connection.close(code=1008, reason="network_disabled")

    def route(self, route) -> None:
        if self.failure:
            self.reject(route, self.failure)
            return
        try:
            request = route.request
            if request.method != "GET" or urlsplit(request.url).scheme not in {"http", "https"}:
                self.reject(route, "blocked_request")
                return
            if self.requests >= _MAX_REQUESTS:
                self.reject(route, "request_limit")
                return
            remaining_bytes = _MAX_TOTAL_BYTES - self.bytes
            if remaining_bytes <= 0:
                self.reject(route, "byte_limit")
                return
            self.requests += 1
            response = reliable_get(
                request.url, headers={"User-Agent": _USER_AGENT, "Accept": "*/*", "Accept-Language": "zh-CN"},
                timeout=self.remaining_ms() / 1000, max_retries=0, follow_redirects=False,
                max_response_bytes=min(MAX_RESPONSE_BYTES, remaining_bytes),
            )
            self.remaining_ms()
            if 300 <= response.status_code < 400:
                self.reject(route, "redirect_not_supported")
                return
            body = response.content
            if len(body) > min(MAX_RESPONSE_BYTES, remaining_bytes):
                self.reject(route, "byte_limit")
                return
            self.bytes += len(body)
            headers = {name.lower(): value for name, value in response.headers.items()
                       if name.lower() in _RESPONSE_HEADERS and len(value) <= 8192}
            if sum(len(name) + len(value) for name, value in headers.items()) > 32768:
                self.reject(route, "header_limit")
                return
            route.fulfill(status=response.status_code, headers=headers, body=body)
        except Exception:
            self.reject(route, self.failure or "bridge_failed")


def _render_browser(url: str, *, timeout_ms: int, wait_until: str) -> tuple[str | None, str]:
    bridge = _SafeBridge(monotonic() + timeout_ms / 1000)
    if not is_safe_url(url):
        return None, "unsafe_url"

    try:
        from playwright.sync_api import sync_playwright

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as proxy, sync_playwright() as pw:
            proxy.bind(("127.0.0.1", 0))
            browser = pw.chromium.launch(
                headless=True, chromium_sandbox=True, timeout=bridge.remaining_ms(),
                proxy={"server": f"http://127.0.0.1:{proxy.getsockname()[1]}", "bypass": ""},
                args=["--proxy-bypass-list=<-loopback>", "--disable-quic", "--disable-background-networking",
                      "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                      "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"],
            )
            try:
                context = browser.new_context(
                    user_agent=_USER_AGENT, locale="zh-CN", service_workers="block", accept_downloads=False,
                )
                try:
                    if not callable(getattr(context, "route_web_socket", None)):
                        return None, "safety_unavailable"
                    try:
                        context.route("**/*", bridge.route)
                        context.route_web_socket("**/*", bridge.websocket)
                    except Exception:
                        return None, "safety_unavailable"
                    context.set_default_timeout(bridge.remaining_ms())
                    context.set_default_navigation_timeout(bridge.remaining_ms())
                    page = context.new_page()
                    page.goto(url, wait_until=wait_until, timeout=bridge.remaining_ms())
                    if bridge.failure:
                        return None, bridge.failure
                    bridge.remaining_ms()
                    html = page.content()
                    bridge.remaining_ms()
                    if len(html.encode("utf-8")) > _MAX_HTML_BYTES:
                        return None, "html_limit"
                    return html, "ok"
                finally:
                    context.close()
            finally:
                browser.close()
    except Exception as exc:
        reason = bridge.failure or "error"
        logger.warning("rendered_page_fetcher_error reason=%s error_type=%s", reason, type(exc).__name__)
        return None, reason


def _encode_result(html: str | None, reason: str) -> bytes:
    body = html.encode("utf-8") if html is not None else b""
    if len(body) > _MAX_HTML_BYTES:
        html, body, reason = None, b"", "html_limit"
    reason_bytes = reason.encode("ascii")
    if not 0 < len(reason_bytes) <= _MAX_REASON_BYTES:
        raise ValueError("invalid_render_reason")
    return _IPC_HEADER.pack(html is not None, len(reason_bytes), len(body)) + reason_bytes + body


def _render_worker(connection: socket.socket, url: str, timeout_ms: int, wait_until: str) -> None:
    acknowledged = False
    try:
        os.setsid()
        connection.sendall(b"R")
        if connection.recv(1) != b"A":
            return
        acknowledged = True
        connection.sendall(_encode_result(*_render_browser(url, timeout_ms=timeout_ms, wait_until=wait_until)))
    except Exception:
        if acknowledged:
            with suppress(Exception):
                connection.sendall(_encode_result(None, "error"))
    finally:
        connection.close()


def render_page_with_reason(
    url: str, *, timeout_ms: int = 15000, wait_until: str = "networkidle"
) -> tuple[str | None, str]:
    """Render through bounded public HTTP bridging, never browser direct fetch.

    Unsupported safety features, redirects, blocked requests and budget exhaustion
    return explicit fallback reasons. A POSIX worker deadline also bounds stalled
    browser operations. Proxy and browser controls are not an OS network sandbox.
    Worker-to-parent IPC uses a six-byte header plus ASCII reason and raw UTF-8
    HTML, capped at 2 MiB + 71 bytes including the ready marker. The parent sends
    one acknowledgement byte before the worker may start the browser.
    """
    if not isinstance(timeout_ms, int) or timeout_ms <= 0:
        return None, "invalid_timeout"
    if wait_until not in {"commit", "domcontentloaded", "load", "networkidle"}:
        return None, "invalid_wait_until"
    if os.name != "posix":
        return None, "safety_unavailable"
    if not _check_playwright():
        return None, "not_installed"
    check_run_control()
    timeout_ms = min(timeout_ms, _MAX_TIMEOUT_MS)
    deadline = monotonic() + timeout_ms / 1000
    process_context = multiprocessing.get_context("spawn")
    receiver, sender = socket.socketpair()
    receiver.setblocking(False)
    process = process_context.Process(target=_render_worker, args=(sender, url, timeout_ms, wait_until))
    group_confirmed = False
    try:
        process.start()
        sender.close()
        buffer = bytearray()
        received_bytes = 0
        expected_size = None
        with selectors.DefaultSelector() as selector:
            selector.register(receiver, selectors.EVENT_READ)
            while True:
                check_run_control()
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return None, "deadline_exceeded"
                if not selector.select(min(remaining, 0.05)):
                    continue
                try:
                    chunk = receiver.recv(min(65536, _MAX_IPC_BYTES - received_bytes + 1))
                except BlockingIOError:
                    continue
                check_run_control()
                if monotonic() >= deadline:
                    return None, "deadline_exceeded"
                if not chunk:
                    return None, "error"
                received_bytes += len(chunk)
                if received_bytes > _MAX_IPC_BYTES:
                    return None, "ipc_limit"
                if not group_confirmed:
                    if chunk[:1] != b"R":
                        return None, "error"
                    group_confirmed = True
                    receiver.send(b"A")
                    chunk = chunk[1:]
                buffer.extend(chunk)
                if expected_size is None and len(buffer) >= _IPC_HEADER.size:
                    has_html, reason_size, html_size = _IPC_HEADER.unpack_from(buffer)
                    if html_size > _MAX_HTML_BYTES:
                        return None, "html_limit"
                    if has_html not in (0, 1) or not 0 < reason_size <= _MAX_REASON_BYTES or (not has_html and html_size):
                        return None, "error"
                    expected_size = _IPC_HEADER.size + reason_size + html_size
                if expected_size is not None and len(buffer) >= expected_size:
                    if len(buffer) > expected_size:
                        return None, "error"
                    body_start = _IPC_HEADER.size + reason_size
                    reason = bytes(buffer[_IPC_HEADER.size:body_start]).decode("ascii")
                    html = bytes(buffer[body_start:]).decode("utf-8") if has_html else None
                    check_run_control()
                    if monotonic() >= deadline:
                        return None, "deadline_exceeded"
                    return html, reason
    except Exception as exc:
        logger.warning("rendered_page_worker_error error_type=%s", type(exc).__name__)
        return None, "error"
    finally:
        receiver.close()
        sender.close()
        if process.pid is not None:
            with suppress(ProcessLookupError):
                if group_confirmed:
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    os.kill(process.pid, signal.SIGKILL)
            process.join(timeout=0.2)
            if process.is_alive():
                process.kill()
                process.join(timeout=0.2)
            if not process.is_alive():
                process.close()


def render_page(url: str, *, timeout_ms: int = 15000, wait_until: str = "networkidle") -> str | None:
    """Render a page and return its full HTML, or None on any failure.

    Thin wrapper over render_page_with_reason for callers that don't need the
    reason. Kept for back-compat."""
    html, _reason = render_page_with_reason(url, timeout_ms=timeout_ms, wait_until=wait_until)
    return html
