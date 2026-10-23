import json
from dataclasses import replace

import pytest

from backend.app.core.config import get_settings
from backend.app.models.schemas import AnalyzeRequest, NormalizedEvent
from backend.app.services.agent_reasoner import (
    CLAIMS_ONLY_SYSTEM_PROMPT,
    SYNTHESIS_CRITIC_SYSTEM_PROMPT,
    LlmAgentReasoner,
)
from backend.app.services.retrieval_models import RetrievalBundle, SearchResult
from backend.app.services.run_control import RunControl, RunStopped, reset_run_control, set_run_control


@pytest.fixture
def review(monkeypatch):
    texts = [f"选中的声明{index}" for index in range(13)]
    request = AnalyzeRequest(raw_input="完整旧报告", request_context={
        "review_claim_texts": texts, "review_claim_types": ["fact"] * len(texts),
        "search_sources": ["piyao"], "review_note": "保留核查范围",
    })
    event = NormalizedEvent(summary=request.raw_input, raw_input=request.raw_input, input_type="text_news")
    evidence = SearchResult(
        case_id="review", query="review", result_id="source", title="原始公告",
        url="https://example.org/notice", source_name="公告", published_at="",
        snippet="可引用的公告原文", source_tier="S",
    )
    bundle = RetrievalBundle(query="review", canonical_results=(evidence,), provider_name="fixture")
    reasoner = LlmAgentReasoner(settings=replace(
        get_settings(), analysis_provider="kimi", llm_api_key="test", evidence_rerank_enabled=False,
        agent_synthesis_critic_enabled=False,
    ))
    monkeypatch.setattr(reasoner, "_annotate_corrections", lambda results, *args: results)
    monkeypatch.setattr(reasoner, "_enrich_synthesis", lambda **kwargs: {
        "timeline_nodes": [], "possibilities": [], "event": None,
    })
    return reasoner, request, event, bundle


def _prompt_claims(kwargs):
    context = json.loads(kwargs["user_prompt"].split("<untrusted-input>\n", 1)[1].split("\n</untrusted-input>", 1)[0])
    return context["review_claim_texts"]


def _claims(texts, *, evidence_id="source"):
    return [{"claim": text, "claim_type": "fact", "verdict": "supported", "confidence": "high",
             "evidence_result_ids": [evidence_id], "notes": "原文支持"} for text in texts]


@pytest.mark.parametrize("failure", ["invalid_json", "exception"])
@pytest.mark.parametrize("failed_batch", [0, 1, 2])
def test_failed_batch_preserves_other_batches_and_selected_scope(monkeypatch, review, failure, failed_batch):
    reasoner, request, event, bundle = review
    calls = []

    def complete(**kwargs):
        calls.append(_prompt_claims(kwargs))
        if len(calls) - 1 == failed_batch:
            if failure == "exception":
                raise RuntimeError("batch unavailable")
            return "not JSON"
        return json.dumps({"claims": _claims(calls[-1])})

    monkeypatch.setattr(reasoner, "_request_completion", complete)
    result = reasoner.synthesize(request=request, event=event, retrieval_bundle=bundle)
    assert result is not None
    assert len(calls) == 3
    assert [item.claim for item in result.verdict.claim_results] == request.request_context["review_claim_texts"]
    for index, item in enumerate(result.verdict.claim_results):
        if index // 6 == failed_batch:
            assert item.verdict == "insufficient" and item.confidence == "low"
            assert not item.evidence and item.truth_probability is None
        else:
            assert item.verdict == "supported"
            assert item.evidence[0].url == bundle.canonical_results[0].url


@pytest.mark.parametrize("response", ["invalid", '{"claims": []}', '{"claims": [{"claim": " "}]}'])
def test_all_batches_failed_preserves_rule_fallback(monkeypatch, review, response):
    reasoner, request, event, bundle = review
    calls = []
    monkeypatch.setattr(reasoner, "_request_completion", lambda **kwargs: calls.append(kwargs) or response)
    monkeypatch.setattr(reasoner, "_enrich_synthesis", lambda **kwargs: pytest.fail("nothing to enrich"))
    assert reasoner.synthesize(request=request, event=event, retrieval_bundle=bundle) is None
    assert len(calls) == 3


