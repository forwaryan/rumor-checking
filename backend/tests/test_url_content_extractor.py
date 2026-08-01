from __future__ import annotations

from backend.app.services.url_content_extractor import UrlContentExtractor

ex = UrlContentExtractor()


def _extract(html: str):
    return ex._extract_from_html(
        html=html, final_url="https://example.com/a", content_type="text/html",
        fallback_source_name="example.com",
    )


def test_nav_chrome_is_not_treated_as_article_body():
    # Regression: 163.com renders its body via JS, leaving only the nav menu in
    # static HTML. Block extraction picked up the menu and a length check labeled
    # it a valid body — polluting downstream synthesis/correction with chrome like
    # "网易首页 应用 网易新闻 … 体育 NBA CBA". Nav chrome must be rejected as body.
    html = (
        '<html><head><title>乒协主席王励勤回应樊振东回归国家队情况，表示已经在联系过程中</title>'
        '<meta name="description" content="乒协主席王励勤回应樊振东回归国家队情况，表示已经在联系过程中"/>'
        '</head><body>'
        '<div>网易首页 应用 网易新闻 网易公开课 网易红彩 网易严选 邮箱大师 网易云课堂 '
        '快速导航 新闻 国内 国际 王三三 体育 NBA CBA 综合 中超 国际足球 英超 西甲 意甲 '
        '娱乐 明星 电影 电视 音乐 财经 股票 汽车 购车 车型库</div>'
        '</body></html>'
    )
    result = _extract(html)
    assert "网易首页" not in (result.body or "")
    assert "NBA" not in (result.body or "")
    # Body-less page must not masquerade as a fully-extracted article.
    assert result.status != "ok"
    # The decisive sentence still survives via the meta description snippet.
    assert "在联系过程中" in (result.snippet or "")


def test_prose_body_with_sentence_punctuation_survives():
    # The guard keys off sentence terminators (。！？); real prose must pass through
    # extraction untouched (status depends only on length, not on the nav guard).
    html = (
        '<html><head><title>樊振东是否回归国家队？王励勤最新回应</title></head><body>'
        '<article><p>据白鹿视频，乒协主席王励勤回应樊振东回归国家队情况，称目前还在联系的过程当中。</p>'
        '<p>此前据四川观察消息，萨尔布吕肯俱乐部经理回应樊振东是否将续约，称一切都有可能。</p>'
        '</article></body></html>'
    )
    result = _extract(html)
    assert "还在联系的过程当中" in (result.body or "")
    assert "一切都有可能" in (result.body or "")


def test_looks_like_nav_chrome_thresholds():
    f = ex._looks_like_nav_chrome
    assert f("网易首页 应用 网易新闻 国内 国际 体育 娱乐 财经 汽车 科技") is True
    # Prose (has terminator, few spaces) is never nav.
    assert f("乒协主席王励勤回应樊振东回归国家队情况，称目前还在联系的过程当中。") is False
    # A short space-separated headline is not enough tokens to be nav.
    assert f("樊振东 回归 国家队") is False
