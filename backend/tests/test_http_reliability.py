from __future__ import annotations

import httpx
import pytest

from backend.app.services import http_reliability
from backend.app.services.http_reliability import _backoff_seconds, reliable_get


class _Script:
    """Shared, stateful replay of responses/exceptions. reliable_get creates a
    fresh client per attempt (session isolation), so the call counter must live
    OUTSIDE the client — here — to advance across attempts."""

    def __init__(self, script):
        self._script = list(script)
        self.calls = 0

    def next(self):
        item = self._script[self.calls]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        return item


class _FakeClient:
    def __init__(self, script: _Script):
        self._script = script

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, headers=None, timeout=None):
        return self._script.next()


def _resp(status: int) -> httpx.Response:
    return httpx.Response(status_code=status, request=httpx.Request("GET", "https://x"))


def _patch_client(monkeypatch, script):
    shared = _Script(script)

    def _factory(*args, **kwargs):
        return _FakeClient(shared)

    monkeypatch.setattr(http_reliability.httpx, "Client", _factory)
    return {"script": shared}


def test_retries_transient_timeout_then_succeeds(monkeypatch):
    slept = []
    holder = _patch_client(monkeypatch, [httpx.ConnectTimeout("boom"), _resp(200)])

    resp = reliable_get(
        "https://x", headers={}, timeout=5.0, max_retries=2, sleep=slept.append
    )

    assert resp.status_code == 200
    assert holder["script"].calls == 2  # one failed attempt + one success
    assert len(slept) == 1  # one backoff before the successful retry


def test_retries_5xx_then_succeeds(monkeypatch):
    slept = []
    _patch_client(monkeypatch, [_resp(503), _resp(200)])

    resp = reliable_get("https://x", headers={}, timeout=5.0, max_retries=2, sleep=slept.append)

    assert resp.status_code == 200
    assert len(slept) == 1


def test_does_not_retry_4xx(monkeypatch):
    slept = []
    _patch_client(monkeypatch, [_resp(404)])

    resp = reliable_get("https://x", headers={}, timeout=5.0, max_retries=3, sleep=slept.append)

    # 404 is a definitive answer — returned immediately, never retried.
    assert resp.status_code == 404
    assert slept == []


def test_does_not_retry_403_to_avoid_hammering(monkeypatch):
    slept = []
    _patch_client(monkeypatch, [_resp(403)])

    resp = reliable_get("https://x", headers={}, timeout=5.0, max_retries=3, sleep=slept.append)

    assert resp.status_code == 403
    assert slept == []


def test_raises_after_exhausting_transient_retries(monkeypatch):
    slept = []
    _patch_client(monkeypatch, [httpx.ConnectError("x"), httpx.ConnectError("x")])

    with pytest.raises(httpx.ConnectError):
        reliable_get("https://x", headers={}, timeout=5.0, max_retries=1, sleep=slept.append)

    assert len(slept) == 1  # one backoff between the two attempts


def test_backoff_is_exponential_and_capped():
    assert _backoff_seconds(1) == 0.5
    assert _backoff_seconds(2) == 1.0
    assert _backoff_seconds(3) == 2.0
    assert _backoff_seconds(10) == 4.0  # capped
