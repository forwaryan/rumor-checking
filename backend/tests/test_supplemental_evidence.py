import ssl
from ipaddress import ip_address

import httpcore
import httpx
import pytest

from backend.app.models.schemas import AnalyzeRequest, MockFetchResult
from backend.app.services.retrieval_models import RetrievalBundle, SearchResult
from backend.app.services.supplemental_evidence import (
    SupplementalUrlExtractor,
    _source_tier,
    load_supplemental_evidence,
    merge_supplemental_evidence,
    supplemental_evidence_scope,
)


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    def resolve(host, *args, **kwargs):
        try:
            address = str(ip_address(host))
        except ValueError:
            address = "93.184.216.34"
        return [(2, 1, 6, "", (address, 443))]

    monkeypatch.setattr("backend.app.services.url_validator.socket.getaddrinfo", resolve)


@pytest.mark.parametrize("url", ["http://127.0.0.1/data", "http://10.0.0.1/data", "file:///etc/passwd", "http://[::1]/", "http://user:pass@example.org/"])
def test_blocks_unsafe_supplement_without_request(monkeypatch, url):
    def unexpected(*args, **kwargs):
        pytest.fail("unsafe URL must not reach HTTP transport")
    monkeypatch.setattr(httpx.Client, "send", unexpected)
    request = AnalyzeRequest(raw_input="复核", request_context={"supplemental_urls": [url]})
    results, failures = load_supplemental_evidence(request)
    assert not results
    assert len(failures) == 1


def test_blocks_private_redirect_before_following(monkeypatch):
    requested = []

    def get(self, request, **kwargs):
        requested.append(str(request.url))
        assert self.follow_redirects is False
        return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"}, request=request)

    monkeypatch.setattr(httpx.Client, "send", get)
    fetched = SupplementalUrlExtractor().extract("https://example.org/article")
    assert fetched.status != "ok"
    assert requested == ["https://93.184.216.34/article"]


def test_public_hostname_resolving_to_private_network_is_blocked(monkeypatch):
    monkeypatch.setattr("backend.app.services.url_validator.socket.getaddrinfo",
                        lambda *args, **kwargs: [(2, 1, 6, "", ("10.0.0.5", 443))])
    monkeypatch.setattr(httpx.Client, "send",
                        lambda *args, **kwargs: pytest.fail("private address reached transport"))
    assert SupplementalUrlExtractor().extract("https://example.org/article").status != "ok"


def test_reads_once_keeps_result_grounding_and_ignores_user_note(monkeypatch):
    calls = []

    def extract(self, url):
        calls.append(url)
        return MockFetchResult(status="ok", title="参观公告", body="周三免费开放。", final_url=url, source_name="官方政府")

    monkeypatch.setattr(SupplementalUrlExtractor, "extract", extract)
    request = AnalyzeRequest(raw_input="免费吗", request_context={
        "supplemental_urls": ["https://example.org/article", "https://example.org/article"],
        "review_note": "据我了解票价100元", "source_tier": "S",
    })
    with supplemental_evidence_scope():
        bundle = merge_supplemental_evidence(request, None)
        assert merge_supplemental_evidence(request, bundle) is bundle
        assert calls == ["https://example.org/article"]
    evidence = bundle.canonical_results[0]
    assert evidence.result_id.startswith("supp-")
    assert evidence.source_tier == "C"
    assert evidence.source_name == "example.org"
    assert "100元" not in evidence.snippet
    # The cache belongs to the request scope, never to the request itself: nothing is
    # stashed on the model that could be persisted with it, and a later scope re-reads.
    assert "_supplemental_evidence" not in request.model_dump()
    with supplemental_evidence_scope():
        merge_supplemental_evidence(request, None)
    assert calls == ["https://example.org/article"] * 2


@pytest.mark.parametrize("host,tier", [("news.gov.cn", "S"), ("news.gov.cn.evil.org", "C"), ("fakegov.cn", "C"), ("www.news.cn", "A"), ("news.cn.evil.org", "C")])
def test_source_tier_uses_domain_boundaries(host, tier):
    assert _source_tier(host) == tier


