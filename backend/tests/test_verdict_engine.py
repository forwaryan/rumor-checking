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


# ---------------------------------------------------------------------------
# Quantitative conflict detection tests
# ---------------------------------------------------------------------------


def test_authoritative_quantitative_correction_refutes_exact_number():
    """An authoritative source explicitly correcting an exact number refutes it."""
    engine = VerdictEngine()
    event = NormalizedEvent(
        summary="拼多多在雄安招了6000人",
        keywords=["拼多多", "雄安"],
        input_type="text_news",
        raw_input="拼多多在雄安招了6000人",
    )
    claims = [ClaimItem(claim="拼多多在雄安招了6000人。", claim_type="fact")]
    evidence = [
        EvidenceItem(
            title="拼多多雄安研发中心招聘2000人",
            url="https://news.example.com/pdd-xiongan",
            source_name="财经日报",
            published_at="2026-03-10T10:00:00+08:00",
            snippet="拼多多雄安研发中心目前招聘规模为2000人，并非此前传闻数字。",
            relevance_reason="同一主题但数字不同。",
            source_tier="A",
        ),
    ]

    result = engine.evaluate(
        request=AnalyzeRequest(raw_input="拼多多在雄安招了6000人", input_type="text", mock_evidence=evidence),
        event=event,
        claims=claims,
    )

    claim_result = result[0][0]
    assert claim_result.verdict == "refuted"


def test_quantitative_conflict_ignores_subject_mismatched_source():
    """A number from a different subject must not manufacture a conflict.

    Regression: a '美团裁员50%' claim was flipped to 'conflicting' by a
    'Meta 裁员20%' article. The subject gate already drops that article as
    off-topic, so its 20% must never be weighed against the claim's 50%."""
    engine = VerdictEngine()
    event = NormalizedEvent(
        summary="美团最近裁员了50%的产品",
        keywords=["美团", "裁员"],
        input_type="text_news",
        raw_input="美团最近裁员了50%的产品",
    )
    claims = [ClaimItem(claim="美团最近裁员了50%的产品。", claim_type="fact")]
    evidence = [
        EvidenceItem(
            title="AI抢饭碗!Meta被曝拟裁员20%:1.58万人面临失业",
            url="https://www.163.com/dy/article/meta-layoff.html",
            source_name="www.163.com",
            published_at="2026-07-26T19:44:00+08:00",
            snippet="Meta被曝拟裁员20%，约1.58万人面临失业。",
            relevance_reason="",
            source_tier="B",
        ),
    ]

    result = engine.evaluate(
        request=AnalyzeRequest(raw_input="美团最近裁员了50%的产品", input_type="text", mock_evidence=evidence),
        event=event,
        claims=claims,
    )

    claim_result = result[0][0]
    assert claim_result.verdict == "insufficient"
    assert claim_result.verdict != "conflicting"


# ---------------------------------------------------------------------------
# Supported verdict with high-trust source tests
# ---------------------------------------------------------------------------


def test_supported_verdict_with_high_trust_source():
    """When evidence from a high-trust source (tier S/A) directly supports the
    claim, the verdict should be 'supported'."""
    engine = VerdictEngine()
    event = NormalizedEvent(
        summary="晨星生物裁员40%",
        keywords=["晨星生物", "裁员"],
        input_type="text_news",
        raw_input="晨星生物裁员40%",
    )
    claims = [ClaimItem(claim="晨星生物裁员40%。", claim_type="fact")]
    bundle = RetrievalBundle(
        query="晨星生物 裁员 40%",
        provider_name="kimi",
        canonical_results=(
            SearchResult(
                case_id="test",
                query="晨星生物 裁员 40%",
                result_id="r1",
                title="晨星生物宣布裁员40%",
                url="https://news.example.com/chenxing",
                source_name="财经日报",
                published_at="2026-03-12T10:00:00+08:00",
                snippet="晨星生物公司今日宣布裁员40%，涉及多个部门。",
                source_tier="S",
            ),
            SearchResult(
                case_id="test",
                query="晨星生物 裁员 40%",
                result_id="r2",
                title="晨星生物大规模裁员已证实",
                url="https://news.example.com/chenxing-2",
                source_name="人民网",
                published_at="2026-03-13T10:00:00+08:00",
                snippet="多家媒体证实晨星生物确实裁员40%，员工已收到通知。",
                source_tier="A",
            ),
        ),
    )

    result = engine.evaluate_with_source(
        request=AnalyzeRequest(raw_input="晨星生物裁员40%", input_type="text"),
        event=event,
        claims=claims,
        retrieval_bundle=bundle,
    )

    assert result.claim_results[0].verdict == "supported"
    assert result.claim_results[0].confidence in {"high", "medium"}


