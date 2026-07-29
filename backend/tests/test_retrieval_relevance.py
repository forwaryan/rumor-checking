"""Relevance-filter tests for RetrievalService.

Guards the dual "subject + event" filter added to _result_matches_query, which
drops aggregator hits that share only the verb of the query (a "美团 裁员" query
must not keep Amazon/Meta/辛选 layoff titles just because they mention 裁员).
"""
from __future__ import annotations

from backend.app.core.config import get_settings
from backend.app.services.retrieval_models import SearchResult
from backend.app.services.retrieval_service import RetrievalService


def _hit(
    query: str,
    title: str,
    snippet: str = "",
    *,
    source_name: str = "www.163.com",
    tier: str = "B",
    url: str | None = None,
) -> SearchResult:
    return SearchResult(
        case_id="relevance_test",
        query=query,
        result_id=f"r-{abs(hash((query, title))) % 100000}",
        title=title,
        url=url or f"https://example.com/{abs(hash(title)) % 100000}",
        source_name=source_name,
        published_at="",
        snippet=snippet,
        source_tier=tier,
    )


def _service() -> RetrievalService:
    return RetrievalService(settings=get_settings())


class TestSubjectRequired:
    """When the query names a brand subject, results must mention it."""

    def test_meituan_layoff_query_keeps_meituan_hits(self) -> None:
        svc = _service()
        query = "美团 产品 裁员 70%"
        assert svc._result_matches_query(_hit(query, "讲述:我被美团裁员的过程!_主管_工作_公司"))
        assert svc._result_matches_query(
            _hit(query, "普渡科技宣布裁员,近两年密集融资12亿,曾多次获腾讯、红杉、美团投资"),
        )
        assert svc._result_matches_query(
            _hit(query, "王兴:美团要减少登味,以后别叫我兴哥"),
        )

    def test_meituan_layoff_query_drops_amazon_meta_layoff_hits(self) -> None:
        svc = _service()
        query = "美团 产品 裁员 70%"
        # Amazon layoff aggregator title — shares the verb 裁员 but subject is Amazon.
        assert not svc._result_matches_query(
            _hit(query, "曝亚马逊5月又要裁1.4万人,比裁员更可怕的是「随机点名」"),
        )
        # Meta AI-layoff title — same problem.
        assert not svc._result_matches_query(
            _hit(query, "AI抢饭碗!Meta被曝拟裁员20%:1.58万人面临失业"),
        )
        # 辛选 layoff — subject not in the query.
        assert not svc._result_matches_query(
            _hit(query, "员工回应辛选裁员50%"),
        )
        # Wholly-unrelated brand.
        assert not svc._result_matches_query(
            _hit(query, "茅台涨价通报"),
        )

    def test_subject_may_appear_only_in_snippet(self) -> None:
        svc = _service()
        # Title doesn't say 美团 but the snippet does — should still keep it.
        assert svc._result_matches_query(
            _hit(
                "美团 产品 裁员 70%",
                title="快讯:一季度净亏损48.5亿元",
                snippet="美团一季度净亏损48.5亿元,魅族宣布接入鸿蒙但暂不包括手机产品",
            ),
        )

    def test_explicit_unrelated_marker_still_wins_over_subject_match(self) -> None:
        svc = _service()
        # Even if the subject brand appears, an "无关" black-list marker still rejects.
        assert not svc._result_matches_query(
            _hit(
                "美团 产品 裁员 70%",
                title="美团相关新闻",
                snippet="经核实此内容与本次事件无关。",
            ),
        )


class TestNoSubjectFallback:
    """Queries without a brand subject fall back to event-term matching."""

    def test_open_question_query_uses_event_terms(self) -> None:
        svc = _service()
        # Query has no brand from _SUBJECT_BRANDS — falls back to event tokens ("裁员", "50%")
        query = "网传某科技公司 裁员 50%"
        assert svc._result_matches_query(
            _hit(query, "某AI科技公司启动裁员计划,涉及研发岗"),
        )
        # Result mentions neither 裁员 nor 50% nor any event token — off-topic.
        assert not svc._result_matches_query(
            _hit(query, "咖啡店的新品测评"),
        )

    def test_query_with_only_scaffolding_words_keeps_everything(self) -> None:
        svc = _service()
        # After stripping generic + stopwords, no event token remains — pre-existing
        # accept-all behavior should hold so we don't drop hits for an empty filter.
        query = "官方 回应 通报 说明"
        assert svc._result_matches_query(_hit(query, "任意标题"))

    def test_english_event_terms_match_case_insensitively(self) -> None:
        svc = _service()
        # Regression: _result_matches_query used to do a case-SENSITIVE membership
        # check for event tokens. An "OpenAI Layoffs" query yielded event_terms
        # ["OpenAI", "Layoffs"] and rejected a "openai layoffs latest update"
        # title because "OpenAI" isn't literally in the lowercased text.
        query = "OpenAI Layoffs 2026"
        assert svc._result_matches_query(
            _hit(query, "openai layoffs latest update"),
        )
        assert svc._result_matches_query(
            _hit(query, "OPENAI ANNOUNCES LAYOFFS"),
        )
        # Still rejects a genuinely off-topic hit.
        assert not svc._result_matches_query(
            _hit(query, "microsoft earnings beat expectations"),
        )


