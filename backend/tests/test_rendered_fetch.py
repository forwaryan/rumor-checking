"""Tests for the rendered page fetch fallback path."""
from __future__ import annotations

import os
import signal
import socket
import struct
import sys
import threading
import time
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
import pytest

from backend.app.services import rendered_page_fetcher as renderer
from backend.app.services.rendered_page_fetcher import _check_playwright, render_page


def test_render_page_returns_none_when_playwright_missing():
    with patch.dict("sys.modules", {"playwright": None, "playwright.sync_api": None}), patch.object(renderer, "is_safe_url", return_value=True):
        import importlib

        import backend.app.services.rendered_page_fetcher as mod
        mod._PLAYWRIGHT_AVAILABLE = None  # reset cache
        result = mod.render_page("https://example.com")
        assert result is None


@pytest.fixture
def browser_bridge(monkeypatch):
    monkeypatch.setattr(renderer, "is_safe_url", lambda url: True)
    routes = []
    context = SimpleNamespace()
    page = SimpleNamespace(content=Mock(return_value="<html><body>公开正文</body></html>"))

    def route(pattern, handler):
        context.handler = handler

    def websocket(pattern, handler):
        context.websocket_handler = handler

    def navigate(*args, **kwargs):
        for pending in routes:
            context.handler(pending)

    page.goto = Mock(side_effect=navigate)
    context.route = Mock(side_effect=route)
    context.route_web_socket = Mock(side_effect=websocket)
    context.new_page = Mock(return_value=page)
    context.set_default_timeout = Mock()
    context.set_default_navigation_timeout = Mock()
    context.close = Mock()
    browser = SimpleNamespace(new_context=Mock(return_value=context), close=Mock())
    chromium = SimpleNamespace(launch=Mock(return_value=browser))
    manager = Mock()
    manager.__enter__ = Mock(return_value=SimpleNamespace(chromium=chromium))
    manager.__exit__ = Mock(return_value=False)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", SimpleNamespace(sync_playwright=lambda: manager))
    response = httpx.Response(200, content=b"public response", headers={"content-type": "text/html", "set-cookie": "private=1", "alt-svc": "h3=:443"})
    transport = Mock(return_value=response)
    monkeypatch.setattr(renderer, "reliable_get", transport, raising=False)

    def request(url="https://example.org/page", method="GET"):
        pending = SimpleNamespace(request=SimpleNamespace(url=url, method=method, resource_type="document",
                                  headers={"cookie": "secret", "authorization": "Bearer secret"}), abort=Mock(), fulfill=Mock())
        routes.append(pending)
        return pending

    return SimpleNamespace(request=request, routes=routes, context=context, page=page, browser=browser,
                           chromium=chromium, transport=transport)


def test_browser_requests_use_safe_bridge_and_fail_closed_proxy(browser_bridge):
    route = browser_bridge.request()
    html, reason = renderer._render_browser("https://example.org/page", timeout_ms=1000, wait_until="load")
    assert reason == "ok" and "公开正文" in html
    options = browser_bridge.chromium.launch.call_args.kwargs
    assert options["proxy"]["server"].startswith("http://127.0.0.1:")
    assert "--proxy-bypass-list=<-loopback>" in options["args"]
    assert "--disable-quic" in options["args"]
    assert "--force-webrtc-ip-handling-policy=disable_non_proxied_udp" in options["args"]
    assert browser_bridge.browser.new_context.call_args.kwargs["service_workers"] == "block"
    request = browser_bridge.transport.call_args.kwargs
    assert request["follow_redirects"] is False and request["max_retries"] == 0
    assert not {"cookie", "authorization"} & {name.lower() for name in request["headers"]}
    assert route.fulfill.call_args.kwargs["body"] == b"public response"
    assert route.fulfill.call_args.kwargs["headers"] == {"content-type": "text/html"}
    assert browser_bridge.browser.close.called


@pytest.mark.parametrize("method,url", [("POST", "https://example.org"), ("GET", "file:///etc/passwd")])
def test_browser_rejects_unsupported_requests(browser_bridge, method, url):
    route = browser_bridge.request(url, method)
    html, reason = renderer._render_browser("https://example.org", timeout_ms=1000, wait_until="load")
    assert html is None and reason == "blocked_request"
    assert route.abort.called and not browser_bridge.transport.called