# ---------------------------------------------------------------------------
# Refuted verdict tests
# ---------------------------------------------------------------------------


def test_refuted_verdict_with_negation_evidence():
    """When high-trust evidence contains negation markers against the claim,
    the verdict should be 'refuted'."""
    engine = VerdictEngine()
    event = NormalizedEvent(
        summary="滨海地铁明天全线停运",
        keywords=["滨海地铁", "停运"],
        input_type="text_news",
        raw_input="滨海地铁明天全线停运",
    )
    claims = [ClaimItem(claim="滨海地铁明天全线停运。", claim_type="fact")]
    evidence = [
        EvidenceItem(
            title="滨海地铁辟谣全线停运传闻",
            url="https://metro.example.cn/notice",
            source_name="滨海地铁官方",
            published_at="2026-03-10T20:00:00+08:00",
            snippet="滨海地铁运营公司辟谣称全线停运系谣言，目前所有线路正常运行。",
            relevance_reason="官方辟谣。",
            source_tier="S",
        ),
    ]

    result = engine.evaluate(
        request=AnalyzeRequest(raw_input="滨海地铁明天全线停运", input_type="text", mock_evidence=evidence),
        event=event,
        claims=claims,
    )

    claim_result = result[0][0]
    assert claim_result.verdict == "refuted"
    assert claim_result.confidence in {"high", "medium"}


# ---------------------------------------------------------------------------
# Insufficient verdict (no matching evidence) tests
# ---------------------------------------------------------------------------


def test_insufficient_verdict_no_matching_evidence():
    """When no evidence matches the claim, the verdict should be 'insufficient'."""
    engine = VerdictEngine()
    event = NormalizedEvent(
        summary="某公司计划迁址西安",
        keywords=["某公司", "迁址"],
        input_type="text_news",
        raw_input="某公司计划迁址西安",
    )
    claims = [ClaimItem(claim="某公司计划迁址西安。", claim_type="fact")]
    # Evidence on a completely unrelated topic
    evidence = [
        EvidenceItem(
            title="上海房价最新数据",
            url="https://housing.example.com/data",
            source_name="住房数据中心",
            published_at="2026-03-01T08:00:00+08:00",
            snippet="2026年上海住宅均价小幅波动，整体平稳。",
            relevance_reason="不相关。",
            source_tier="A",
        ),
    ]

    result = engine.evaluate(
        request=AnalyzeRequest(raw_input="某公司计划迁址西安", input_type="text", mock_evidence=evidence),
        event=event,
        claims=claims,
    )

    claim_result = result[0][0]
    assert claim_result.verdict == "insufficient"


# ---------------------------------------------------------------------------
# coarse_truth_probability mapping tests
# ---------------------------------------------------------------------------


def test_coarse_truth_probability_supported_high():
    """supported/high should map to 90."""
    from backend.app.services.verdict_engine import coarse_truth_probability

    probability, basis = coarse_truth_probability("supported", "high")
    assert probability == 90.0
    assert basis == "evidence"


def test_coarse_truth_probability_refuted_high():
    """refuted/high should map to 10."""
    from backend.app.services.verdict_engine import coarse_truth_probability

    probability, basis = coarse_truth_probability("refuted", "high")
    assert probability == 10.0
    assert basis == "evidence"


