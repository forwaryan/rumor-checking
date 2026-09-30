import gzip
import socket

import httpx
import pytest

from backend.app.services.http_reliability import reliable_get
from backend.app.services.url_validator import is_safe_url


@pytest.fixture
def transport(monkeypatch):
    requests = []
    options = []
    responses = []
    original_client = httpx.Client

    def send(request):
        requests.append(request)
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def client(**kwargs):
        options.append(kwargs.copy())
        return original_client(transport=httpx.MockTransport(send), **kwargs)

    monkeypatch.setattr(httpx, "Client", client)
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", port)),
    ])
    return requests, options, responses


def fetch(url="https://example.org/article", **kwargs):
    return reliable_get(url, headers=kwargs.pop("headers", {}), timeout=1, max_retries=0, **kwargs)


def test_pins_public_ip_and_drops_credentials_and_environment_proxy(transport, monkeypatch):
    requests, options, responses = transport
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9999")
    responses.append(httpx.Response(200, content=b"public text"))
    response = fetch(headers={"Authorization": "secret", "Cookie": "secret", "Host": "private.test"})
    assert requests[0].url.host == "93.184.216.34"
    assert requests[0].headers["host"] == "example.org"
    assert requests[0].extensions["sni_hostname"] == "example.org"
    assert requests[0].headers["accept-encoding"] == "identity"
    assert "authorization" not in requests[0].headers
    assert "cookie" not in requests[0].headers
    assert options[0]["trust_env"] is False
    assert options[0]["follow_redirects"] is False
    assert options[0]["verify"] is True
    assert str(response.url) == "https://example.org/article"


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://[::1]/", "http://10.0.0.1/",
                                 "http://224.0.0.1/", "http://user:pass@example.org/", "file:///etc/passwd"])
def test_private_or_credential_urls_never_reach_transport(transport, url):
    requests, _options, _responses = transport
    with pytest.raises(ValueError):
        fetch(url)
    assert not requests


def test_private_redirect_blocked_and_relative_redirect_uses_logical_host(transport):
    requests, _options, responses = transport
    responses.extend([httpx.Response(302, headers={"location": "/next", "set-cookie": "secret=1"}),
                      httpx.Response(302, headers={"location": "http://127.0.0.1/private"})])
    with pytest.raises(ValueError):
        fetch()
    assert [str(request.url) for request in requests] == ["https://93.184.216.34/article", "https://93.184.216.34/next"]
    assert all("cookie" not in request.headers for request in requests)


def test_dns_failure_and_mixed_public_private_answers_fail_closed(transport, monkeypatch):
    requests, _options, _responses = transport
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: (_ for _ in ()).throw(socket.gaierror()))
    assert not is_safe_url("https://example.org")
    with pytest.raises(ValueError):
        fetch()
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [
        (2, 1, 6, "", ("93.184.216.34", 443)), (2, 1, 6, "", ("10.0.0.8", 443)),
    ])
    with pytest.raises(ValueError):
        fetch()
    assert not requests


def test_header_size_and_compression_rejected_before_stream_read(transport):
    _requests, _options, responses = transport
    for headers in [{"content-length": "99999999"}, {"content-encoding": "gzip"}]:
        class Unreadable(httpx.SyncByteStream):
            closed = False

            def __iter__(self):
                pytest.fail("rejected response body must not be read")
                yield b""

            def close(self):
                self.closed = True

        stream = Unreadable()
        responses.append(httpx.Response(200, headers=headers, stream=stream))
        with pytest.raises(ValueError):
            fetch(max_response_bytes=32)
        assert stream.closed


def test_chunked_stream_stops_at_byte_limit_and_closes(transport):
    _requests, _options, responses = transport

    class Chunks(httpx.SyncByteStream):
        closed = False
        reads = 0

        def __iter__(self):
            for _index in range(10):
                self.reads += 1
                yield b"0123456789"

        def close(self):
            self.closed = True

    stream = Chunks()
    responses.append(httpx.Response(200, stream=stream))
    with pytest.raises(ValueError):
        fetch(max_response_bytes=24)
    assert stream.reads == 3
    assert stream.closed


def test_unexpected_compression_is_not_silently_accepted(transport):
    _requests, _options, responses = transport
    responses.append(httpx.Response(200, content=gzip.compress(b"a" * 10000), headers={"content-encoding": "gzip"}))
    with pytest.raises(ValueError):
        fetch(max_response_bytes=24)
