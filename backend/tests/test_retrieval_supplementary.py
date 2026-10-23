"""Supplementary searches overlap without changing evidence selection or context."""
from dataclasses import replace
from threading import Barrier, Event
from types import SimpleNamespace

import pytest

from backend.app.agent.trace import TraceExporter, get_current_parent, get_current_trace
from backend.app.core.config import get_settings
from backend.app.models.schemas import NormalizedEvent
from backend.app.services.progress import (
    emit_api_call,
    get_progress_callback,
    get_retrieval_stage_key,
    reset_progress_callback,
    reset_retrieval_stage_key,
    set_progress_callback,
    set_retrieval_stage_key,
)
from backend.app.services.retrieval_models import RetrievalBundle, SearchResult
from backend.app.services.retrieval_service import RetrievalService
from backend.app.services.run_control import (
    RunControl,
    RunStopped,
    get_run_control,
    reset_run_control,
    set_run_control,
)

SOURCES = ("xiaohongshu", "toutiao", "sogou_weixin", "piyao")
PROVIDERS = ("xhs_provider", "toutiao_provider", "sogou_weixin_provider", "piyao_provider")
EVENT = NormalizedEvent(summary="城市交通公告", raw_input="城市交通公告", input_type="text_news", keywords=[])


def hit(result_id, host, *, tier="C"):
    return SearchResult(
        case_id="test", query="城市交通公告", result_id=result_id, title="城市交通公告",
        snippet="城市交通公告回应网传消息。", url=f"https://{host}/{result_id}",
        source_name=host, published_at="", source_tier=tier,
    )


def setup_service(monkeypatch):
    primary_hit = replace(hit("primary", "primary.test"), independence_key="primary.test")
    bundle = RetrievalBundle(
        query="城市交通公告", raw_results=(primary_hit,), canonical_results=(primary_hit,),
        provider_name="gdelt", matched_case_id="original", cache_status="hit", cache_key="cached-key",
        fallback_used=True, fallback_reason="original reason", query_failures=("original failure",),
        retrieved_at="2026-01-01T00:00:00+00:00", expected_origin_result_id="primary",
    )
    service = RetrievalService(settings=replace(get_settings(), retrieval_provider="mock"))
    service.provider = SimpleNamespace(
        enabled=True, name="gdelt", search=lambda *a, **kw: pytest.fail("unexpected official search"),
    )
    monkeypatch.setattr(service, "_retrieve_for_event", lambda *a, **kw: bundle)
    return service, bundle


def test_supplementary_sources_overlap_and_preserve_order_context_and_metadata(monkeypatch):
    service, primary = setup_service(monkeypatch)
    barrier = Barrier(4)
    release = [Event() for _ in SOURCES]
    release[-1].set()
    completed = []
    hits = [
        [hit("xhs", "shared.test"), hit("xhs-second", "shared.test")],
        [hit("toutiao-duplicate", "shared.test"), hit("toutiao", "toutiao.test")],
        [hit("sogou-duplicate", "primary.test"), hit("sogou", "sogou.test")],
        [hit("piyao", "piyao.test", tier="A")],
    ]
    exporter = TraceExporter("parallel-supplements")
    progress = []
    callback = progress.append

    def search(index, query, *, max_results):
        assert query == primary.query and max_results == 5
        assert get_progress_callback() is callback
        assert get_retrieval_stage_key() == "retrieval_follow_up"
        assert get_current_trace() is exporter
        assert get_current_parent().metadata["operation"] == "supplement"
        barrier.wait(timeout=5)
        assert release[index].wait(timeout=5)
        completed.append(index)
        if index:
            release[index - 1].set()
        emit_api_call(stage_key=get_retrieval_stage_key(), call_type="http", status="completed",
                      title=SOURCES[index], summary="done", details=[])
        return hits[index]

    for index, name in enumerate(PROVIDERS):
        def search_source(query, *, max_results, index=index):
            return search(index, query, max_results=max_results)
        setattr(service, name, SimpleNamespace(enabled=True, search=search_source))

    seen_at_boost = []
    original_boost = service._append_official_source_results

    def boost(bundle, query, *, stage_key):
        seen_at_boost.extend(item.result_id for item in bundle.canonical_results)
        return original_boost(bundle, query, stage_key=stage_key)

    monkeypatch.setattr(service, "_append_official_source_results", boost)
    callback_token = set_progress_callback(callback)
    stage_token = set_retrieval_stage_key("outer-stage")
    try:
        with exporter.activate():
            result = service.retrieve_for_event(EVENT, request_context={"retrieval_stage_key": "retrieval_follow_up"})
        assert get_retrieval_stage_key() == "outer-stage"
        assert get_progress_callback() is callback
    finally:
        reset_retrieval_stage_key(stage_token)
        reset_progress_callback(callback_token)

    expected_ids = ["primary", "xhs", "xhs-second", "toutiao", "sogou", "piyao"]
    assert completed == [3, 2, 1, 0]
    assert [r.result_id for r in result.canonical_results] == expected_ids
    assert [r.result_id for r in result.raw_results] == expected_ids
    assert seen_at_boost == expected_ids
    assert replace(result, raw_results=primary.raw_results, canonical_results=primary.canonical_results) == primary
    assert result.canonical_results[-1].source_category == "official_debunking"
    assert all(r.independence_key and r.retrieved_at and r.signal_tags for r in result.canonical_results[1:])
    assert len(progress) == 4
    assert all(item["stage_key"] == "retrieval_follow_up" for item in progress)
    root = next(s for s in exporter.record.spans if s.metadata.get("operation") == "round")
    supplements = [s for s in exporter.record.spans if s.metadata.get("operation") == "supplement"]
    assert len(supplements) == 4
    assert all(s.parent_span_id == root.span_id for s in supplements)
    selections = {s.metadata["provider"]: s.metadata for s in exporter.record.spans
                  if s.metadata.get("operation") == "selection"}
    assert selections["toutiao"]["duplicate_count"] == selections["sogou_weixin"]["duplicate_count"] == 1
    assert root.metadata["failure_count"] == 0
    assert get_current_parent() is None and get_current_trace() is None