def test_batch_results_cannot_cross_scope_change_types_or_invent_evidence(monkeypatch, review):
    reasoner, request, event, bundle = review
    texts = request.request_context["review_claim_texts"]
    # Duplicate selected text straddles batches with different original types.
    texts[6] = texts[0]
    request.request_context["review_claim_types"][6] = "prediction"
    calls = []

    def complete(**kwargs):
        selected = _prompt_claims(kwargs)
        calls.append(selected)
        if len(calls) == 1:
            # A claim from batch three must not fill a missing result there.
            return json.dumps({"claims": _claims(selected[:4] + [texts[-1]])})
        if len(calls) == 2:
            return json.dumps({"claims": _claims(selected, evidence_id="invented")})
        return json.dumps({"claims": _claims(["未选择的声明"])})

    monkeypatch.setattr(reasoner, "_request_completion", complete)
    result = reasoner.synthesize(request=request, event=event, retrieval_bundle=bundle)
    assert result is not None
    claims = result.verdict.claim_results
    assert [item.claim for item in claims] == texts
    assert [item.claim_type for item in claims] == request.request_context["review_claim_types"]
    assert [item.verdict for item in claims[:4]] == ["supported"] * 4
    assert all(item.verdict == "insufficient" for item in claims[4:])
    assert all(not item.evidence for item in claims[4:])
    assert claims[6].truth_probability is None


@pytest.mark.parametrize("stop_reason", ["user_cancelled", "call_budget_exhausted"])
def test_run_control_stops_batching_without_fallback_or_enrichment(monkeypatch, review, stop_reason):
    reasoner, request, event, bundle = review
    calls = []
    control = RunControl(max_llm_calls=1, cancelled=lambda: stop_reason == "user_cancelled" and bool(calls))

    def complete(**kwargs):
        control.reserve(1)
        calls.append(_prompt_claims(kwargs))
        return json.dumps({"claims": _claims(calls[-1])})

    monkeypatch.setattr(reasoner, "_request_completion", complete)
    monkeypatch.setattr(reasoner, "_enrich_synthesis", lambda **kwargs: pytest.fail("stopped runs must not enrich"))
    token = set_run_control(control)
    try:
        with pytest.raises(RunStopped, match=stop_reason):
            reasoner.synthesize(request=request, event=event, retrieval_bundle=bundle)
    finally:
        reset_run_control(token)
    assert len(calls) == control.llm_calls == 1


def test_batches_share_supplemental_evidence_and_fetched_bodies(monkeypatch, review):
    reasoner, request, event, bundle = review
    merges = []
    prompts = []
    original_prompt = reasoner._build_synthesis_prompt
    bodies = {"source": "已获取的完整公告正文"}
    original_request = request.model_dump()

    def merge(actual_request, actual_bundle):
        merges.append((actual_request, actual_bundle))
        return bundle

    def prompt(**kwargs):
        prompts.append(kwargs)
        assert kwargs["fetched_bodies"] is bodies
        assert kwargs["retrieval_bundle"] is bundle
        assert kwargs["request"].request_context["search_sources"] == ["piyao"]
        return original_prompt(**kwargs)

    monkeypatch.setattr("backend.app.services.agent_reasoner.merge_supplemental_evidence", merge)
    monkeypatch.setattr(reasoner, "_build_synthesis_prompt", prompt)
    monkeypatch.setattr(reasoner, "_request_completion", lambda **kwargs: json.dumps({"claims": _claims(_prompt_claims(kwargs))}))
    result = reasoner.synthesize(request=request, event=event, retrieval_bundle=None, fetched_bodies=bodies)
    assert result is not None
    assert merges == [(request, None)]
    assert len(prompts) == 3
    assert request.model_dump() == original_request


