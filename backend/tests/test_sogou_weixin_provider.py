from __future__ import annotations

from backend.app.services.sogou_weixin_provider import SogouWeixinSearchProvider

SOGOU_WEIXIN_HTML = """
<html><body>
<ul class="news-list">
  <li id="sogou_vr_11002601_box_0">
    <div class="txt-box">
      <a href="/link?url=abc123" target="_blank">地震<em>谣言</em>不可信 官方辟谣</a>
      <a class="account">腾讯较真</a>
      <p class="txt-info">近日网传某地将发生大地震的消息纯属谣言，请勿传播。</p>
      <script>timeConvert('1706440243')</script>
    </div>
  </li>
  <li id="sogou_vr_11002601_box_1">
    <div class="txt-box">
      <a href="/link?url=def456" target="_blank">丁香医生：这些健康谣言不要信</a>
      <a class="account">丁香医生</a>
      <p class="txt-info">盘点本月十大健康类谣言，逐一澄清。</p>
      <script>timeConvert('1706500000')</script>
    </div>
  </li>
  <li id="sogou_vr_11002601_box_2">
    <div class="txt-box">
      <a href="https://mp.weixin.qq.com/s/xyz789" target="_blank">某自媒体文章标题</a>
      <a class="account">营销号A</a>
      <p class="txt-info">震惊！这个真相让人无法接受！</p>
    </div>
  </li>
</ul>
</body></html>
"""

EMPTY_HTML = "<html><body><div>no results</div></body></html>"


def test_parse_results_extracts_items():
    provider = SogouWeixinSearchProvider.__new__(SogouWeixinSearchProvider)
    results = provider._parse_results("地震谣言", SOGOU_WEIXIN_HTML, max_results=10)
    assert len(results) == 3


def test_parse_results_respects_max_results():
    provider = SogouWeixinSearchProvider.__new__(SogouWeixinSearchProvider)
    results = provider._parse_results("地震谣言", SOGOU_WEIXIN_HTML, max_results=2)
    assert len(results) == 2


def test_parse_results_extracts_url():
    provider = SogouWeixinSearchProvider.__new__(SogouWeixinSearchProvider)
    results = provider._parse_results("地震谣言", SOGOU_WEIXIN_HTML, max_results=10)
    assert results[0].url == "https://weixin.sogou.com/link?url=abc123"
    assert results[2].url == "https://mp.weixin.qq.com/s/xyz789"


def test_parse_results_extracts_account_as_source():
    provider = SogouWeixinSearchProvider.__new__(SogouWeixinSearchProvider)
    results = provider._parse_results("地震谣言", SOGOU_WEIXIN_HTML, max_results=10)
    assert results[0].source_name == "腾讯较真"
    assert results[1].source_name == "丁香医生"
    assert results[2].source_name == "营销号A"


def test_parse_results_extracts_snippet():
    provider = SogouWeixinSearchProvider.__new__(SogouWeixinSearchProvider)
    results = provider._parse_results("地震谣言", SOGOU_WEIXIN_HTML, max_results=10)
    assert "纯属谣言" in results[0].snippet


def test_parse_results_extracts_timestamp():
    provider = SogouWeixinSearchProvider.__new__(SogouWeixinSearchProvider)
    results = provider._parse_results("地震谣言", SOGOU_WEIXIN_HTML, max_results=10)
    assert results[0].published_at != ""
    assert "2024" in results[0].published_at
    assert results[2].published_at == ""


def test_classify_tier_high_trust():
    provider = SogouWeixinSearchProvider.__new__(SogouWeixinSearchProvider)
    results = provider._parse_results("地震谣言", SOGOU_WEIXIN_HTML, max_results=10)
    assert results[0].source_tier == "A"  # 腾讯较真
    assert results[1].source_tier == "A"  # 丁香医生


def test_classify_tier_default():
    provider = SogouWeixinSearchProvider.__new__(SogouWeixinSearchProvider)
    results = provider._parse_results("地震谣言", SOGOU_WEIXIN_HTML, max_results=10)
    # An unknown marketing account is social-tier C, NOT mainstream B — an
    # unverified WeChat post must not count as tier-B evidence.
    assert results[2].source_tier == "C"  # 营销号A


def test_classify_tier_ignores_trust_keywords_in_article_text():
    """Trust is a property of the account, not the article. A marketing account
    whose headline/snippet name-drops '官方'/'公安' must NOT be promoted to tier A."""
    provider = SogouWeixinSearchProvider.__new__(SogouWeixinSearchProvider)
    html = """
    <li id="sogou_vr_1_box_0">
      <a href="/link?url=x" target="_blank">公安部官方通报！新华社权威发布</a>
      <a class="account">震惊部小道消息</a>
      <p class="txt-info">据公安、政府、央视官方多方求证……</p>
    </li>
    """
    results = provider._parse_results("q", html, max_results=10)
    assert len(results) == 1
    # Account name carries no authority marker → C, despite the loud headline.
    assert results[0].source_tier == "C"


def test_classify_tier_promotes_authoritative_account():
    provider = SogouWeixinSearchProvider.__new__(SogouWeixinSearchProvider)
    html = """
    <li id="sogou_vr_1_box_0">
      <a href="/link?url=y" target="_blank">某地无地震预警</a>
      <a class="account">中国互联网联合辟谣平台</a>
      <p class="txt-info">经核实为不实信息。</p>
    </li>
    """
    results = provider._parse_results("q", html, max_results=10)
    assert results[0].source_tier == "A"


def test_empty_html_returns_empty_list():
    provider = SogouWeixinSearchProvider.__new__(SogouWeixinSearchProvider)
    results = provider._parse_results("地震谣言", EMPTY_HTML, max_results=10)
    assert results == []


def test_result_ids_unique():
    provider = SogouWeixinSearchProvider.__new__(SogouWeixinSearchProvider)
    results = provider._parse_results("地震谣言", SOGOU_WEIXIN_HTML, max_results=10)
    ids = [r.result_id for r in results]
    assert len(ids) == len(set(ids))