def test_failed_supplement_does_not_discard_other_sources(monkeypatch):
    service, primary = setup_service(monkeypatch)
    barrier = Barrier(4)

    def search(index, query, **kwargs):
        barrier.wait(timeout=5)
        if index == 1:
            raise TimeoutError("provider failed")
        return [hit(SOURCES[index], f"source{index}.test")]

    for index, name in enumerate(PROVIDERS):
        def search_source(query, *, index=index, **kwargs):
            return search(index, query, **kwargs)
        setattr(service, name, SimpleNamespace(enabled=True, search=search_source))
    exporter = TraceExporter("partial-supplements")
    with exporter.activate():
        result = service.retrieve_for_event(EVENT, request_context={"disable_official_boost": True})
    assert [r.result_id for r in result.canonical_results] == ["primary", "xiaohongshu", "sogou_weixin", "piyao"]
    assert result.cache_key == primary.cache_key
    root = next(s for s in exporter.record.spans if s.metadata.get("operation") == "round")
    assert root.metadata["failure_count"] == 1
    assert root.metadata["status"] == "partial"


@pytest.mark.parametrize("stop_reason", ["user_cancelled", "call_budget_exhausted", "token_budget_exhausted"])
def test_supplementary_workers_share_control_and_propagate_stop(monkeypatch, stop_reason):
    service, _ = setup_service(monkeypatch)
    barrier = Barrier(4)
    control = RunControl(
        cancelled=lambda: stop_reason == "user_cancelled",
        max_llm_calls=1,
        llm_calls=1 if stop_reason == "call_budget_exhausted" else 0,
        max_tokens=1,
    )
    inherited = {}
    signals = []

    def search(index, query, **kwargs):
        inherited[index] = get_run_control()
        barrier.wait(timeout=5)
        if index == 1:
            try:
                inherited[index].reserve(2)
            except RunStopped as stopped:
                signals.append(stopped)
                raise
        return [hit(SOURCES[index], f"source{index}.test")]

    for index, name in enumerate(PROVIDERS):
        def search_source(query, *, index=index, **kwargs):
            return search(index, query, **kwargs)
        setattr(service, name, SimpleNamespace(enabled=True, search=search_source))
    monkeypatch.setattr(service, "_append_official_source_results",
                        lambda *a, **kw: pytest.fail("boost must not run after RunStopped"))
    exporter = TraceExporter("stopped-supplements")
    control_token = set_run_control(control)
    stage_token = set_retrieval_stage_key("outer-stage")
    try:
        with exporter.activate(), pytest.raises(RunStopped) as stopped:
            service.retrieve_for_event(EVENT)
        assert stopped.value is signals[0]
        assert stopped.value.reason == stop_reason
        assert get_run_control() is control
        assert get_retrieval_stage_key() == "outer-stage"
    finally:
        reset_retrieval_stage_key(stage_token)
        reset_run_control(control_token)

    assert set(inherited) == {0, 1, 2, 3}
    assert all(value is control for value in inherited.values())
    root = next(s for s in exporter.record.spans if s.metadata.get("operation") == "round")
    assert root.metadata["status"] == "error"
    assert root.error_type == "RunStopped"
    assert get_run_control() is None
    assert get_current_parent() is None and get_current_trace() is None


@pytest.mark.parametrize("sources,enabled,expected", [
    (["baidu"], True, []),
    (["baidu", "toutiao"], True, ["toutiao"]),
    (["baidu", "toutiao"], False, []),
])
def test_supplementary_source_filter_and_enabled_flag(monkeypatch, sources, enabled, expected):
    service, primary = setup_service(monkeypatch)
    calls = []
    for source, name in zip(SOURCES, PROVIDERS, strict=True):
        def search(query, *, max_results, source=source):
            calls.append(source)
            return []
        setattr(service, name, SimpleNamespace(enabled=enabled, search=search))
    result = service.retrieve_for_event(EVENT, request_context={"search_sources": sources})
    assert calls == expected
    assert result is primary
