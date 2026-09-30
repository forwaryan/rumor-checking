"""Retrieval diagnostics preserve results, privacy, and concurrent parentage."""
from asyncio import CancelledError
from dataclasses import replace
from threading import Barrier
from types import SimpleNamespace

import pytest

from backend.app.agent.trace import TraceExporter, get_current_parent, get_current_trace
from backend.app.core.config import get_settings
from backend.app.core.exceptions import AppError
from backend.app.models.schemas import NormalizedEvent
from backend.app.services.phoenix_exporter import span_attributes
from backend.app.services.retrieval_cache import RetrievalCache
from backend.app.services.retrieval_models import RetrievalQuerySpec, SearchResult
from backend.app.services.retrieval_observer import observe_retrieval
from backend.app.services.retrieval_service import RetrievalService

SECRET = "TEST_PRIVATE_QUERY_URL_AND_EXCEPTION_SENTINEL"


def hit(index="1"):
    return SearchResult(case_id="test", query=SECRET, result_id=index, title=f"{SECRET} {index}",
                        snippet=SECRET, url=f"https://example.com/{SECRET}/{index}",
                        source_name=SECRET, published_at="", source_tier="B")


def setup_service(tmp_path, monkeypatch, search, *, cache_enabled=False, ttl=600, queries=1):
    settings = replace(get_settings(), retrieval_provider="gdelt", retrieval_cache_enabled=cache_enabled,
                       retrieval_fallback_to_mock=False, retrieval_cache_allow_stale_on_error=True)
    provider = SimpleNamespace(name="gdelt", enabled=True, search=search)
    service = RetrievalService(settings=settings, provider=provider,
                               cache=RetrievalCache(cache_root=tmp_path, ttl_seconds=ttl))
    plan = [RetrievalQuerySpec(label=f"query{index}", query=f"{SECRET}{index}", rationale=SECRET)
            for index in range(queries)]
    monkeypatch.setattr(service, "_build_query_plan", lambda *a, **kw: plan)
    return service, plan


def retrieve(service, exporter, **context):
    with exporter.activate():
        return service.retrieve_for_event(
            NormalizedEvent(summary=SECRET, raw_input=SECRET, input_type="text_news", keywords=[]),
            request_context={"search_sources": ["baidu"], **context},
        )


def spans(exporter, operation):
    return [s for s in exporter.record.spans if s.metadata.get("operation") == operation]


def test_concurrent_queries_parent_llm_under_query_and_never_capture_content(tmp_path, monkeypatch):
    exporter = TraceExporter("test")
    barrier = Barrier(2)

    def search(query):
        parent = get_current_parent()
        assert parent.metadata["operation"] == "query"
        assert get_current_trace() is exporter
        barrier.wait(timeout=5)
        with exporter.span("fake.model", span_kind="LLM"):
            pass
        return [hit(query[-1])]

    service, _ = setup_service(tmp_path, monkeypatch, search, queries=2)
    bundle = retrieve(service, exporter)
    queries = spans(exporter, "query")
    root = spans(exporter, "round")[0]
    assert len(queries) == 2
    assert all(q.parent_span_id == root.span_id for q in queries)
    assert {s.parent_span_id for s in exporter.record.spans if s.action == "fake.model"} == {q.span_id for q in queries}
    assert root.metadata["canonical_result_count"] == len(bundle.canonical_results)
    assert root.metadata["failure_count"] == 0
    assert SECRET not in exporter.record.to_json()
    assert SECRET not in str([span_attributes(s) for s in exporter.record.spans])
    assert all(span_attributes(q)["openinference.span.kind"] == "RETRIEVER" for q in queries)
    assert get_current_trace() is None


def test_cache_hit_and_cache_only_miss_are_visible_without_network(tmp_path, monkeypatch):
    calls = []
    service, _ = setup_service(tmp_path, monkeypatch, lambda q: calls.append(q) or [hit()], cache_enabled=True)
    retrieve(service, TraceExporter("populate"))
    exporter = TraceExporter("hit")
    bundle = retrieve(service, exporter)
    assert len(calls) == 1
    assert not spans(exporter, "query")
    assert spans(exporter, "cache")[0].metadata["cache_status"] == "hit"
    assert bundle.cache_status == "hit"
    empty_service, _ = setup_service(tmp_path / "empty", monkeypatch, lambda q: pytest.fail("network"), cache_enabled=True)
    empty_exporter = TraceExporter("miss")
    retrieve(empty_service, empty_exporter, retrieval_cache_only=True)
    assert spans(empty_exporter, "cache")[0].metadata["status"] == "miss"
    assert spans(empty_exporter, "round")[0].metadata["status"] == "empty"


def test_failed_query_stale_fallback_is_partial_without_exception_text(tmp_path, monkeypatch):
    service, _ = setup_service(tmp_path, monkeypatch, lambda q: [hit()], cache_enabled=True, ttl=0)
    retrieve(service, TraceExporter("populate"))

    def fail(query):
        raise TimeoutError(SECRET)

    service.provider.search = fail
    exporter = TraceExporter("stale")
    bundle = retrieve(service, exporter)
    assert bundle.fallback_used
    query = spans(exporter, "query")[0]
    assert query.metadata["status"] == "error"
    assert query.error_type == "TimeoutError" and query.error_message is None
    assert spans(exporter, "cache")[-1].metadata["cache_status"] == "stale_hit"
    assert spans(exporter, "round")[0].metadata["status"] == "partial"
    assert spans(exporter, "round")[0].metadata["failure_count"] == 1
    assert SECRET not in exporter.record.to_json()


