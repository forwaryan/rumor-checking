"""Tests for structured trace export (P2)."""
from __future__ import annotations

import json
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from backend.app.agent.trace import TraceExporter, TraceRecord, TraceSpan
from backend.app.services.phoenix_exporter import export_trace_to_phoenix, span_attributes

# --- TraceSpan ---


def test_span_duration():
    span = TraceSpan(action="search_news", start_time=1000.0, end_time=1000.5)
    assert span.duration_ms == 500.0


def test_span_to_dict():
    span = TraceSpan(
        action="normalize",
        start_time=100.0,
        end_time=100.1,
        success=True,
        token_usage={"prompt": 50, "completion": 20, "total": 70},
    )
    d = span.to_dict()
    assert d["action"] == "normalize"
    assert d["success"] is True
    assert d["duration_ms"] == 100.0
    assert d["token_usage"]["total"] == 70


def test_phoenix_span_attributes_are_flat_and_semantic():
    span = TraceSpan(
        action="synthesize",
        start_time=1.0,
        end_time=2.0,
        span_id="span_0002",
        parent_span_id="span_0001",
        success=False,
        error_type="TimeoutError",
        token_usage={"prompt": 12, "completion": 3, "total": 15},
        metadata={"model": "test-model", "queries": ["a", "b"]},
    )

    attributes = span_attributes(span)

    assert attributes["openinference.span.kind"] == "TOOL"
    assert attributes["rumor_checking.parent_span_id"] == "span_0001"
    assert attributes["llm.token_count.total"] == 15
    assert attributes["error.type"] == "TimeoutError"
    assert attributes["rumor_checking.metadata.queries"] == '["a", "b"]'


def test_phoenix_export_is_noop_when_disabled():
    record = TraceRecord(run_id="offline", start_time=1.0, end_time=2.0)
    assert export_trace_to_phoenix(
        record,
        enabled=False,
        endpoint="http://localhost:6006/v1/traces",
        project_name="test",
    ) is False


# --- TraceRecord ---


def test_record_aggregation():
    record = TraceRecord(run_id="test-1", start_time=100.0)
    record.spans = [
        TraceSpan(action="a", start_time=100.0, end_time=100.5, success=True,
                  token_usage={"total": 100}),
        TraceSpan(action="b", start_time=100.5, end_time=101.0, success=False,
                  error_type="Timeout", token_usage={"total": 50}),
        TraceSpan(action="c", start_time=101.0, end_time=101.2, success=True,
                  token_usage={"total": 200}),
    ]
    record.end_time = 101.2
    assert record.total_tokens == 350
    assert record.success_count == 2
    assert record.failure_count == 1
    assert abs(record.duration_ms - 1200.0) < 0.01


def test_record_to_json():
    record = TraceRecord(run_id="json-test", start_time=0, end_time=1.0)
    record.spans = [
        TraceSpan(action="normalize", start_time=0, end_time=0.1, success=True),
    ]
    json_str = record.to_json()
    parsed = json.loads(json_str)
    assert parsed["run_id"] == "json-test"
    assert len(parsed["spans"]) == 1
    assert parsed["spans"][0]["action"] == "normalize"


# --- TraceExporter ---


def test_exporter_begin_end_span():
    exporter = TraceExporter(run_id="export-1")
    exporter.begin_span("search_news")
    time.sleep(0.01)
    exporter.end_span(success=True, token_usage={"total": 100})

    record = exporter.finalize()
    assert len(record.spans) == 1
    assert record.spans[0].action == "search_news"
    assert record.spans[0].success is True
    assert record.spans[0].duration_ms > 0


def test_exporter_end_span_without_begin():
    exporter = TraceExporter(run_id="orphan")
    # Should not crash
    exporter.end_span(success=False)
    assert len(exporter.record.spans) == 0


def test_exporter_multiple_spans():
    exporter = TraceExporter(run_id="multi")
    for action in ["normalize", "search_news", "synthesize"]:
        exporter.begin_span(action)
        exporter.end_span(success=True)

    record = exporter.finalize()
    assert len(record.spans) == 3
    actions = [s.action for s in record.spans]
    assert actions == ["normalize", "search_news", "synthesize"]


def test_exporter_export_to_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        exporter = TraceExporter(run_id="file-test")
        exporter.begin_span("normalize")
        exporter.end_span(success=True)
        exporter.finalize()

        path = Path(tmpdir) / "traces" / "test.json"
        exporter.export_to_file(path)

        assert path.exists()
        content = json.loads(path.read_text(encoding="utf-8"))
        assert content["run_id"] == "file-test"
        assert len(content["spans"]) == 1