def test_private_target_cannot_fall_back_to_browser_network(browser_bridge):
    route = browser_bridge.request("http://127.0.0.1/private")
    browser_bridge.transport.side_effect = ValueError("unsafe_public_url")
    html, reason = renderer._render_browser("https://example.org", timeout_ms=1000, wait_until="load")
    assert html is None and reason == "bridge_failed"
    assert route.abort.called and not route.fulfill.called


def test_browser_refuses_redirects_instead_of_leaking_unintercepted_redirects(browser_bridge):
    route = browser_bridge.request()
    browser_bridge.transport.return_value = httpx.Response(302, headers={"location": "http://127.0.0.1/private"})
    assert renderer._render_browser("https://example.org", timeout_ms=1000, wait_until="load") == (None, "redirect_not_supported")
    assert route.abort.called and not route.fulfill.called


def test_missing_websocket_routing_degrades_before_opening_page(browser_bridge):
    browser_bridge.context.route_web_socket = None
    assert renderer._render_browser("https://example.org", timeout_ms=1000, wait_until="load") == (None, "safety_unavailable")
    assert not browser_bridge.context.new_page.called


def test_websocket_is_closed_without_connecting(browser_bridge):
    connection = SimpleNamespace(close=Mock())
    browser_bridge.page.goto.side_effect = lambda *args, **kwargs: browser_bridge.context.websocket_handler(connection)
    assert renderer._render_browser("https://example.org", timeout_ms=1000, wait_until="load") == (None, "blocked_websocket")
    assert connection.close.called


def test_browser_enforces_request_and_byte_budgets(browser_bridge, monkeypatch):
    monkeypatch.setattr(renderer, "_MAX_REQUESTS", 1, raising=False)
    browser_bridge.request()
    extra = browser_bridge.request()
    assert renderer._render_browser("https://example.org", timeout_ms=1000, wait_until="load") == (None, "request_limit")
    assert browser_bridge.transport.call_count == 1 and extra.abort.called
    browser_bridge.routes.pop()
    monkeypatch.setattr(renderer, "_MAX_TOTAL_BYTES", 3, raising=False)
    assert renderer._render_browser("https://example.org", timeout_ms=1000, wait_until="load") == (None, "byte_limit")


def test_browser_checks_global_deadline_after_http_bridge(browser_bridge, monkeypatch):
    now = [0.0]
    monkeypatch.setattr(renderer, "monotonic", lambda: now[0], raising=False)
    browser_bridge.request()

    def fetch(*args, **kwargs):
        now[0] = 2.0
        return httpx.Response(200, content=b"late")

    browser_bridge.transport.side_effect = fetch
    assert renderer._render_browser("https://example.org", timeout_ms=1000, wait_until="load") == (None, "deadline_exceeded")


def _hanging_browser_worker(connection, url, timeout_ms, wait_until):
    os.setsid()
    time.sleep(10)


@pytest.mark.skipif(os.name != "posix", reason="POSIX process containment only")
def test_parent_deadline_terminates_stalled_browser_worker(monkeypatch):
    monkeypatch.setattr(renderer, "_check_playwright", lambda: True)
    monkeypatch.setattr(renderer, "_render_worker", _hanging_browser_worker)
    started = time.monotonic()
    assert renderer.render_page_with_reason("https://example.org", timeout_ms=60) == (None, "deadline_exceeded")
    assert time.monotonic() - started < 1.0


def _test_worker_handshake(connection):
    os.setsid()
    connection.sendall(b"R")
    assert connection.recv(1) == b"A"


def _partial_frame_worker(connection, url, timeout_ms, wait_until):
    _test_worker_handshake(connection)
    payload = struct.pack("!BBI", 1, 2, 1024) + b"ok<"
    connection.sendall(payload[:1] if Path(url).name == "partial-header" else payload)
    Path(url).touch()
    time.sleep(1.5)
    connection.close()


def _allow_worker_startup(monkeypatch, marker):
    startup = time.monotonic()
    worker_started = []

    def clock():
        now = time.monotonic()
        if not worker_started and marker.exists():
            worker_started.append(now)
        return now - worker_started[0] if worker_started else max(0, now - startup - 5)

    monkeypatch.setattr(renderer, "monotonic", clock)
    return worker_started


