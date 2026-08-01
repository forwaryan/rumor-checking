"""Rendered page fetcher: Playwright fallback for JS-rendered pages.

When the static httpx fetch returns partial/empty (client-rendered SPAs like
163.com), this module launches a headless browser, waits for content to render,
and returns the resulting HTML for the extractor to parse.

Playwright is an OPTIONAL dependency. If not installed, calling render_page()
gracefully returns None so the pipeline degrades to static-only without crashing.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from backend.app.services.url_validator import is_safe_url

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_PLAYWRIGHT_AVAILABLE: bool | None = None


def _check_playwright() -> bool:
    global _PLAYWRIGHT_AVAILABLE
    if _PLAYWRIGHT_AVAILABLE is not None:
        return _PLAYWRIGHT_AVAILABLE
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        _PLAYWRIGHT_AVAILABLE = True
    except ImportError:
        _PLAYWRIGHT_AVAILABLE = False
        logger.info("rendered_page_fetcher_disabled reason=playwright_not_installed")
    return _PLAYWRIGHT_AVAILABLE


def render_page(url: str, *, timeout_ms: int = 15000, wait_until: str = "networkidle") -> str | None:
    """Render a page with a headless browser and return its full HTML.

    Returns None if:
    - playwright is not installed
    - the URL is blocked by SSRF guard
    - any browser/network error occurs

    The browser context is ephemeral (no cookies/state persist).
    """
    if not is_safe_url(url):
        return None
    if not _check_playwright():
        return None

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    locale="zh-CN",
                )
                page = context.new_page()
                page.goto(url, wait_until=wait_until, timeout=timeout_ms)
                html = page.content()
                context.close()
                return html
            finally:
                browser.close()
    except Exception as exc:
        logger.warning("rendered_page_fetcher_error url=%s error=%s", url, exc)
        return None