def test_coarse_truth_probability_insufficient():
    """insufficient should map to 50 with prior basis."""
    from backend.app.services.verdict_engine import coarse_truth_probability

    probability, basis = coarse_truth_probability("insufficient", "low")
    assert probability == 50.0
    assert basis == "prior"


# ---------------------------------------------------------------------------
# Non-fact claims get insufficient with appropriate notes
# ---------------------------------------------------------------------------


def test_non_fact_claims_get_insufficient():
    """Opinion, prediction, and unverifiable claims should always get
    'insufficient' verdict with appropriate notes."""
    engine = VerdictEngine()
    event = NormalizedEvent(
        summary="某事件讨论",
        keywords=[],
        input_type="text_news",
        raw_input="某事件讨论",
    )

    test_cases = [
        ("opinion", "这次公司明显在甩锅。", "评价性说法"),
        ("prediction", "预计该公司明年会继续裁员。", "未来判断"),
        ("unverifiable", "据内部员工透露有问题。", "公开资料难以直接核验"),
    ]

    for claim_type, claim_text, expected_note_fragment in test_cases:
        claims = [ClaimItem(claim=claim_text, claim_type=claim_type)]
        bundle = RetrievalBundle(
            query="test",
            provider_name="kimi",
            canonical_results=(
                SearchResult(
                    case_id="test",
                    query="test",
                    result_id="r1",
                    title="相关报道",
                    url="https://example.com/article",
                    source_name="某新闻",
                    published_at="2026-03-10T10:00:00+08:00",
                    snippet="相关内容报道。",
                    source_tier="A",
                ),
            ),
        )

        result = engine.evaluate_with_source(
            request=AnalyzeRequest(raw_input="某事件讨论", input_type="text"),
            event=event,
            claims=claims,
            retrieval_bundle=bundle,
        )

        assert result.claim_results[0].verdict == "insufficient", f"Failed for {claim_type}"
        assert result.claim_results[0].confidence == "low", f"Failed for {claim_type}"
        assert expected_note_fragment in result.claim_results[0].notes, (
            f"Failed for {claim_type}: expected '{expected_note_fragment}' in '{result.claim_results[0].notes}'"
        )


# ---------------------------------------------------------------------------
# Time-sensitive recency ordering of surfaced evidence
# ---------------------------------------------------------------------------


def _supporting_item(*, title: str, published_at: str | None, tier: str = "A") -> EvidenceItem:
    return EvidenceItem(
        title=title,
        url=f"https://news.example.com/{title}",
        source_name="财经日报",
        published_at=published_at,
        snippet=title,
        relevance_reason="直接相关。",
        source_tier=tier,
    )


def _refuting_item(*, title: str, published_at: str, tier: str = "A") -> EvidenceItem:
    return EvidenceItem(
        title=title,
        url=f"https://factcheck.example.com/{title}",
        source_name="官方核查",
        published_at=published_at,
        snippet="官方辟谣称相关消息不实，线路正常运行。",
        relevance_reason="直接相关的否定证据。",
        source_tier=tier,
    )


def test_time_sensitive_claim_surfaces_newest_supporting_evidence_first():
    """A claim asserting a *current* state ('最新…') should reorder the surfaced
    evidence newest-first, so the top-2 shown reflect the latest reporting rather
    than retrieval order. Ordering only — the verdict is unaffected."""
    engine = VerdictEngine()
    # Deliberately out of chronological order; older item comes first in the pool.
    pool = [
        _supporting_item(title="晨星生物最新裁员40%", published_at="2026-03-01T10:00:00+08:00"),
        _supporting_item(title="晨星生物最新裁员40%", published_at="2026-03-20T10:00:00+08:00"),
        _supporting_item(title="晨星生物最新裁员40%", published_at="2026-03-10T10:00:00+08:00"),
    ]

    verdict, _confidence, _notes, selected = engine._evaluate_fact_claim(
        claim_text="晨星生物最新裁员40%。",
        evidence_pool=pool,
        subject_anchors=["晨星生物"],
    )

    assert verdict == "supported"
    surfaced_dates = [item.published_at for item in selected]
    assert surfaced_dates == [
        "2026-03-20T10:00:00+08:00",
        "2026-03-10T10:00:00+08:00",
    ]


