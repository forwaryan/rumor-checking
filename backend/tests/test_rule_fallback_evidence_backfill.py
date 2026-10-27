"""Evidence selection keeps unrelated retrieval hits out of claim citations."""
from __future__ import annotations

from backend.app.models.schemas import AnalyzeRequest, ClaimItem, NormalizedEvent
from backend.app.services.retrieval_models import RetrievalBundle, SearchResult, build_independence_key
from backend.app.services.verdict_engine import VerdictEngine


def _hit(url: str, title: str) -> SearchResult:
    return SearchResult(
        case_id="test", query="q", result_id=url, title=title, url=url,
        source_name=url.split("//")[-1].split("/")[0],
        published_at="2026-07-29T09:00:00+08:00", snippet=title,
        source_tier="B", provider_name="test",
        independence_key=build_independence_key(url, ""),
    )


def test_end_to_end_keeps_unrelated_hits_out_of_claim_evidence():
    """Retrieved pages with no claim overlap remain navigation hints, not citations."""
    engine = VerdictEngine()
    bundle = RetrievalBundle(
        query="test query", matched_case_id="test",
        canonical_results=(
            _hit("https://a.example.com/one", "foo bar baz alpha"),
            _hit("https://b.example.com/two", "foo bar baz beta"),
            _hit("https://c.example.com/three", "foo bar baz gamma"),
        ),
        raw_results=(), provider_name="playwright",
    )
    verdict = engine.evaluate_with_source(
        request=AnalyzeRequest(raw_input="totally unrelated claim"),
        event=NormalizedEvent(
            title="disjoint", summary="disjoint",
            input_type="text_news", raw_input="disjoint",
        ),
        claims=[ClaimItem(claim="something quite different.", claim_type="fact")],
        retrieval_bundle=bundle,
    )
    main = verdict.claim_results[0]
    assert main.evidence == []
    assert main.verdict == "insufficient"
    assert "规则兜底" not in (main.notes or "")
