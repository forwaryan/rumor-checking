"""Tests for the rendered page fetch fallback path."""
from __future__ import annotations

from unittest.mock import patch

from backend.app.services.rendered_page_fetcher import _check_playwright, render_page


def test_render_page_returns_none_when_playwright_missing():
    with patch.dict("sys.modules", {"playwright": None, "playwright.sync_api": None}):
        import importlib

        import backend.app.services.rendered_page_fetcher as mod
        mod._PLAYWRIGHT_AVAILABLE = None  # reset cache
        result = mod.render_page("https://example.com")
        assert result is None


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