def test_time_sensitive_claim_keeps_source_tier_ahead_of_recency():
    engine = VerdictEngine()
    pool = [
        _supporting_item(
            title="晨星生物最新裁员40%：权威旧报",
            published_at="2026-03-01T10:00:00+08:00",
            tier="A",
        ),
        _supporting_item(
            title="晨星生物最新裁员40%：较新转载",
            published_at="2026-03-20T10:00:00+08:00",
            tier="B",
        ),
        _supporting_item(
            title="晨星生物最新裁员40%：权威新报",
            published_at="2026-03-10T10:00:00+08:00",
            tier="A",
        ),
    ]

    verdict, _confidence, _notes, selected = engine._evaluate_fact_claim(
        claim_text="晨星生物最新裁员40%。",
        evidence_pool=pool,
        subject_anchors=["晨星生物"],
    )

    assert verdict == "supported"
    assert [(item.source_tier, item.published_at) for item in selected] == [
        ("A", "2026-03-10T10:00:00+08:00"),
        ("A", "2026-03-01T10:00:00+08:00"),
    ]


def test_time_sensitive_claim_handles_date_only_timezone_and_invalid_dates():
    engine = VerdictEngine()
    pool = [
        _supporting_item(title="晨星生物最新裁员40%：纯日期", published_at="2026-03-20"),
        _supporting_item(
            title="晨星生物最新裁员40%：跨时区",
            published_at="2026-03-19T17:00:00+00:00",
        ),
        _supporting_item(title="晨星生物最新裁员40%：日期无效", published_at="not-a-date"),
    ]

    verdict, confidence, _notes, selected = engine._evaluate_fact_claim(
        claim_text="晨星生物最新裁员40%。",
        evidence_pool=pool,
        subject_anchors=["晨星生物"],
    )

    assert (verdict, confidence) == ("supported", "high")
    assert [item.published_at for item in selected] == [
        "2026-03-19T17:00:00+00:00",
        "2026-03-20",
    ]


def test_time_sensitive_refuting_evidence_surfaces_newest_first():
    engine = VerdictEngine()
    pool = [
        _refuting_item(title="滨海地铁辟谣全线停运传闻：旧", published_at="2026-03-01T10:00:00+08:00"),
        _refuting_item(title="滨海地铁辟谣全线停运传闻：新", published_at="2026-03-20T10:00:00+08:00"),
        _refuting_item(title="滨海地铁辟谣全线停运传闻：中", published_at="2026-03-10T10:00:00+08:00"),
    ]

    verdict, confidence, _notes, selected = engine._evaluate_fact_claim(
        claim_text="滨海地铁目前已经全线停运。",
        evidence_pool=pool,
        subject_anchors=["滨海地铁"],
    )

    assert (verdict, confidence) == ("refuted", "high")
    assert [item.published_at for item in selected] == [
        "2026-03-20T10:00:00+08:00",
        "2026-03-10T10:00:00+08:00",
    ]


def test_time_sensitive_claim_preserves_order_when_rank_keys_match():
    engine = VerdictEngine()
    pool = [
        _supporting_item(title=f"晨星生物最新裁员40%：来源{index}", published_at="2026-03-20", tier="A")
        for index in range(3)
    ]

    verdict, confidence, _notes, selected = engine._evaluate_fact_claim(
        claim_text="晨星生物最新裁员40%。",
        evidence_pool=pool,
        subject_anchors=["晨星生物"],
    )

    assert (verdict, confidence) == ("supported", "high")
    assert [item.title for item in selected] == [
        "晨星生物最新裁员40%：来源0",
        "晨星生物最新裁员40%：来源1",
    ]