@pytest.mark.skipif(os.name != "posix", reason="POSIX process containment only")
@pytest.mark.parametrize("frame", ["partial-header", "partial-body"])
def test_partial_ipc_frame_cannot_block_parent_deadline(monkeypatch, tmp_path, frame):
    monkeypatch.setattr(renderer, "_check_playwright", lambda: True)
    monkeypatch.setattr(renderer, "_render_worker", _partial_frame_worker)
    marker = tmp_path / frame
    worker_started = _allow_worker_startup(monkeypatch, marker)
    result = renderer.render_page_with_reason(str(marker), timeout_ms=200)
    assert marker.exists()
    assert result == (None, "deadline_exceeded")
    assert time.monotonic() - worker_started[0] < 1.0


@pytest.mark.skipif(os.name != "posix", reason="POSIX process containment only")
def test_partial_ipc_frame_remains_cancellable(monkeypatch, tmp_path):
    from backend.app.services.run_control import RunControl, RunStopped, reset_run_control, set_run_control

    monkeypatch.setattr(renderer, "_check_playwright", lambda: True)
    monkeypatch.setattr(renderer, "_render_worker", _partial_frame_worker)
    marker = tmp_path / "partial-body"
    token = set_run_control(RunControl(cancelled=marker.exists))
    try:
        with pytest.raises(RunStopped, match="user_cancelled"):
            renderer.render_page_with_reason(str(marker), timeout_ms=5000)
    finally:
        reset_run_control(token)
    assert marker.exists()
    assert time.time() - marker.stat().st_mtime < 1.0


@pytest.mark.parametrize("acknowledge", [False, True])
def test_worker_cannot_start_browser_before_group_ack(monkeypatch, acknowledge):
    session_started = []
    monkeypatch.setattr(renderer, "os", SimpleNamespace(setsid=lambda: session_started.append(True)))
    browser = Mock(return_value=("<html>ok</html>", "ok"))
    monkeypatch.setattr(renderer, "_render_browser", browser)
    receiver, sender = socket.socketpair()
    receiver.settimeout(1)
    worker = threading.Thread(target=renderer._render_worker, args=(sender, "offline", 1000, "load"))
    worker.start()
    try:
        assert receiver.recv(1) == b"R"
        assert session_started == [True]
        assert not browser.called
        if acknowledge:
            receiver.sendall(b"A")
            assert receiver.recv(1024) == renderer._encode_result("<html>ok</html>", "ok")
    finally:
        receiver.close()
        worker.join(1)
    assert not worker.is_alive()
    assert browser.call_count == int(acknowledge)