def test_exporter_hook_integration():
    """Test hook-style usage (pre_hook / post_hook)."""
    exporter = TraceExporter(run_id="hook-test")

    @dataclass
    class FakeOutcome:
        success: bool = True
        error_type: str | None = None
        error_message: str | None = None

    @dataclass
    class FakeState:
        class token_usage:
            prompt_tokens = 100
            completion_tokens = 50
            total_tokens = 150

    @dataclass
    class FakeHookCtx:
        action: str
        state: object = None
        outcome: object = None

    # Simulate pre → post cycle
    ctx1 = FakeHookCtx(action="search_news", state=FakeState())
    exporter.pre_hook(ctx1)
    ctx1.outcome = FakeOutcome(success=True)
    exporter.post_hook(ctx1)

    ctx2 = FakeHookCtx(action="synthesize", state=FakeState())
    exporter.pre_hook(ctx2)
    ctx2.outcome = FakeOutcome(success=False, error_type="Timeout", error_message="timed out")
    exporter.post_hook(ctx2)

    record = exporter.finalize()
    assert len(record.spans) == 2
    assert record.spans[0].success is True
    assert record.spans[0].token_usage["total"] == 150
    assert record.spans[1].success is False
    assert record.spans[1].error_type == "Timeout"


def test_exporter_metadata():
    exporter = TraceExporter(run_id="meta", metadata={"model": "test-model", "mode": "deep"})
    record = exporter.finalize()
    assert record.metadata["model"] == "test-model"
    d = record.to_dict()
    assert d["metadata"]["mode"] == "deep"


# --- Phoenix export verification against a real in-memory OTel exporter ---
# These prove build_spans emits genuine OpenInference spans (tree shape, kinds,
# status) — the same spans a live Phoenix would receive — without needing a
# reachable Phoenix/OTLP endpoint. Skipped when the observability extra
# (opentelemetry-*) is not installed, so the default test env stays dependency-free.

import pytest  # noqa: E402

otel_sdk = pytest.importorskip("opentelemetry.sdk.trace")


def _in_memory_tracer():
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer("test"), exporter


def test_build_spans_emits_real_openinference_span_tree():
    from backend.app.services.phoenix_exporter import build_spans

    record = TraceRecord(run_id="run-1", start_time=1.0, end_time=5.0, metadata={"mode": "deep"})
    record.spans = [
        TraceSpan(action="retrieve", start_time=1.0, end_time=2.0, span_id="s1", success=True),
        TraceSpan(
            action="synthesize", start_time=2.0, end_time=3.0, span_id="s2",
            parent_span_id="s1", success=False, error_type="Timeout",
        ),
    ]

    tracer, exporter = _in_memory_tracer()
    build_spans(record, tracer)

    spans = exporter.get_finished_spans()
    # root + 2 children all actually emitted
    names = {s.name for s in spans}
    assert names == {"rumor-checking.run", "retrieve", "synthesize"}

    by_name = {s.name: s for s in spans}
    # Root carries the OpenInference CHAIN kind + session id.
    assert by_name["rumor-checking.run"].attributes["openinference.span.kind"] == "CHAIN"
    assert by_name["rumor-checking.run"].attributes["session.id"] == "run-1"
    # Parent/child tree is preserved: synthesize nests under retrieve.
    assert by_name["synthesize"].parent.span_id == by_name["retrieve"].context.span_id
    assert by_name["retrieve"].parent.span_id == by_name["rumor-checking.run"].context.span_id
    # Status maps success->OK, failure->ERROR.
    from opentelemetry.trace import StatusCode
    assert by_name["retrieve"].status.status_code == StatusCode.OK
    assert by_name["synthesize"].status.status_code == StatusCode.ERROR


def test_export_trace_to_phoenix_returns_true_on_successful_flush(monkeypatch):
    """End-to-end: enabled + a working (in-memory) OTLP path returns True. Proves
    the full export_trace_to_phoenix wiring flushes without error given real OTel."""
    # Swap the OTLP HTTP exporter for the in-memory one so no network is needed.
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from backend.app.services import phoenix_exporter

    captured = InMemorySpanExporter()

    class _StubOTLP:
        def __init__(self, *a, **k):
            pass

        def export(self, spans):
            return captured.export(spans)

        def shutdown(self):
            captured.shutdown()

        def force_flush(self, timeout_millis=None):
            return True

    import opentelemetry.exporter.otlp.proto.http.trace_exporter as otlp_mod
    monkeypatch.setattr(otlp_mod, "OTLPSpanExporter", _StubOTLP)

    record = TraceRecord(run_id="run-2", start_time=1.0, end_time=2.0)
    record.spans = [TraceSpan(action="retrieve", start_time=1.0, end_time=2.0, span_id="s1", success=True)]

    ok = phoenix_exporter.export_trace_to_phoenix(
        record, enabled=True, endpoint="http://localhost:6006/v1/traces", project_name="test",
    )
    assert ok is True
    assert len(captured.get_finished_spans()) == 2  # root + retrieve
