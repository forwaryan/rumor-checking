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


def _fact(text):
    return ClaimItem(claim=text, claim_type="fact")


def _sr(result_id, source="News"):
    return SearchResult(
        case_id="c", query="q", result_id=result_id, title=f"t-{result_id}",
        url=f"https://example.com/{result_id}", source_name=source,
        published_at="2026-03-10T10:00:00+08:00", snippet="s", source_tier="A",
    )


def _base_bundle():
    return RetrievalBundle(query="q", provider_name="live", canonical_results=(_sr("r0"),))


def _event():
    return NormalizedEvent(summary="e", input_type="text_news", raw_input="e")


def test_per_claim_search_runs_concurrently_and_merges_in_order(monkeypatch):
    import threading
    import time

    from backend.app.services import per_claim_retriever as mod

    monkeypatch.setattr(mod, "emit_stage", lambda **k: None)
    monkeypatch.setattr(mod, "emit_log", lambda **k: None)

    active = {"now": 0, "max": 0}
    lock = threading.Lock()
    counter = {"n": 0}

    class SlowService:
        def retrieve_for_event(self, event, request_context):
            with lock:
                active["now"] += 1
                active["max"] = max(active["max"], active["now"])
                counter["n"] += 1
                tag = counter["n"]
            time.sleep(0.05)
            with lock:
                active["now"] -= 1
            # A uniquely-identified hit per call so the deduped merge keeps all of them.
            return RetrievalBundle(query="q", provider_name="live", canonical_results=(_sr(f"hit-{tag}"),))

    claims = [_fact("拼多多在雄安买了5栋楼"), _fact("拼多多在雄安招了6000人"), _fact("拼多多迁总部到雄安")]
    result = mod.enrich_retrieval_for_claims(
        claims=claims, retrieval_bundle=_base_bundle(),
        retrieval_service=SlowService(), resolved_event=_event(),
    )
    # If the three queries ran serially, max concurrency would be 1.
    assert active["max"] >= 2, "per-claim queries did not run concurrently"
    # The original result plus the three new hits, merged.
    assert len(result.canonical_results) == 4


def test_per_claim_search_degrades_when_one_query_fails(monkeypatch):
    from backend.app.services import per_claim_retriever as mod

    monkeypatch.setattr(mod, "emit_stage", lambda **k: None)
    monkeypatch.setattr(mod, "emit_log", lambda **k: None)

    class FlakyService:
        def retrieve_for_event(self, event, request_context):
            q = request_context["force_retrieval_query"]
            if "6000" in q:
                raise RuntimeError("network boom")
            return RetrievalBundle(query=q, provider_name="live", canonical_results=(_sr(f"ok-{q[:4]}"),))

    claims = [_fact("拼多多在雄安买了5栋楼"), _fact("拼多多在雄安招了6000人")]
    result = mod.enrich_retrieval_for_claims(
        claims=claims, retrieval_bundle=_base_bundle(),
        retrieval_service=FlakyService(), resolved_event=_event(),
    )
    # The failing query is skipped; the surviving one still merges in.
    assert len(result.canonical_results) == 2