def test_non_time_sensitive_claim_preserves_retrieval_order():
    """Without a recency marker the stance list is left in retrieval order, so the
    recency sort does not silently reorder every claim's evidence."""
    engine = VerdictEngine()
    pool = [
        _supporting_item(title="晨星生物裁员40%", published_at="2026-03-01T10:00:00+08:00"),
        _supporting_item(title="晨星生物裁员40%", published_at="2026-03-20T10:00:00+08:00"),
    ]

    _verdict, _confidence, _notes, selected = engine._evaluate_fact_claim(
        claim_text="晨星生物裁员40%。",
        evidence_pool=pool,
        subject_anchors=["晨星生物"],
    )

    surfaced_dates = [item.published_at for item in selected]
    assert surfaced_dates == [
        "2026-03-01T10:00:00+08:00",
        "2026-03-20T10:00:00+08:00",
    ]


def test_incidental_date_number_does_not_create_quantitative_conflict():
    engine = VerdictEngine()
    pool = [
        EvidenceItem(
            title="美团回应裁员80%传言：不属实",
            url="https://news.example.com/meituan-response",
            source_name="财经日报",
            published_at="2026-12-03",
            snippet="针对裁员80%的消息，美团12月回应称该说法不实。",
            relevance_reason="直接回应传言。",
            source_tier="A",
        )
    ]

    verdict, confidence, _notes, _selected = engine._evaluate_fact_claim(
        claim_text="美团裁员80%",
        evidence_pool=pool,
        subject_anchors=["美团"],
    )

    assert (verdict, confidence) == ("refuted", "medium")


def test_refutation_phrases_reverse_positive_claim():
    engine = VerdictEngine()
    for phrase in ("物理上不可能", "实为气象气球", "并非该公司", "暂无相关安排"):
        evidence = EvidenceItem(
            title=f"官方核查：{phrase}",
            url=f"https://fact.example/{len(phrase)}",
            source_name="官方核查",
            published_at="2026-08-20",
            snippet=f"飞行滑板车传言{phrase}。",
            relevance_reason="直接核查。",
            source_tier="S",
        )
        verdict, confidence, _notes, _selected = engine._evaluate_fact_claim(
            claim_text="存在可载人飞行的滑板车",
            evidence_pool=[evidence],
            subject_anchors=[],
        )
        assert (verdict, confidence) == ("refuted", "high"), phrase


def test_explicit_new_policy_supersedes_old_supporting_policy():
    engine = VerdictEngine()
    pool = [
        EvidenceItem(
            title="海州市2024年购房资格政策",
            url="https://gov.example/old",
            source_name="海州市政府",
            published_at="2024-03-01",
            snippet="非本地户籍购房仍需购房资格。",
            relevance_reason="旧政策。",
            source_tier="S",
        ),
        EvidenceItem(
            title="海州市全面取消购房资格限制",
            url="https://gov.example/new",
            source_name="海州市政府",
            published_at="2026-08-01",
            snippet="自2026年8月1日起不再审核购房资格。",
            relevance_reason="新政策。",
            source_tier="S",
        ),
    ]

    verdict, confidence, _notes, selected = engine._evaluate_fact_claim(
        claim_text="海州市目前购房仍需要购房资格",
        evidence_pool=pool,
        subject_anchors=[],
    )

    assert (verdict, confidence) == ("refuted", "high")
    assert selected[0].url == "https://gov.example/new"


def test_current_state_claim_with_only_undated_evidence_is_insufficient():
    engine = VerdictEngine()
    pool = [
        EvidenceItem(
            title="青山市博物馆参观须知",
            url="https://museum.example/visit",
            source_name="青山市博物馆",
            published_at="",
            snippet="开放时间为周二至周日，周一闭馆。",
            relevance_reason="官网说明。",
            source_tier="S",
        )
    ]

    verdict, confidence, _notes, selected = engine._evaluate_fact_claim(
        claim_text="青山市博物馆目前每周一闭馆",
        evidence_pool=pool,
        subject_anchors=[],
    )

    assert (verdict, confidence) == ("insufficient", "low")
    assert selected == pool


