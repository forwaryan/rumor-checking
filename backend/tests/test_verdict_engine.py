from __future__ import annotations

from backend.app.models.schemas import AnalyzeRequest, ClaimItem, NormalizedEvent
from backend.app.services.retrieval_models import RetrievalBundle, SearchResult
from backend.app.services.verdict_engine import VerdictEngine


def _result(
    *,
    result_id: str,
    title: str,
    snippet: str,
    source_name: str,
    source_tier: str,
    published_at: str,
    url: str,
) -> SearchResult:
    return SearchResult(
        case_id="real_search",
        query="最近有个女网红脑出血死了真的假的",
        result_id=result_id,
        title=title,
        url=url,
        source_name=source_name,
        published_at=published_at,
        snippet=snippet,
        source_tier=source_tier,
    )


def test_supporting_report_with_sleep_duration_is_not_misclassified_as_refutation():
    engine = VerdictEngine()
    event = NormalizedEvent(
        summary="最近有个女网红脑出血死了真的假的",
        keywords=["女网红", "脑出血", "死亡"],
        input_type="question_only",
        raw_input="最近有个女网红脑出血死了真的假的？",
    )
    claims = [ClaimItem(claim="最近有个女网红脑出血死了真的假的。", claim_type="fact")]
    bundle = RetrievalBundle(
        query="最近有个女网红脑出血死了真的假的",
        matched_case_id="real_search",
        mode_hint="partial",
        provider_name="kimi",
        canonical_results=(
            _result(
                result_id="real-1",
                title="山西39岁网红“王炸姐”直播时突发脑干出血去世",
                snippet="极目新闻等媒体报道，王炸姐直播时突发剧烈头痛，送医后确认因脑干出血去世。",
                source_name="极目新闻",
                source_tier="A",
                published_at="2026-03-12T00:00:00+08:00",
                url="https://www.ctdsb.net/c1716_202603/2684118.html",
            ),
            _result(
                result_id="real-2",
                title="“王炸姐”葬礼举行 亲友证实其长期熬夜、曾出现头痛先兆",
                snippet="记者从葬礼现场获悉，她平日每天仅睡四五小时，医生提示长期熬夜易诱发脑出血。",
                source_name="光明网",
                source_tier="A",
                published_at="2026-03-13T00:00:00+08:00",
                url="https://www.gmw.cn/2026-03/13/content_1304373570.htm",
            ),
        ),
    )

    result = engine.evaluate_with_source(
        request=AnalyzeRequest(raw_input="最近有个女网红脑出血死了真的假的？", input_type="question"),
        event=event,
        claims=claims,
        retrieval_bundle=bundle,
    )

    assert result.claim_results[0].verdict == "supported"
    assert result.claim_results[0].confidence in {"medium", "high"}
