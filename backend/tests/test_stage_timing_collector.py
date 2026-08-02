"""Stage-timing collector and its projection onto PipelineTraceStep.

The frontend used to derive startedAt/endedAt/duration/offset by diffing
consecutive stream events. That pushes calendar arithmetic into the render
layer for no good reason — the backend already knows precisely when each
stage started and ended. This module tests the piece that captures that
information at emit time and hands it to the trace builder.
"""
from __future__ import annotations

from backend.app.models.schemas import PipelineTraceStep
from backend.app.services.pipeline_trace_builder import _apply_stage_timing
from backend.app.services.progress import (
    StageTimingCollector,
    emit_stage,
    reset_stage_timing_collector,
    set_stage_timing_collector,
)


def test_collector_records_first_running_and_last_terminal():
    """A stage that fires running → completed keeps the first running ts and
    the last terminal ts. Re-firing running is not supposed to reset the start;
    real pipelines occasionally fire a duplicate 'running' when a supervisor
    retries a branch, and we want the original wall-clock start to stick."""
    c = StageTimingCollector()
    c.record(stage_key="retrieval_initial", status="running", timestamp="2026-08-02T10:00:00+00:00")
    c.record(stage_key="retrieval_initial", status="running", timestamp="2026-08-02T10:00:00.500+00:00")
    c.record(stage_key="retrieval_initial", status="completed", timestamp="2026-08-02T10:00:03+00:00")
    entry = c.get("retrieval_initial")
    assert entry is not None
    assert entry.started_at == "2026-08-02T10:00:00+00:00"
    assert entry.ended_at == "2026-08-02T10:00:03+00:00"
    assert entry.final_status == "completed"


def test_collector_terminal_without_running_still_gets_start():
    """Emitters that only fire terminal events (e.g. a synthetic 'skipped'
    stage) should still leave a non-null started_at so the frontend has a
    single time to anchor them on the timeline. The event time is used for
    both endpoints."""
    c = StageTimingCollector()
    c.record(stage_key="question_resolution", status="skipped", timestamp="2026-08-02T10:00:05+00:00")
    entry = c.get("question_resolution")
    assert entry.started_at == "2026-08-02T10:00:05+00:00"
    assert entry.ended_at == "2026-08-02T10:00:05+00:00"


def test_emit_stage_hooks_into_collector():
    """emit_stage must record into whatever collector is currently installed
    on the ContextVar; multiple concurrent requests each installing their own
    collector must not see cross-talk (guaranteed by ContextVar semantics)."""
    collector = StageTimingCollector()
    token = set_stage_timing_collector(collector)
    try:
        emit_stage(stage_key="s1", title="t", status="running", summary="")
        emit_stage(stage_key="s1", title="t", status="completed", summary="")
    finally:
        reset_stage_timing_collector(token)
    entry = collector.get("s1")
    assert entry is not None
    assert entry.started_at is not None
    assert entry.ended_at is not None


def test_apply_timing_computes_offset_and_duration():
    """The trace builder projects raw ISO timestamps onto steps as ms integers
    relative to the run's t=0. Steps that had no stage event fired for them
    (e.g. the synthetic input_received row) collapse to zero-duration markers
    anchored at the run start — otherwise they render as a null bar and users
    are left wondering whether the stage ran at all."""
    c = StageTimingCollector()
    c.record(stage_key="retrieval_initial", status="running", timestamp="2026-08-02T10:00:00+00:00")
    c.record(stage_key="retrieval_initial", status="completed", timestamp="2026-08-02T10:00:03+00:00")
    c.record(stage_key="verdict", status="running", timestamp="2026-08-02T10:00:05+00:00")
    c.record(stage_key="verdict", status="completed", timestamp="2026-08-02T10:00:07+00:00")

    steps = [
        # synthetic step (never emitted): should be pinned at t=0 with 0ms
        PipelineTraceStep(stage_key="input_received", title="接收输入", summary="s"),
        PipelineTraceStep(stage_key="retrieval_initial", title="首轮检索", summary="s"),
        PipelineTraceStep(stage_key="verdict", title="综合判断", summary="s"),
    ]
    _apply_stage_timing(steps, c)

    assert steps[0].offset_ms == 0
    assert steps[0].duration_ms == 0
    assert steps[1].offset_ms == 0
    assert steps[1].duration_ms == 3000
    assert steps[2].offset_ms == 5000
    assert steps[2].duration_ms == 2000


def test_apply_timing_is_a_noop_when_collector_absent():
    """Replay corpora and mock traces do not install a collector; the builder
    must degrade gracefully so those paths keep working."""
    steps = [PipelineTraceStep(stage_key="s", title="t", summary="")]
    _apply_stage_timing(steps, None)
    assert steps[0].offset_ms is None
    assert steps[0].duration_ms is None
