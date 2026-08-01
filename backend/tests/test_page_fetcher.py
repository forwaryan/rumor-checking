from __future__ import annotations

from pathlib import Path

from backend.app.models.schemas import MockFetchResult
from backend.app.services import page_fetcher
from backend.app.services.page_fetcher import _strip_tags, fetch_page_snippets
from backend.app.services.retrieval_models import SearchResult
from backend.app.services.url_fetch_cache import UrlFetchCache


def _result(result_id: str, url: str) -> SearchResult:
    return SearchResult(
        case_id="real_search",
        query="q",
        result_id=result_id,
        title=f"title-{result_id}",
        url=url,
        source_name="src",
        published_at="2026-07-01",
        snippet="s",
        source_tier="B",
    )


def test_strip_tags_drops_style_and_script_contents():
    # Regression: naive tag-stripping left <style>/<script> INNER text behind,
    # leaking CSS like ".g-layout-wrap{height:2.7rem}" into the "body".
    html = (
        "<html><head><style>.g-layout-wrap{height:2.7rem;position:relative;}</style>"
        "<script>var a=1;function f(){return 2;}</script></head>"
        "<body><p>王励勤表示回归仍在联系过程中。</p></body></html>"
    )
    out = _strip_tags(html)
    assert "王励勤表示回归仍在联系过程中。" in out
    assert "g-layout-wrap" not in out
    assert "height" not in out
    assert "function" not in out


def test_fetch_page_snippets_keyed_by_url(monkeypatch):
    # The sole consumer (claim_correction) looks bodies up by evidence url, so the
    # returned dict must be keyed by url — not result_id.
    r = _result("q0-pw-3", "https://www.163.com/dy/article/KN6KST440529EJSU.html")
    monkeypatch.setattr(
        page_fetcher, "_fetch_single_page",
        lambda url: "王励勤回应樊振东回归国家队情况，表示已经在联系过程中。" * 3,
    )
    bodies = fetch_page_snippets([r])
    assert set(bodies.keys()) == {r.url}
    assert r.result_id not in bodies


def test_cache_namespace_isolates_raw_html_from_extracted_text(tmp_path: Path):
    # Bug 1 core: page_fetcher stores RAW html in body; UrlContentExtractor stores
    # already-extracted article text in the same field. They share one cache keyed
    # by url — a namespace must keep the two formats in disjoint keyspaces so a raw
    # write can never be served to the extractor path (and vice versa).
    cache = UrlFetchCache(cache_root=tmp_path, ttl_seconds=3600)
    url = "https://m.gmw.cn/2026-03/04/content_1304364760.htm"

    cache.write(url=url, result=MockFetchResult(status="ok", body="<html>raw</html>"), namespace="raw_html")
    cache.write(url=url, result=MockFetchResult(status="ok", body="clean article text"))

    assert cache.read(url=url, namespace="raw_html").body == "<html>raw</html>"
    assert cache.read(url=url).body == "clean article text"
    # Distinct on-disk keys — no collision.
    assert cache.build_cache_key(url=url, namespace="raw_html") != cache.build_cache_key(url=url)