def test_supplement_limits_and_failed_body(monkeypatch):
    calls = []

    def extract(self, url):
        calls.append(url)
        return MockFetchResult(status="ok", body="", final_url=url)

    monkeypatch.setattr(SupplementalUrlExtractor, "extract", extract)
    request = AnalyzeRequest(raw_input="复核", request_context={"supplemental_urls": [f"https://example.org/{index}" for index in range(8)]})
    results, failures = load_supplemental_evidence(request)
    assert len(calls) == 5
    assert not results
    assert len(failures) == 6


def test_pinned_connection_ignores_rebound_dns_and_environment_proxies(monkeypatch):
    lookups = []
    connections = []
    tls_names = []
    writes = []

    def changing_dns(host, port):
        lookups.append(host)
        address = "93.184.216.34" if len(lookups) == 1 else "10.0.0.9"
        return [(2, 1, 6, "", (address, port))]

    class Stream:
        def read(self, max_bytes, timeout=None):
            return b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"

        def write(self, buffer, timeout=None):
            writes.append(buffer)

        def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            assert ssl_context.check_hostname
            assert ssl_context.verify_mode == ssl.CERT_REQUIRED
            tls_names.append(server_hostname)
            return self

        def get_extra_info(self, info):
            return None

        def close(self):
            pass

    def connect(self, host, port, **kwargs):
        connections.append((host, port))
        assert changing_dns("example.org", port)[0][4][0] == "10.0.0.9"
        assert host == "93.184.216.34"
        return Stream()

    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:8123")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:8124")
    monkeypatch.setenv("SSL_CERT_FILE", "/nonexistent/environment-ca.pem")
    monkeypatch.setattr("backend.app.services.url_validator.socket.getaddrinfo", changing_dns)
    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", connect)
    response = SupplementalUrlExtractor()._fetch("https://example.org:8443/article")
    assert connections == [("93.184.216.34", 8443)]
    assert tls_names == ["example.org"]
    assert b"Host: example.org:8443\r\n" in b"".join(writes)
    assert str(response.url) == "https://example.org:8443/article"
    assert response.text == "ok"


def test_public_redirect_revalidates_and_pins_each_destination(monkeypatch):
    lookups = []
    requests = []

    def dns(host, port):
        lookups.append(host)
        address = {"example.org": "93.184.216.34", "news.example.org": "93.184.216.35"}[host]
        return [(2, 1, 6, "", (address, port))]

    def send(self, request, **kwargs):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(302, headers={"location": "https://news.example.org/story"}, request=request)
        return httpx.Response(200, content="article", request=request)

    monkeypatch.setattr("backend.app.services.url_validator.socket.getaddrinfo", dns)
    monkeypatch.setattr(httpx.Client, "send", send)
    response = SupplementalUrlExtractor()._fetch("https://example.org/article")
    assert lookups == ["example.org", "news.example.org"]
    assert [request.url.host for request in requests] == ["93.184.216.34", "93.184.216.35"]
    assert [request.headers["host"] for request in requests] == lookups
    assert [request.extensions["sni_hostname"] for request in requests] == lookups
    assert str(response.url) == "https://news.example.org/story"


def test_real_supplement_discards_mock_material_and_fixture_metadata(monkeypatch):
    monkeypatch.setattr(SupplementalUrlExtractor, "extract", lambda self, url: MockFetchResult(
        status="ok", title="真实公告", body="真实正文", final_url=url))
    mock_result = SearchResult(case_id="fixture", query="q", result_id="fake", title="合成内容",
                               url="https://fake.example.org", source_name="合成来源", source_tier="S",
                               published_at="", snippet="合成正文")
    bundle = RetrievalBundle(query="q", provider_name="mock", matched_case_id="fixture",
                             raw_results=(mock_result,), canonical_results=(mock_result,),
                             expected_origin_result_id="fake", cache_status="hit")
    request = AnalyzeRequest(raw_input="复核", request_context={"supplemental_urls": ["https://example.org/article"]})
    merged = merge_supplemental_evidence(request, bundle)
    assert merged.provider_name == "supplemental_url"
    assert [item.title for item in merged.canonical_results] == ["真实公告"]
    assert [item.title for item in merged.raw_results] == ["真实公告"]
    assert merged.matched_case_id is None
    assert merged.expected_origin_result_id is None
    assert merged.cache_status == "not_used"