def _bounded_protocol_worker(connection, url, timeout_ms, wait_until):
    _test_worker_handshake(connection)
    marker = Path(url)
    marker.touch()
    if marker.name == "oversized_html":
        connection.sendall(struct.pack("!BBI", 1, 2, 0xFFFFFFFF))
        time.sleep(1.5)
    elif marker.name == "oversized_reason":
        connection.sendall(struct.pack("!BBI", 0, 255, 0))
        time.sleep(1.5)
    elif marker.name == "invalid_utf8":
        connection.sendall(struct.pack("!BBI", 1, 2, 1) + b"ok\xff")
    else:
        connection.sendall(renderer._encode_result("界" * (renderer._MAX_HTML_BYTES // 3), "ok"))
    connection.close()


@pytest.mark.skipif(os.name != "posix", reason="POSIX process containment only")
@pytest.mark.parametrize("payload,reason", [("oversized_html", "html_limit"), ("oversized_reason", "error"), ("invalid_utf8", "error"), ("unicode", "ok")])
def test_ipc_rejects_oversized_headers_before_reading_body(monkeypatch, tmp_path, payload, reason):
    monkeypatch.setattr(renderer, "_check_playwright", lambda: True)
    monkeypatch.setattr(renderer, "_render_worker", _bounded_protocol_worker)
    marker = tmp_path / payload
    html, actual_reason = renderer.render_page_with_reason(str(marker), timeout_ms=5000)
    assert actual_reason == reason
    assert marker.exists()
    assert time.time() - marker.stat().st_mtime < 1.0
    if html is not None:
        assert html == "界" * (renderer._MAX_HTML_BYTES // 3)
        assert len(renderer._encode_result(html, reason)) + 1 <= renderer._MAX_IPC_BYTES


def _exited_leader_worker(connection, url, timeout_ms, wait_until):
    _test_worker_handshake(connection)
    leader_pid = os.getpid()
    descendant = os.fork()
    if descendant:
        Path(url + ".pids").write_text(f"{leader_pid},{descendant}")
        os._exit(0)
    time.sleep(0.2)
    Path(url).write_text("ready")
    html = b"<html>done</html>"
    connection.sendall(struct.pack("!BBI", 1, 2, len(html)) + b"ok" + html)
    for counter in range(500):
        Path(url).write_text(str(counter))
        time.sleep(0.02)
    os._exit(0)


@pytest.mark.skipif(os.name != "posix", reason="POSIX process containment only")
def test_exited_worker_leader_does_not_leave_descendants(monkeypatch, tmp_path):
    monkeypatch.setattr(renderer, "_check_playwright", lambda: True)
    monkeypatch.setattr(renderer, "_render_worker", _exited_leader_worker)
    heartbeat = tmp_path / "heartbeat"
    try:
        assert renderer.render_page_with_reason(str(heartbeat), timeout_ms=5000) == ("<html>done</html>", "ok")
        assert heartbeat.exists()
        time.sleep(0.05)
        previous = heartbeat.read_text() if heartbeat.exists() else None
        time.sleep(0.15)
        assert (heartbeat.read_text() if heartbeat.exists() else None) == previous
    finally:
        pids = Path(str(heartbeat) + ".pids")
        if pids.exists():
            leader, descendant = map(int, pids.read_text().split(","))
            with suppress(ProcessLookupError):
                if os.getpgid(descendant) == leader:
                    os.killpg(leader, signal.SIGKILL)


def test_budget_options_and_unsupported_platform_fail_closed(monkeypatch):
    assert renderer.render_page_with_reason("https://example.org", timeout_ms=0) == (None, "invalid_timeout")
    assert renderer.render_page_with_reason("https://example.org", wait_until="forever") == (None, "invalid_wait_until")
    monkeypatch.setattr(renderer, "os", SimpleNamespace(name="nt"))
    assert renderer.render_page_with_reason("https://example.org") == (None, "safety_unavailable")


def test_render_page_returns_none_for_unsafe_url():
    result = render_page("http://127.0.0.1:8080/admin")
    assert result is None


def test_try_rendered_fallback_gated_by_setting():
    """Disabled setting -> (None, "disabled"), and render is never attempted."""
    from types import SimpleNamespace

    from backend.app.agent_tools.tools import _try_rendered_fallback

    ctx = SimpleNamespace(settings=SimpleNamespace(rendered_fetch_enabled=False))
    body, reason = _try_rendered_fallback("https://example.com", ctx)
    assert body is None
    assert reason == "disabled"


def test_try_rendered_fallback_propagates_render_reason():
    """When enabled but the browser yields nothing, the render reason is surfaced."""
    from types import SimpleNamespace

    from backend.app.agent_tools.tools import _try_rendered_fallback

    ctx = SimpleNamespace(
        settings=SimpleNamespace(rendered_fetch_enabled=True, url_fetch_max_chars=12000),
    )
    with patch(
        "backend.app.services.rendered_page_fetcher.render_page_with_reason",
        return_value=(None, "not_installed"),
    ):
        body, reason = _try_rendered_fallback("https://news.163.com/article", ctx)
        assert body is None
        assert reason == "not_installed"


def test_try_rendered_fallback_extracts_body_on_html():
    """Browser returns extractable HTML -> (body, "ok")."""
    from types import SimpleNamespace

    from backend.app.agent_tools.tools import _try_rendered_fallback

    html = """<html><head><title>测试标题</title></head><body>
    <article><p>这是一段完整的新闻正文内容，包含了足够的中文字符来通过长度阈值检测，确保提取器会返回状态为ok的结果。这是更多的内容来满足140字符的要求。为了达到提取器的最低字数门槛，我们需要继续填充更多有意义的中文文字。据悉樊振东已于今年一月重新回到国家队训练基地开始备战巴黎奥运会后续赛事安排。</p></article>
    </body></html>"""

    ctx = SimpleNamespace(
        settings=SimpleNamespace(rendered_fetch_enabled=True, url_fetch_max_chars=12000),
    )
    with patch(
        "backend.app.services.rendered_page_fetcher.render_page_with_reason",
        return_value=(html, "ok"),
    ):
        body, reason = _try_rendered_fallback("https://news.163.com/article", ctx)
        assert body is not None
        assert "新闻正文" in body
        assert reason == "ok"
