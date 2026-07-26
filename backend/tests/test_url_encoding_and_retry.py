from __future__ import annotations

from dataclasses import replace

import httpx

from backend.app.core.config import get_settings
from backend.app.services.agent_reasoner import LlmAgentReasoner
from backend.app.services.url_content_extractor import UrlContentExtractor

_ZH = "拼多多雄安公司员工数量超600人，成为新区最大互联网民营企业"
_PAGE = f'<html><head><meta charset="{{cs}}"><title>{_ZH}</title></head><body><p>{_ZH}</p></body></html>'


def _resp(body: bytes, content_type: str) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": content_type}, content=body)


def test_decodes_gbk_page_without_http_charset():
    # The chinanews failure: GBK body, charset only in <meta>, no HTTP header charset.
    # httpx's .text would default to UTF-8 and produce mojibake.
    ex = UrlContentExtractor()
    body = _PAGE.format(cs="gbk").encode("gb18030")
    decoded = ex._decode_response(_resp(body, "text/html"))
    assert _ZH in decoded
    assert "�" not in decoded and "ƴ" not in decoded


def test_decodes_gb2312_alias():
    ex = UrlContentExtractor()
    body = _PAGE.format(cs="gb2312").encode("gb18030")
    decoded = ex._decode_response(_resp(body, "text/html"))
    assert _ZH in decoded


def test_http_header_charset_takes_precedence():
    ex = UrlContentExtractor()
    body = _PAGE.format(cs="utf-8").encode("utf-8")
    decoded = ex._decode_response(_resp(body, "text/html; charset=utf-8"))
    assert _ZH in decoded


def test_utf8_page_still_decodes():
    ex = UrlContentExtractor()
    body = _PAGE.format(cs="utf-8").encode("utf-8")
    decoded = ex._decode_response(_resp(body, "text/html"))
    assert _ZH in decoded


def _reasoner() -> LlmAgentReasoner:
    return LlmAgentReasoner(settings=replace(get_settings(), analysis_provider="kimi", llm_api_key="k"))


def test_planner_validator_rejects_truncated_response():
    # A truncated planner response (cut before the decision field closes) must fail
    # validation so _request_completion retries instead of silently giving up.
    r = _reasoner()
    check = r._json_with_key_usable("should_continue")
    assert check('{ "should_continue": true, "follow_up_query": "x", "reason": "cut off') is False
    assert check('{ "should_continue": false, "reason": "done" }') is True


def test_next_action_validator_requires_key():
    r = _reasoner()
    check = r._json_with_key_usable("next_action")
    assert check('{ "next_action": "synthesize", "reason": "ok" }') is True
    assert check('{ "reason": "no action field') is False