def test_incidental_supersession_characters_do_not_override_conflict():
    engine = VerdictEngine()
    pool = [
        EvidenceItem(
            title="海州市政府否认仍需购房资格",
            url="https://gov.example/refute",
            source_name="海州市政府",
            published_at="2026-01-01",
            snippet="海州市政府否认目前仍需购房资格。",
            relevance_reason="直接否认。",
            source_tier="S",
        ),
        EvidenceItem(
            title="房企自称海州市仍需购房资格",
            url="https://news.example/support",
            source_name="财经日报",
            published_at="2026-02-01",
            snippet="一家房企自称海州市购房仍需资格。",
            relevance_reason="相反说法。",
            source_tier="S",
        ),
    ]

    verdict, _confidence, _notes, _selected = engine._evaluate_fact_claim(
        claim_text="海州市目前购房仍需要购房资格",
        evidence_pool=pool,
        subject_anchors=[],
    )

    assert verdict == "conflicting"


def test_equal_date_supersession_evidence_remains_conflicting():
    engine = VerdictEngine()
    pool = [
        _supporting_item(title="海州市目前仍需购房资格", published_at="2026-02-01", tier="S"),
        _refuting_item(title="海州市新规不再审核购房资格", published_at="2026-02-01", tier="S"),
    ]

    verdict, _confidence, _notes, _selected = engine._evaluate_fact_claim(
        claim_text="海州市目前仍需购房资格",
        evidence_pool=pool,
        subject_anchors=[],
    )

    assert verdict == "conflicting"


def test_non_time_sensitive_claim_accepts_undated_authoritative_evidence():
    engine = VerdictEngine()
    pool = [_supporting_item(title="水在标准大气压下沸点为100摄氏度", published_at="", tier="S")]

    verdict, confidence, _notes, _selected = engine._evaluate_fact_claim(
        claim_text="水在标准大气压下沸点为100摄氏度",
        evidence_pool=pool,
        subject_anchors=[],
    )

    assert (verdict, confidence) == ("supported", "high")


def test_entity_named_only_in_source_name_still_supports_claim():
    """Co-reference: the full entity name lives in source_name ('中国科学技术大学')
    while the body uses an abbreviation ('中科大'). The support classifier must see
    the source_name via anchor_context, or evidence lands in `relevant` and the
    claim collapses to insufficient despite an authoritative on-topic source."""
    engine = VerdictEngine()
    event = NormalizedEvent(
        summary="中国科学技术大学新增人工智能学院",
        input_type="text_news",
        raw_input="中国科学技术大学新增人工智能学院",
    )
    item = EvidenceItem(
        title="中科大成立人工智能学院",
        url="https://ustc.edu/ai",
        source_name="中国科学技术大学",
        published_at="2026-08-20",
        snippet="中科大正式成立人工智能学院，首批招生今年秋季启动。",
        relevance_reason="直接相关。",
        source_tier="S",
    )
    anchors = engine._subject_anchors_for_claim(
        claim_text="中国科学技术大学新增人工智能学院", event=event
    )
    verdict, _confidence, _notes, _selected = engine._evaluate_fact_claim(
        claim_text="中国科学技术大学新增人工智能学院",
        evidence_pool=[item],
        subject_anchors=anchors,
    )

    assert verdict == "supported"


def test_entity_action_claim_does_not_over_extract_whole_claim_as_anchor():
    """ENTITY_PATTERN must stop at the first entity suffix, not run greedily to the
    last. '中国科学技术大学新增人工智能学院' has two suffixes (大学, 学院); a greedy match
    collapsed the whole claim into one anchor that no evidence could satisfy."""
    from backend.app.services.entity_anchor import extract_subject_anchors

    anchors = extract_subject_anchors("中国科学技术大学新增人工智能学院")

    assert "中国科学技术大学" in anchors
    assert "中国科学技术大学新增人工智能学院" not in anchors
