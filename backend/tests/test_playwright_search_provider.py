from __future__ import annotations

from backend.app.core.config import get_settings
from backend.app.services.playwright_search_provider import (
    PlaywrightSearchProvider,
    _extract_baidu_items,
    _extract_bing_items,
    _clean_text,
)
from backend.app.services.retrieval_models import SearchResult


BAIDU_HTML = """
<html><body>
<div id="content_left">
  <div class="result c-container">
    <h3><a href="https://news.example.com/article-1">海州酸奶<em>超期</em>事件通报</a></h3>
    <div class="c-abstract">海州市场监管局通报涉事门店已停业整改，部分批次确认超过保质期。</div>
    <span class="c-color-gray">news.example.com</span>
  </div>
  <div class="result c-container">
    <h3><a href="https://gov.example.com/notice-2">官方回应：酸奶质量<em>抽检</em>结果</a></h3>
    <div class="c-abstract">经抽检确认三个批次不合格，责令整改。</div>
    <span class="c-color-gray">gov.example.com</span>
  </div>
</div>
<div id="content_right"></div>
</body></html>
"""

BING_HTML = """
<html><body>
<ol id="b_results">
  <li class="b_algo">
    <h2><a href="https://news.example.com/bing-1">京东游轮最新进展</a></h2>
    <div class="b_caption"><p>刘强东旗下探海游艇项目已开工。</p></div>
  </li>
  <li class="b_algo">
    <h2><a href="https://finance.example.com/bing-2">京东布局邮轮产业</a></h2>
    <div class="b_caption"><p>京东物流延伸至海运领域。</p></div>
  </li>
</ol>
</body></html>
"""


def test_extract_baidu_items_parses_title_url_snippet():
    items = _extract_baidu_items(BAIDU_HTML)
    assert len(items) == 2
    assert items[0]["url"] == "https://news.example.com/article-1"
    assert "超期" in items[0]["title"]
    assert "停业整改" in items[0]["snippet"]
    assert items[0]["source"] == "news.example.com"


def test_extract_bing_items_parses_title_url_snippet():
    items = _extract_bing_items(BING_HTML)
    assert len(items) == 2
    assert items[0]["url"] == "https://news.example.com/bing-1"
    assert "游轮" in items[0]["title"]
    assert "探海游艇" in items[0]["snippet"]


def test_clean_text_strips_html_and_whitespace():
    raw = "  <em>hello</em>   world  "
    assert _clean_text(raw) == "hello world"


def test_extract_baidu_empty_html_returns_empty():
    items = _extract_baidu_items("<html><body>no results here</body></html>")
    assert items == []


def test_extract_bing_empty_html_returns_empty():
    items = _extract_bing_items("<html><body>no results here</body></html>")
    assert items == []


def _provider() -> PlaywrightSearchProvider:
    # RETRIEVAL_PROVIDER=playwright so .enabled is True; the conftest autouse
    # fixture forces mock, so override just for this provider instance.
    from dataclasses import replace

    return PlaywrightSearchProvider(settings=replace(get_settings(), retrieval_provider="playwright"))


def _result(result_id: str, title: str, snippet: str = "", *, query: str = "京东造游轮") -> SearchResult:
    return SearchResult(
        case_id="real_search",
        query=query,
        result_id=result_id,
        title=title,
        url=f"https://news.example.com/{result_id}",
        source_name="news.example.com",
        published_at=None,
        snippet=snippet or title,
        source_tier="B",
    )


def test_search_prefers_baidu_when_it_returns_results(monkeypatch):
    # Baidu understands Chinese hot-topic phrases; Bing cn tokenizes them to a
    # single character. So Baidu must win and Bing must not even be called.
    p = _provider()
    bing_called = False

    def fake_baidu(q):
        return [_result("bd-1", "刘强东要造游艇了", "个人出资50亿造游艇")]

    def fake_bing(q):
        nonlocal bing_called
        bing_called = True
        return [_result("bing-1", "京（汉语文字）_百度百科", "京的释义")]

    monkeypatch.setattr(p, "_search_baidu", fake_baidu)
    monkeypatch.setattr(p, "_search_bing", fake_bing)

    results = p.search("京东造游轮")
    assert [r.result_id for r in results] == ["bd-1"]
    assert bing_called is False


def test_search_falls_back_to_bing_when_baidu_empty(monkeypatch):
    p = _provider()
    monkeypatch.setattr(p, "_search_baidu", lambda q: [])
    monkeypatch.setattr(
        p, "_search_bing", lambda q: [_result("bing-1", "京东造游轮 刘强东回应", "京东游艇项目")]
    )

    results = p.search("京东造游轮")
    assert [r.result_id for r in results] == ["bing-1"]


def test_tokenization_junk_is_dropped(monkeypatch):
    # The exact Bing cn failure: "京东造游轮" collapses to the single char 京, so
    # results are 京-the-character encyclopedia pages sharing only that one unit.
    p = _provider()
    junk = _result("junk", "京（汉语文字）_百度百科", "京的拼音、部首、笔顺")
    good = _result("good", "刘强东要造游艇了", "京东创始人个人出资50亿造游艇")
    monkeypatch.setattr(p, "_search_baidu", lambda q: [junk, good])

    results = p.search("京东造游轮")
    ids = [r.result_id for r in results]
    assert "good" in ids
    assert "junk" not in ids


def test_single_char_match_keeps_synonym_evidence(monkeypatch):
    # Rumor says 游轮, real coverage says 游艇 — a whole-word "游轮" filter would
    # wrongly drop the debunk. Single-char 游 + 京东 must keep it.
    p = _provider()
    good = _result("yacht", "刘强东要造游艇了", "京东出资造游艇")
    monkeypatch.setattr(p, "_search_baidu", lambda q: [good])

    results = p.search("京东造游轮")
    assert [r.result_id for r in results] == ["yacht"]


def test_junk_filter_keeps_original_when_all_filtered(monkeypatch):
    # If every result reads as junk, return the original set rather than nothing —
    # let the downstream relevance/provenance layers judge.
    p = _provider()
    only_junk = [
        _result("j1", "京（汉语文字）_百度百科", "京的释义"),
        _result("j2", "北京市_百度百科", "北京市概况"),
    ]
    monkeypatch.setattr(p, "_search_baidu", lambda q: only_junk)

    results = p.search("京东造游轮")
    assert [r.result_id for r in results] == ["j1", "j2"]


def test_short_query_skips_junk_filter(monkeypatch):
    # A query with < 2 topical units has nothing to cross-check against, so results
    # pass through untouched.
    p = _provider()
    passthrough = [_result("x", "任意标题", "任意内容", query="京")]
    monkeypatch.setattr(p, "_search_baidu", lambda q: passthrough)

    results = p.search("京")
    assert [r.result_id for r in results] == ["x"]

