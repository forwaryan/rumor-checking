from __future__ import annotations

import json

from backend.app.services.toutiao_search_provider import ToutiaoSearchProvider


def _script(data: dict) -> str:
    return f"<script>{json.dumps({'data': data}, ensure_ascii=False)}</script>"


TOUTIAO_HTML = "<html><body>" + "".join([
    _script({
        "title": "网传某地大地震系谣言 官方辟谣",
        "abstract": "经核实该消息不实，当地并无地震预警。",
        "source": "头条辟谣",
        "article_url": "https://www.toutiao.com/article/1",
        "datetime": "2026-07-20 08:00",
    }),
    _script({
        "title": "科普：关于食品添加剂的真相",
        "abstract": "适量使用的合规添加剂对健康无害。",
        "media_name": "科普中国",
        "url": "https://www.toutiao.com/article/2",
    }),
]) + "</body></html>"


def _provider() -> ToutiaoSearchProvider:
    return ToutiaoSearchProvider.__new__(ToutiaoSearchProvider)


def test_parse_results_extracts_items():
    results = _provider()._parse_results("地震谣言", TOUTIAO_HTML, max_results=10)
    assert len(results) == 2
    assert results[0].title.startswith("网传某地大地震")
    assert results[0].source_name == "头条辟谣"
    assert results[1].source_name == "科普中国"


def test_parse_results_respects_max_results():
    results = _provider()._parse_results("q", TOUTIAO_HTML, max_results=1)
    assert len(results) == 1


def test_null_fields_do_not_discard_whole_response():
    """A blob with an explicit null title must be skipped individually — NOT
    raise AttributeError and wipe out every subsequent valid result."""
    html = "<html>" + "".join([
        _script({"title": None, "abstract": None, "url": "https://x/nul"}),
        _script({
            "title": "有效标题",
            "abstract": "有效摘要文本。",
            "source": "光明网",
            "article_url": "https://www.toutiao.com/article/ok",
        }),
    ]) + "</html>"
    results = _provider()._parse_results("q", html, max_results=10)
    # The null-field blob is skipped; the valid one still comes through.
    assert len(results) == 1
    assert results[0].title == "有效标题"


def test_numeric_published_at_coerced_to_none():
    html = _script({
        "title": "标题",
        "abstract": "摘要。",
        "source": "环球网",
        "article_url": "https://www.toutiao.com/article/3",
        "datetime": 1706440243,  # epoch int, not a string
    })
    results = _provider()._parse_results("q", html, max_results=10)
    assert len(results) == 1
    assert results[0].published_at is None


def test_missing_url_skips_item():
    html = _script({"title": "标题", "abstract": "摘要。", "source": "x"})  # no url
    results = _provider()._parse_results("q", html, max_results=10)
    assert results == []


def test_malformed_json_blob_skipped():
    html = "<script>{not valid json}</script>" + _script({
        "title": "标题",
        "abstract": "摘要文本。",
        "source": "新华社",
        "article_url": "https://www.toutiao.com/article/4",
    })
    results = _provider()._parse_results("q", html, max_results=10)
    assert len(results) == 1


def test_result_ids_unique():
    results = _provider()._parse_results("q", TOUTIAO_HTML, max_results=10)
    ids = [r.result_id for r in results]
    assert len(ids) == len(set(ids))
