from __future__ import annotations

from backend.app.models.schemas import AnalyzeRequest, ClaimItem, NormalizedEvent
from backend.app.services.claim_extractor import ClaimExtractor
from backend.app.services.input_normalizer import InputNormalizer
from backend.app.services.question_resolver import QuestionResolver
from backend.app.services.retrieval_models import RetrievalBundle, SearchResult


def _result(
    *,
    title: str,
    snippet: str,
    source_name: str = "晨星生物",
    source_tier: str = "S",
) -> SearchResult:
    return SearchResult(
        case_id="real_search",
        query="test query",
        result_id="r-1",
        title=title,
        url="https://example.com/story",
        source_name=source_name,
        published_at="2026-03-15T10:00:00+08:00",
        snippet=snippet,
        source_tier=source_tier,
    )


def test_claim_extractor_splits_compound_question_into_multiple_claims():
    extractor = ClaimExtractor()
    event = NormalizedEvent(
        summary="某女主播脑出血去世，平台还封锁消息是真是假",
        input_type="question_only",
        raw_input="某女主播脑出血去世，平台还封锁消息是真是假？",
    )

    claims = extractor.extract(
        event,
        provider_claims=[
            ClaimItem(claim="某女主播脑出血去世。", claim_type="fact"),
            ClaimItem(claim="平台封锁消息。", claim_type="fact"),
        ],
    )

    assert len(claims) >= 2
    assert any("脑出血去世" in item.claim for item in claims)
    assert any("平台封锁消息" in item.claim for item in claims)


def test_claim_extractor_refines_provider_claims_into_atomic_claims_and_query_hints():
    extractor = ClaimExtractor()
    event = NormalizedEvent(
        title="滨海地铁回应停运传闻",
        summary="滨海地铁运营公司称仅3号线夜间检修，其他线路正常运营。",
        keywords=["滨海地铁", "停运传闻", "3号线夜间检修"],
        source_name="滨海地铁运营公司",
        input_type="text_news",
        raw_input="【热搜截图】网传滨海地铁明天全线停运，运营公司深夜回应：仅3号线夜间检修，其他线路正常运营。",
    )

    extraction = extractor.extract_with_source(
        event,
        provider_claims=[
            ClaimItem(
                claim="网传滨海地铁明天全线停运，运营公司称仅3号线夜间检修，其余线路正常运营。",
                claim_type="fact",
            )
        ],
    )

    claim_texts = [item.claim for item in extraction.claims]
    assert "滨海地铁明天全线停运。" in claim_texts
    assert any("3号线夜间检修" in item for item in claim_texts)
    assert any("其余线路正常运营" in item for item in claim_texts)
    assert extraction.query_hints["滨海地铁明天全线停运。"]
    assert any("滨海地铁" in query for query in extraction.query_hints["滨海地铁明天全线停运。"])


def test_claim_extractor_marks_chatlog_and_emotional_extensions():
    extractor = ClaimExtractor()
    event = NormalizedEvent(
        title="北川中学停课传闻",
        summary="聊天记录称北川中学下周停课一个月，校方回应本周正常上课。",
        keywords=["北川中学", "停课", "聊天记录"],
        source_name="用户提供文本",
        input_type="text_news",
        raw_input="群聊聊天记录显示北川中学下周停课一个月，很多家长都收到通知，这次学校明显在隐瞒。",
    )

    extraction = extractor.extract_with_source(
        event,
        provider_claims=[
            ClaimItem(
                claim="聊天记录显示北川中学下周停课一个月，很多家长都收到通知，这次学校明显在隐瞒。",
                claim_type="fact",
            )
        ],
    )

    type_by_claim = {item.claim: item.claim_type for item in extraction.claims}
    assert any(claim_type == "unverifiable" for claim_type in type_by_claim.values())
    assert any(claim_type == "opinion" for claim_type in type_by_claim.values())
    assert any("北川中学下周停课一个月" in claim for claim in type_by_claim)


def test_input_normalizer_rewrites_noisy_summary_and_extracts_better_keywords():
    event = InputNormalizer().normalize(
        AnalyzeRequest(
            raw_input="【群聊截图】网传晨星生物本周裁员40%，聊天记录称多个部门已经收到通知，公司回应只是结构调整。",
            input_type="text",
        )
    )

    assert event.input_type == "text_news"
    assert event.summary.startswith("晨星生物本周裁员40%")
    assert "晨星生物" in event.keywords
    assert "裁员40%" in event.keywords


def test_question_resolver_builds_subject_anchored_follow_up_query():
    resolver = QuestionResolver()
    event = NormalizedEvent(
        summary="晨星生物裁员40%还要继续裁员是真是假",
        keywords=["晨星生物", "裁员40%"],
        input_type="question_only",
        raw_input="最近晨星生物裁员40%还要继续裁员是真的吗？",
    )
    bundle = RetrievalBundle(
        query="晨星生物 裁员",
        canonical_results=(
            _result(
                title="晨星生物回应裁员传闻：没有40%裁员计划",
                snippet="公司回应称不存在所谓40%裁员安排，目前仅做结构调整。",
            ),
        ),
    )

    resolution = resolver.resolve(event=event, retrieval_bundle=bundle)

    assert resolution.selected_result is not None
    assert resolution.follow_up_query is not None
    assert "晨星生物" in resolution.follow_up_query
    assert "裁员" in resolution.follow_up_query
    assert "40%" in resolution.follow_up_query
