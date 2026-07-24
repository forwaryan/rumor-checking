from __future__ import annotations

from dataclasses import replace

from backend.app.core.config import _parse_model_base_urls, get_settings


def test_parse_model_base_urls_basic():
    parsed = _parse_model_base_urls("a=http://x/v2,b=http://y/v1")
    assert parsed == {"a": "http://x/v2", "b": "http://y/v1"}


def test_parse_model_base_urls_strips_trailing_slash_and_spaces():
    parsed = _parse_model_base_urls(" a = http://x/v2/ ")
    assert parsed == {"a": "http://x/v2"}


def test_parse_model_base_urls_skips_malformed_entries():
    # No '=', blank name, blank url — all dropped, valid ones kept.
    parsed = _parse_model_base_urls("noequals,=http://x,b=,c=http://z/v2")
    assert parsed == {"c": "http://z/v2"}


def test_parse_model_base_urls_empty():
    assert _parse_model_base_urls("") == {}
    assert _parse_model_base_urls(None) == {}


def test_base_url_for_model_uses_override_else_default():
    settings = replace(
        get_settings(),
        llm_base_url="http://gw/v1",
        llm_model_base_urls={"special": "http://gw/v2"},
    )
    assert settings.base_url_for_model("special") == "http://gw/v2"
    assert settings.base_url_for_model("ordinary") == "http://gw/v1"
    # Whitespace in the requested name is tolerated.
    assert settings.base_url_for_model(" special ") == "http://gw/v2"
