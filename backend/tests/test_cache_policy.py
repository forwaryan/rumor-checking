from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.app.agent.verdict_cache import CachedVerdict, MemoryVerdictCache, fingerprint
from backend.app.core.config import get_settings
from backend.app.models.schemas import AnalyzeRequest, EvidenceItem, MockFetchResult
from backend.app.services import page_fetcher
from backend.app.services.analyze_pipeline import AnalyzePipeline
from backend.tests.test_analysis_runs import sample_report


def _pipeline():
    pipeline = AnalyzePipeline.__new__(AnalyzePipeline)
    pipeline.settings = replace(get_settings(), agent_verdict_cache_enabled=True)
    cache = MemoryVerdictCache()
    pipeline._get_verdict_cache = lambda: cache
    pipeline._run_with_failover_summary = Mock(return_value=sample_report().model_copy(update={"mode": "partial_mode"}))
    return pipeline, cache


@pytest.mark.parametrize("context", [
    {"mode": "deep"}, {"mode": "fast", "model": "alternate"},
    {"mode": "fast", "search_sources": ["piyao"]}, {"mode": "fast", "disable_official_boost": True},
    {"mode": "fast", "force_retrieval_query": "other subject"},
])
def test_verdict_cache_isolates_request_policy(context):
    pipeline, _cache = _pipeline()
    pipeline.analyze(AnalyzeRequest(raw_input="同一声明", request_context={"mode": "fast"}))
    pipeline.analyze(AnalyzeRequest(raw_input="同一声明", request_context=context))
    assert pipeline._run_with_failover_summary.call_count == 2


def test_verdict_cache_reuses_identical_policy_across_runs_and_dict_order():
    pipeline, _cache = _pipeline()
    first = pipeline.analyze(AnalyzeRequest(raw_input="同一声明", request_context={"run_id": "one", "mode": "deep", "model": "selected"}))
    second = pipeline.analyze(AnalyzeRequest(raw_input="同一声明", request_context={"model": "selected", "mode": "deep", "run_id": "two"}))
    assert first == second
    assert pipeline._run_with_failover_summary.call_count == 1


def test_verdict_cache_invalidates_when_configured_model_changes():
    pipeline, _cache = _pipeline()
    request = AnalyzeRequest(raw_input="同一声明")
    pipeline.analyze(request)
    pipeline.settings = replace(pipeline.settings, llm_model="different-default")
    pipeline.analyze(request)
    assert pipeline._run_with_failover_summary.call_count == 2


@pytest.mark.parametrize("changed", [
    {"sogou_weixin_search_enabled": True}, {"piyao_search_enabled": True},
    {"llm_base_url": "https://other.example.org/v1"}, {"llm_model_base_urls": {"model": "https://other.example.org/v1"}},
    {"retrieval_max_results": 99}, {"rendered_fetch_enabled": True},
])
def test_verdict_cache_invalidates_when_source_and_transport_profiles_change(changed):
    pipeline, _cache = _pipeline()
    pipeline.settings = replace(pipeline.settings, rendered_fetch_enabled=False,
                                sogou_weixin_search_enabled=False, piyao_search_enabled=False)
    request = AnalyzeRequest(raw_input="同一声明")
    pipeline.analyze(request)
    pipeline.settings = replace(pipeline.settings, **changed)
    pipeline.analyze(request)
    assert pipeline._run_with_failover_summary.call_count == 2


def test_verdict_cache_bypasses_nonserializable_request_policy():
    pipeline, cache = _pipeline()
    request = AnalyzeRequest(raw_input="同一声明", request_context={"callback": object()})
    pipeline.analyze(request)
    pipeline.analyze(request)
    assert pipeline._run_with_failover_summary.call_count == 2
    assert cache.size == 0


