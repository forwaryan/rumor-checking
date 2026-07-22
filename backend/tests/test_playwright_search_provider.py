from __future__ import annotations

from backend.app.services.playwright_search_provider import (
    _extract_baidu_items,
    _extract_bing_items,
    _clean_text,
)


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
