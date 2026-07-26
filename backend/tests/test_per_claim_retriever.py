from __future__ import annotations

from backend.app.models.schemas import ClaimItem, NormalizedEvent
from backend.app.services.per_claim_retriever import _build_focused_query, _claim_needs_retrieval
from backend.app.services.retrieval_models import RetrievalBundle, SearchResult


def _make_bundle(evidence_grade: str = "D") -> RetrievalBundle:
    """Create a minimal RetrievalBundle for testing."""
    return RetrievalBundle(
        query="test query",
        provider_name="mock",
        canonical_results=(),
    )


# ---------------------------------------------------------------------------
# _build_focused_query tests
# ---------------------------------------------------------------------------


def test_build_focused_query_with_numbers():
    """When the claim contains numbers, _build_focused_query should produce a
    number-verification query extracting subject + place + numbers."""
    query = _build_focused_query("拼多多在雄安买了5栋楼")

    # Should extract subject "拼多多", place "雄安", and number "5栋"
    assert "拼多多" in query
    assert "雄安" in query
    assert "5栋" in query


def test_build_focused_query_with_numbers_multiple():
    """When claim has multiple numbers, all relevant terms are kept."""
    query = _build_focused_query("拼多多在雄安买了5栋楼招了6000人")

    assert "拼多多" in query
    assert "雄安" in query
    # At least one number should appear
    assert "5栋" in query or "6000人" in query


def test_build_focused_query_without_numbers():
    """Without numbers, filler words are stripped but entities/actions kept."""
    query = _build_focused_query("据称滨海地铁可能全线停运")

    # Filler words like "据称" and "可能" should be stripped
    assert "据称" not in query
    assert "可能" not in query
    # Entity and action words should be preserved
    assert "滨海地铁" in query
    assert "全线停运" in query


def test_build_focused_query_strips_question_filler():
    """Question-style filler like '是不是' and '有没有' should be stripped."""
    query = _build_focused_query("是不是有人说北川中学即将停课")

    assert "是不是" not in query
    assert "有人说" not in query
    assert "即将" not in query
    # Core content preserved
    assert "北川中学" in query
    assert "停课" in query


def test_build_focused_query_short_input_preserved():
    """If after stripping the result is too short (< 6 chars), the original
    claim text is used as the query."""
    query = _build_focused_query("据说是真的")

    # After stripping "据说" the remainder is too short, so original text is used
    assert len(query) >= 5


# ---------------------------------------------------------------------------
# _claim_needs_retrieval tests
# ---------------------------------------------------------------------------


def test_claim_needs_retrieval_fact_type():
    """Only fact-type claims should return True for needing retrieval."""
    bundle = _make_bundle()

    fact_claim = ClaimItem(claim="拼多多在雄安买了5栋楼。", claim_type="fact")
    assert _claim_needs_retrieval(fact_claim, bundle) is True


def test_claim_needs_retrieval_opinion_type():
    """Opinion-type claims should NOT need retrieval."""
    bundle = _make_bundle()

    opinion_claim = ClaimItem(claim="公司明显在甩锅。", claim_type="opinion")
    assert _claim_needs_retrieval(opinion_claim, bundle) is False


def test_claim_needs_retrieval_prediction_type():
    """Prediction-type claims should NOT need retrieval."""
    bundle = _make_bundle()

    prediction_claim = ClaimItem(claim="预计明年会继续裁员。", claim_type="prediction")
    assert _claim_needs_retrieval(prediction_claim, bundle) is False


def test_claim_needs_retrieval_unverifiable_type():
    """Unverifiable-type claims should NOT need retrieval."""
    bundle = _make_bundle()

    unverifiable_claim = ClaimItem(claim="据内部员工透露有问题。", claim_type="unverifiable")
    assert _claim_needs_retrieval(unverifiable_claim, bundle) is False


# ---------------------------------------------------------------------------
# enrich_retrieval_for_claims tests
# ---------------------------------------------------------------------------


def test_enrich_retrieval_skips_when_no_fact_claims(monkeypatch):
    """enrich_retrieval_for_claims should return the original bundle unchanged
    when there are no fact-type claims to enrich."""
    from backend.app.services.per_claim_retriever import enrich_retrieval_for_claims

    # Suppress progress emissions in tests
    monkeypatch.setattr("backend.app.services.per_claim_retriever.emit_stage", lambda **kwargs: None)
    monkeypatch.setattr("backend.app.services.per_claim_retriever.emit_log", lambda **kwargs: None)

    bundle = RetrievalBundle(
        query="test query",
        provider_name="mock",
        canonical_results=(
            SearchResult(
                case_id="test",
                query="test",
                result_id="r1",
                title="Existing result",
                url="https://example.com/article",
                source_name="News",
                published_at="2026-03-10T10:00:00+08:00",
                snippet="Some content.",
                source_tier="A",
            ),
        ),
    )

    claims = [
        ClaimItem(claim="公司明显在甩锅。", claim_type="opinion"),
        ClaimItem(claim="预计明年会继续裁员。", claim_type="prediction"),
    ]

    event = NormalizedEvent(
        summary="某事件讨论",
        input_type="text_news",
        raw_input="某事件讨论",
    )

    # retrieval_service is not called when there are no fact claims,
    # so we can pass a dummy object
    class DummyRetrievalService:
        pass

    result = enrich_retrieval_for_claims(
        claims=claims,
        retrieval_bundle=bundle,
        retrieval_service=DummyRetrievalService(),
        resolved_event=event,
    )

    # Should return the original bundle unchanged
    assert result is bundle