@pytest.mark.parametrize("updates", [
    {"mock_fetch_result": MockFetchResult(status="ok", body="mock body")},
    {"mock_evidence": [EvidenceItem(title="mock", url="https://example.org", source_name="mock", published_at="", snippet="mock", relevance_reason="mock")]},
    {"request_context": {"supplemental_urls": ["https://example.org"]}},
    {"request_context": {"review_claim_texts": ["所选声明"]}},
    {"request_context": {"skip_retrieval_cache": True}},
    {"request_context": {"bypass_retrieval_cache": True}},
])
def test_mock_supplement_review_and_forced_refresh_never_read_or_write_verdict_cache(updates):
    pipeline, cache = _pipeline()
    request = AnalyzeRequest(raw_input="同一声明", **updates)
    pipeline.analyze(request)
    pipeline.analyze(request)
    assert pipeline._run_with_failover_summary.call_count == 2
    assert cache.size == 0


def test_legacy_text_only_verdict_keys_do_not_match_new_policy():
    pipeline, cache = _pipeline()
    request = AnalyzeRequest(raw_input="同一声明")
    cache.put(CachedVerdict(fingerprint=fingerprint(request.raw_input), raw_input=request.raw_input,
                           verdict="supported", confidence="high", claim_results_json="[]", cached_at=pipeline._now_ts(),
                           metadata={"report_json": sample_report().model_dump_json()}))
    pipeline.analyze(request)
    assert pipeline._run_with_failover_summary.call_count == 1


def test_verdict_cache_stays_disabled_by_configuration():
    pipeline = AnalyzePipeline.__new__(AnalyzePipeline)
    pipeline.settings = replace(get_settings(), agent_verdict_cache_enabled=False)
    assert pipeline._get_verdict_cache() is None


def test_pipeline_review_policy_reaches_page_fetch_and_is_reset(monkeypatch):
    from backend.app.services.cache_policy import requires_fresh_evidence

    pipeline = AnalyzePipeline.__new__(AnalyzePipeline)
    observed = []

    def analyze(request):
        observed.append(requires_fresh_evidence())
        return sample_report()

    pipeline._analyze_uncached = analyze
    monkeypatch.setattr(pipeline, "_emit_failover_summary", lambda *args: None)
    pipeline._run_with_failover_summary(AnalyzeRequest(raw_input="声明", request_context={"review_claim_texts": ["所选声明"]}))
    pipeline._run_with_failover_summary(AnalyzeRequest(raw_input="声明"))
    assert observed == [True, False]
    assert not requires_fresh_evidence()


def test_review_cache_context_is_propagated_and_reset_after_failure():
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context

    from backend.app.services.cache_policy import evidence_cache_policy, requires_fresh_evidence

    with pytest.raises(RuntimeError), evidence_cache_policy({"review_claim_texts": ["声明"]}):
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(copy_context().run, requires_fresh_evidence).result()
        raise RuntimeError("failed review")
    assert not requires_fresh_evidence()


@pytest.mark.parametrize("refresh", [False, True])
def test_page_fetch_cache_disable_or_review_forces_network(monkeypatch, refresh):
    from backend.app.services.cache_policy import evidence_cache_policy

    cache = SimpleNamespace(read=Mock(return_value=MockFetchResult(status="ok", body="old")), write=Mock())
    monkeypatch.setattr(page_fetcher, "_cache", cache)
    monkeypatch.setattr(page_fetcher, "is_safe_url", lambda url: True)
    settings = SimpleNamespace(url_fetch_cache_enabled=refresh, url_fetch_timeout_seconds=1, url_fetch_max_retries=0)
    monkeypatch.setattr("backend.app.core.config.get_settings", lambda: settings)
    transport = Mock(return_value=SimpleNamespace(status_code=200, text="<p>new</p>", url="https://example.org/source"))
    monkeypatch.setattr(page_fetcher, "reliable_get", transport)
    with evidence_cache_policy({"review_claim_texts": ["声明"]} if refresh else {}):
        assert page_fetcher._fetch_single_page("https://example.org/source") == "new"
    assert not cache.read.called
    assert transport.call_count == 1
    assert cache.write.call_count == int(refresh)
