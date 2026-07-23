from __future__ import annotations

from backend.app.models.schemas import AnalyzeRequest, ClaimItem, EvidenceItem, NormalizedEvent
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
    assert "复核依据：" in result.claim_results[0].notes


def test_named_claim_with_subject_mismatch_evidence_stays_insufficient():
    engine = VerdictEngine()
    event = NormalizedEvent(
        title="晨星生物回应裁员传闻",
        summary="市场出现晨星生物裁员40%的传闻。",
        keywords=["晨星生物", "裁员40%"],
        input_type="text_news",
        raw_input="晨星生物裁员40%是真的吗？",
    )
    claims = [ClaimItem(claim="晨星生物已经宣布裁员40%。", claim_type="fact")]
    evidence = [
        EvidenceItem(
            title="另一家公司回应裁员传闻",
            url="https://finance.example.com/other-company",
            source_name="财经周刊",
            published_at="2026-03-11T10:00:00+08:00",
            snippet="报道未确认与用户提问的是同一家公司，主体不一致。",
            relevance_reason="标题与裁员话题接近，但主体不一致。",
            source_tier="A",
        )
    ]

    result = engine.evaluate(
        request=AnalyzeRequest(raw_input="晨星生物裁员40%是真的吗？", input_type="text", mock_evidence=evidence),
        event=event,
        claims=claims,
    )

    claim_result = result[0][0]
    assert claim_result.verdict == "insufficient"
    assert claim_result.evidence == []


def test_resolution_claim_with_unresolved_signals_returns_conflicting():
    engine = VerdictEngine()
    event = NormalizedEvent(
        title="北城区化工厂异味事件",
        summary="居民投诉夜间异味，生态环境局已进场核查。",
        keywords=["北城区化工厂", "异味", "核查"],
        input_type="text_news",
        raw_input="北城区化工厂异味问题已经彻底解决。",
    )
    claims = [ClaimItem(claim="北城区化工厂异味问题已经彻底解决。", claim_type="fact")]
    evidence = [
        EvidenceItem(
            title="区生态环境局通报已进场核查化工厂异味问题",
            url="https://env.example.cn/check-1",
            source_name="区生态环境局",
            published_at="2026-03-03T10:00:00+08:00",
            snippet="区生态环境局称已进场核查，后续将继续跟进异味投诉。",
            relevance_reason="官方信息表明事件仍在核查阶段。",
            source_tier="S",
        ),
        EvidenceItem(
            title="居民仍称夜间可以闻到刺激性异味",
            url="https://local.example.cn/smell-1",
            source_name="本地新闻",
            published_at="2026-03-05T08:00:00+08:00",
            snippet="多位居民表示异味持续，暂未看到完全恢复的公开结论。",
            relevance_reason="现场投诉显示问题尚未收口。",
            source_tier="A",
        ),
    ]

    result = engine.evaluate(
        request=AnalyzeRequest(raw_input="北城区化工厂异味问题已经彻底解决。", input_type="text", mock_evidence=evidence),
        event=event,
        claims=claims,
    )

    claim_result = result[0][0]
    assert claim_result.verdict == "conflicting"
    assert claim_result.confidence == "medium"
    assert "未收口信号" in claim_result.notes


def _empty_live_bundle(provider_name: str = "kimi") -> RetrievalBundle:
    return RetrievalBundle(
        query="拼多多雄安买楼招5000研发",
        matched_case_id="real_search",
        mode_hint="safe",
        provider_name=provider_name,
        canonical_results=(),
    )


def test_empty_evidence_after_live_search_says_searched_but_not_found():
    # After P0 drops navigational junk, a live search can legitimately yield zero
    # evidence. The note must own that we searched and found nothing — not imply the
    # input was thin.
    engine = VerdictEngine()
    event = NormalizedEvent(
        summary="拼多多在雄安买了三栋楼招了5000研发人员",
        keywords=[],
        input_type="text_news",
        raw_input="拼多多在雄安买了三栋楼招了5000研发人员",
    )
    claims = [ClaimItem(claim="拼多多在雄安买了三栋楼招了5000研发人员。", claim_type="fact")]

    result = engine.evaluate_with_source(
        request=AnalyzeRequest(raw_input="拼多多在雄安买了三栋楼招了5000研发人员", input_type="text"),
        event=event,
        claims=claims,
        retrieval_bundle=_empty_live_bundle(),
    )

    claim_result = result.claim_results[0]
    assert claim_result.verdict == "insufficient"
    assert "已联网检索" in claim_result.notes
    assert "未找到" in claim_result.notes


def test_empty_evidence_without_live_search_keeps_generic_note():
    # No bundle (or mock/off provider) means we never really searched — the honest
    # "已联网检索" wording would be a lie, so keep the generic conservative note.
    engine = VerdictEngine()
    event = NormalizedEvent(
        summary="拼多多在雄安买了三栋楼招了5000研发人员",
        keywords=[],
        input_type="text_news",
        raw_input="拼多多在雄安买了三栋楼招了5000研发人员",
    )
    claims = [ClaimItem(claim="拼多多在雄安买了三栋楼招了5000研发人员。", claim_type="fact")]

    for bundle in (None, _empty_live_bundle(provider_name="mock")):
        result = engine.evaluate_with_source(
            request=AnalyzeRequest(raw_input="拼多多在雄安买了三栋楼招了5000研发人员", input_type="text"),
            event=event,
            claims=claims,
            retrieval_bundle=bundle,
        )
        claim_result = result.claim_results[0]
        assert claim_result.verdict == "insufficient"
        assert "已联网检索" not in claim_result.notes
        assert "缺少可核验的证据链" in claim_result.notes
