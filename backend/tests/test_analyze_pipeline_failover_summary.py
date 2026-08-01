"""Tests for the per-run failover summary the pipeline emits.

The registry is process-wide and never resets, so the pipeline snapshots it on
entry, runs the analysis, and diff-emits at the end — attributing failover
activity to a single run. These tests exercise only that summary layer (the
_emit_failover_summary method), so they never touch the LLM/retrieval path."""
from __future__ import annotations

from backend.app.services import progress
from backend.app.services.analyze_pipeline import AnalyzePipeline


def _capture_events(fn) -> list[dict]:
    events: list[dict] = []
    token = progress.set_progress_callback(events.append)
    try:
        fn()
    finally:
        progress.reset_progress_callback(token)
    return events


def _summary_events(events: list[dict]) -> list[dict]:
    return [e for e in events if e.get("type") == "log" and e.get("title") == "模型健康 (本次)"]


def test_summary_emitted_on_failures_this_run():
    pipeline = AnalyzePipeline()
    diffs = {
        "fast-a": {"failures": 2, "successes": 0, "evictions": 0},
        "fast-b": {"failures": 0, "successes": 1, "evictions": 0},
    }
    events = _capture_events(lambda: pipeline._emit_failover_summary(diffs))
    summaries = _summary_events(events)
    assert len(summaries) == 1
    assert "2 次模型失败" in summaries[0]["summary"]
    # Details name each model with its counter breakdown.
    joined = "\n".join(summaries[0]["details"])
    assert "fast-a" in joined and "fast-b" in joined
    # No eviction this run -> info-level, not a warning.
    assert summaries[0]["level"] == "info"


def test_summary_uses_warning_level_when_a_model_was_evicted():
    pipeline = AnalyzePipeline()
    diffs = {"fast-a": {"failures": 3, "successes": 0, "evictions": 1}}
    events = _capture_events(lambda: pipeline._emit_failover_summary(diffs))
    summaries = _summary_events(events)
    assert summaries[0]["level"] == "warning"
    assert "1 次模型驱逐" in summaries[0]["summary"]


def test_summary_skipped_when_diff_is_empty():
    # Steady-state run: registry unchanged -> silent, not a spammy "0 failures" line.
    pipeline = AnalyzePipeline()
    events = _capture_events(lambda: pipeline._emit_failover_summary({}))
    assert _summary_events(events) == []


def test_summary_skipped_when_only_successes_recorded():
    # Every candidate answered on first try — no failover activity worth surfacing.
    pipeline = AnalyzePipeline()
    diffs = {"fast-a": {"failures": 0, "successes": 3, "evictions": 0}}
    events = _capture_events(lambda: pipeline._emit_failover_summary(diffs))
    assert _summary_events(events) == []


def test_summary_pinned_to_report_build_stage():
    # The trace UI groups events by stage_key — the summary belongs on the report
    # build stage so it appears at the end of the timeline where users look.
    pipeline = AnalyzePipeline()
    diffs = {"fast-a": {"failures": 1, "successes": 0, "evictions": 0}}
    events = _capture_events(lambda: pipeline._emit_failover_summary(diffs))
    assert _summary_events(events)[0]["stage_key"] == "report_build"


def test_analyze_error_propagates_verbatim_through_observability(monkeypatch):
    # The registry snapshot / emit wrapper must never mask the underlying error
    # from _analyze_uncached — if it does, incident triage sees "summary broken"
    # instead of the real bug that fired. We simulate the real failure by making
    # _analyze_uncached raise, and simultaneously the emit raise, and assert the
    # ORIGINAL exception is what surfaces.
    pipeline = AnalyzePipeline()
    original = RuntimeError("pipeline exploded")

    def boom_analyze(request):
        raise original

    def boom_emit(_diffs):
        raise RuntimeError("progress callback died")

    monkeypatch.setattr(pipeline, "_analyze_uncached", boom_analyze)
    monkeypatch.setattr(pipeline, "_emit_failover_summary", boom_emit)

    import pytest

    from backend.app.models.schemas import AnalyzeRequest
    with pytest.raises(RuntimeError) as excinfo:
        pipeline._run_with_failover_summary(AnalyzeRequest(raw_input="x", input_type="text"))
    assert excinfo.value is original  # original error, NOT "progress callback died"


def test_analyze_success_survives_observability_error(monkeypatch):
    # Symmetric case: analysis succeeded, but the emit stage happens to raise —
    # the successful report must still return, because failing an analysis just
    # because the dashboard log broke would be its own outage.
    pipeline = AnalyzePipeline()

    from backend.app.models.schemas import AnalyzeRequest, Report

    fake_report = Report.model_construct()  # minimal stub — we only care it's returned as-is

    monkeypatch.setattr(pipeline, "_analyze_uncached", lambda _r: fake_report)
    monkeypatch.setattr(pipeline, "_emit_failover_summary",
                        lambda _d: (_ for _ in ()).throw(RuntimeError("emit boom")))

    out = pipeline._run_with_failover_summary(AnalyzeRequest(raw_input="x", input_type="text"))
    assert out is fake_report