class TestBrandSubstringNotFalseMatch:
    """A brand string embedded inside a longer CJK compound must NOT activate
    the subject gate — the compound is the real subject, not the brand."""

    def test_alishan_place_query_does_not_activate_alibaba_gate(self) -> None:
        svc = _service()
        # "阿里山" is a place; "阿里" (Alibaba) is a substring but not the subject.
        # _SUBJECT_BRANDS spells "阿里巴巴" specifically to keep this safe.
        query = "阿里山 小火车 事故"
        assert svc._query_subject_tokens(query) == []
        # An on-topic hit that never says "阿里" (just talks about the accident) —
        # must be kept via event-term fallback (小火车 / 事故).
        assert svc._result_matches_query(
            _hit(query, "台湾小火车翻覆事故 多人受伤"),
        )

    def test_alibaba_brand_still_activates_subject_gate(self) -> None:
        svc = _service()
        # Guardrail: the unambiguous brand name must still trigger the gate,
        # even when concatenated with an event verb ("阿里巴巴集团裁员").
        assert svc._query_subject_tokens("阿里巴巴 集团 裁员") == ["阿里巴巴"]
        assert svc._query_subject_tokens("阿里巴巴集团裁员") == ["阿里巴巴"]

    def test_concatenated_brand_prefix_still_activates_gate(self) -> None:
        svc = _service()
        # Users often submit raw un-tokenized queries where the brand is glued
        # to the event ("拼多多雄安新区招聘"). The chunk regex produces ONE
        # merged CJK block, and the prefix rule catches it. If this broke,
        # every un-tokenized rumor query would silently fall back to
        # event-term matching and let unrelated aggregator hits through.
        assert svc._query_subject_tokens("拼多多雄安新区招聘信息") == ["拼多多"]
        assert svc._query_subject_tokens("美团产品裁员70%") == ["美团"]

    def test_real_brand_still_activates_subject_gate(self) -> None:
        svc = _service()
        # Guardrail for tokenized queries: brand as its own chunk must activate.
        assert svc._query_subject_tokens("美团 产品 裁员 70%") == ["美团"]


class TestBaiduPlaceholderNoise:
    """Baidu SERPs return two kinds of placeholder junk that must never
    reach the synthesis stage: (1) image search vertical cards and (2) a
    "no results" placeholder whose title just echoes the query and ends
    with "的最新相关信息". Real case: 2026-07-29 "京东要造游艇" run.
    """

    def test_baidu_image_vertical_card_is_noise(self) -> None:
        svc = _service()
        # Title suffix "- 百度图片" + host image.baidu.com — either alone drops it.
        hit = _hit(
            "刘强东 游艇",
            "刘强东 50 游艇 Sea Expandary 广州 - 百度图片",
            url="https://image.baidu.com/search/index?tn=baiduimage&word=刘强东",
        )
        assert svc._is_noise_result(hit)

    def test_baidu_image_title_alone_is_noise(self) -> None:
        svc = _service()
        # Some baidu image cards get rewritten hosts by _resolve_baidu_redirect;
        # the "- 百度图片" title suffix still identifies them.
        hit = _hit(
            "刘强东 游艇",
            "刘强东 - 百度图片",
            url="https://example.com/some-redirected-image-page",
        )
        assert svc._is_noise_result(hit)

    def test_baidu_no_result_placeholder_is_noise(self) -> None:
        svc = _service()
        # The title Baidu emits when the exact query has zero indexed items:
        # it just repeats the query + "的最新相关信息". Real observed title
        # from the "刘强东 造游艇 京东集团 官方 回应" run.
        hit = _hit(
            "刘强东 Sea Expandary 游艇 官方公告 京东集团 官方 回应",
            "刘强东 Sea Expandary 游艇 官方公告 京东集团 官方 回应的最新相关信息",
            url="https://wappass.baidu.com/static/captcha/tuxing.html",
        )
        assert svc._is_noise_result(hit)

    def test_wappass_captcha_host_is_noise(self) -> None:
        svc = _service()
        # Any wappass.baidu.com URL is a captcha/challenge page — no content.
        hit = _hit(
            "任意 query",
            "任意标题不含 placeholder marker",
            url="https://wappass.baidu.com/static/captcha/tuxing.html",
        )
        assert svc._is_noise_result(hit)

    def test_organic_news_with_latest_news_wording_still_kept(self) -> None:
        svc = _service()
        # Regression guard: organic news titles often say "最新消息" — that
        # phrase must NOT trigger the placeholder filter (which keys on the
        # more specific "的最新相关信息").
        hit = _hit(
            "京东 游艇 声明",
            "京东回应造游艇传闻:纯属子虚乌有 最新消息",
            url="https://www.sohu.com/a/12345.html",
        )
        assert not svc._is_noise_result(hit)