@pytest.mark.parametrize("error", [CancelledError(SECRET), AppError(status_code=422, code="cancel", message=SECRET)])
def test_cancellation_and_app_error_propagate_and_restore_context(tmp_path, monkeypatch, error):
    def fail(query):
        raise error

    service, _ = setup_service(tmp_path, monkeypatch, fail)
    exporter = TraceExporter("cancel")
    with pytest.raises(type(error)) as caught:
        retrieve(service, exporter)
    assert caught.value is error
    assert spans(exporter, "round")[0].metadata["status"] == "error"
    assert SECRET not in exporter.record.to_json()
    assert get_current_trace() is None


def test_supplementary_and_official_failures_remain_best_effort(tmp_path, monkeypatch):
    def fail(query, **kwargs):
        raise RuntimeError(SECRET)

    service, _ = setup_service(tmp_path, monkeypatch, fail)
    service.xhs_provider = SimpleNamespace(enabled=True, search=fail)
    monkeypatch.setattr(service, "_pick_official_whitelist", lambda q: ("example.com",))
    exporter = TraceExporter("supplement")
    bundle = retrieve(service, exporter, search_sources=["xiaohongshu", "official_boost"])
    assert not bundle.canonical_results
    assert spans(exporter, "supplement")[0].metadata["status"] == "error"
    assert spans(exporter, "official_boost")[0].metadata["status"] == "error"
    assert spans(exporter, "round")[0].metadata["failure_count"] == 2
    assert spans(exporter, "round")[0].metadata["status"] == "partial"
    assert SECRET not in exporter.record.to_json()


def test_filter_counts_distinguish_rejections_and_soft_fallback(tmp_path, monkeypatch):
    service, _ = setup_service(tmp_path, monkeypatch, lambda q: [])
    monkeypatch.setattr(service, "_is_noise_result", lambda r: r.result_id == "noise")
    monkeypatch.setattr(service, "_is_navigational_non_evidence", lambda r: r.result_id == "navigation")
    monkeypatch.setattr(service, "_is_topically_disjoint", lambda r: r.result_id == "disjoint")
    monkeypatch.setattr(service, "_result_matches_query", lambda r: False)
    exporter = TraceExporter("selection")
    with exporter.activate():
        selected = service._filter_relevant_results([hit(i) for i in ("noise", "navigation", "disjoint", "a", "b")])
    assert [r.result_id for r in selected] == ["a", "b"]
    metadata = spans(exporter, "selection")[0].metadata
    assert metadata["filtered_result_count"] == 3
    assert metadata["filtered_noise_count"] == metadata["filtered_navigation_count"] == metadata["filtered_disjoint_count"] == 1
    assert metadata["filtered_relevance_count"] == 0
    assert metadata["soft_relevance_fallback"] is True


@pytest.mark.parametrize("method", ["begin_span", "end_span"])
def test_broken_observation_sink_does_not_change_results_or_bindings(tmp_path, monkeypatch, method):
    service, _ = setup_service(tmp_path, monkeypatch, lambda q: [hit()])
    expected = service.retrieve_for_event(
        NormalizedEvent(summary=SECRET, raw_input=SECRET, input_type="text_news", keywords=[]),
        request_context={"search_sources": ["baidu"]},
    )
    exporter = TraceExporter("broken")

    def broken(*args, **kwargs):
        raise RuntimeError("sink failed")

    monkeypatch.setattr(exporter, method, broken)
    actual = retrieve(service, exporter)
    assert [replace(r, retrieved_at=None) for r in actual.canonical_results] == [
        replace(r, retrieved_at=None) for r in expected.canonical_results
    ]
    assert get_current_parent() is None and get_current_trace() is None


def test_metadata_provider_and_stage_are_whitelisted():
    exporter = TraceExporter("safe")
    with exporter.activate(), observe_retrieval("query", provider=SECRET, stage_key=SECRET):
        pass
    metadata = spans(exporter, "query")[0].metadata
    assert metadata["provider"] == metadata["stage_key"] == "other"
    assert SECRET not in exporter.record.to_json()


def test_real_otel_export_keeps_retriever_parent_and_error_status(tmp_path, monkeypatch):
    pytest.importorskip("opentelemetry.sdk.trace")
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from backend.app.services.phoenix_exporter import build_spans

    def fail(query):
        raise TimeoutError(SECRET)

    service, _ = setup_service(tmp_path, monkeypatch, fail)
    exporter = TraceExporter("otel")
    retrieve(service, exporter)
    sink = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(sink))
    build_spans(exporter.finalize(), provider.get_tracer("retrieval-test"))
    exported = {s.name: s for s in sink.get_finished_spans()}
    query = exported["retrieval.query"]
    assert query.attributes["openinference.span.kind"] == "RETRIEVER"
    assert query.parent.span_id == exported["retrieval.round"].context.span_id
    assert query.status.status_code.name == "ERROR"
    assert SECRET not in str([s.attributes for s in sink.get_finished_spans()])
    provider.shutdown()


def test_dedup_stage_counts_actual_duplicates_separately_from_filtering(tmp_path, monkeypatch):
    first = hit()
    service, _ = setup_service(tmp_path, monkeypatch, lambda q: [first, replace(first, result_id="copy")])
    exporter = TraceExporter("duplicates")
    bundle = retrieve(service, exporter)
    assert len(bundle.canonical_results) == 1
    dedup = [s.metadata for s in spans(exporter, "selection") if "duplicate_count" in s.metadata]
    assert dedup
    assert all(s["duplicate_count"] == 1 and s["selected_result_count"] == 1 for s in dedup)
    filtering = [s.metadata for s in spans(exporter, "selection") if "filtered_result_count" in s.metadata]
    assert all(s["filtered_result_count"] == 0 for s in filtering)