def test_fifty_claims_keep_critic_and_optional_stages_within_default_call_budget(monkeypatch, review):
    reasoner, request, event, bundle = review
    texts = [f"所选事实{index}" for index in range(50)]
    request.request_context.update(review_claim_texts=texts, review_claim_types=["fact"] * len(texts))
    reasoner.settings = replace(reasoner.settings, agent_synthesis_critic_enabled=True)
    monkeypatch.setattr(reasoner, "_annotate_corrections", LlmAgentReasoner._annotate_corrections.__get__(reasoner))
    monkeypatch.setattr(reasoner, "_enrich_synthesis", LlmAgentReasoner._enrich_synthesis.__get__(reasoner))
    calls = []
    # Initial resolution/retrieval/planning already consumed three model calls.
    control = RunControl(max_llm_calls=30, llm_calls=3)

    def complete(**kwargs):
        control.reserve(1)
        calls.append(kwargs["title"])
        if kwargs["system_prompt"] == CLAIMS_ONLY_SYSTEM_PROMPT:
            return json.dumps({"claims": _claims(_prompt_claims(kwargs))})
        if kwargs["system_prompt"] == SYNTHESIS_CRITIC_SYSTEM_PROMPT:
            return '{"revisions": []}'
        if kwargs["title"] == "调用数字纠正":
            return json.dumps([{"correction": None}] * 50)
        return '{"timeline": [], "scenarios": []}'

    monkeypatch.setattr(reasoner, "_request_completion", complete)
    token = set_run_control(control)
    try:
        result = reasoner.synthesize(request=request, event=event, retrieval_bundle=bundle)
    finally:
        reset_run_control(token)
    assert result is not None
    assert [item.claim for item in result.verdict.claim_results] == texts
    assert calls.count("调用 Agent synthesis") == calls.count("调用 Agent synthesis critic") == 9
    assert calls.count("调用数字纠正") == 1
    assert calls.count("调用 Agent enrichment (timeline/scenarios)") == 1
    assert control.llm_calls == 23


@pytest.mark.parametrize("count", [2, 7])
@pytest.mark.parametrize("missing_mode", ["omitted", "wrong_type"])
def test_missing_results_are_not_sent_for_correction(monkeypatch, review, count, missing_mode):
    reasoner, request, event, bundle = review
    texts = request.request_context["review_claim_texts"][:count]
    request.request_context.update(review_claim_texts=texts, review_claim_types=["fact"] * count)
    corrected_claims = []

    def complete(**kwargs):
        selected = _prompt_claims(kwargs)
        claims = _claims(selected[:1])
        if missing_mode == "wrong_type":
            claims.extend({**item, "claim_type": "prediction"} for item in _claims(selected[1:]))
        return json.dumps({"claims": claims})

    def correct(results, *args):
        corrected_claims.extend(item.claim for item in results)
        return [item.model_copy(update={"correction": {
            "original": "原断言", "actual": "公告中的实际内容", "source": "公告",
        }}) for item in results]

    monkeypatch.setattr(reasoner, "_request_completion", complete)
    monkeypatch.setattr(reasoner, "_annotate_corrections", correct)
    result = reasoner.synthesize(request=request, event=event, retrieval_bundle=bundle)
    assert result is not None
    assert corrected_claims == texts[::6]
    assert [item.claim for item in result.verdict.claim_results] == texts
    for index, item in enumerate(result.verdict.claim_results):
        if index % 6:
            assert item.verdict == "insufficient" and not item.evidence
            assert item.correction is None


def test_duplicate_claim_in_later_batch_cannot_fill_missing_earlier_copy(monkeypatch, review):
    reasoner, request, event, bundle = review
    texts = request.request_context["review_claim_texts"][:7]
    texts[6] = texts[0]
    request.request_context.update(review_claim_texts=texts, review_claim_types=["fact"] * 7)

    def complete(**kwargs):
        selected = _prompt_claims(kwargs)
        return json.dumps({"claims": _claims(selected[1:] if len(selected) == 6 else selected)})

    monkeypatch.setattr(reasoner, "_request_completion", complete)
    result = reasoner.synthesize(request=request, event=event, retrieval_bundle=bundle)
    assert result is not None
    claims = result.verdict.claim_results
    assert [item.claim for item in claims] == texts
    assert claims[0].verdict == "insufficient" and not claims[0].evidence
    assert claims[6].verdict == "supported" and claims[6].evidence
