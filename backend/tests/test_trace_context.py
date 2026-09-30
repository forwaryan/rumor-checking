"""Request tracing preserves context and counts each provider token once."""
from asyncio import CancelledError
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from threading import Barrier
from types import SimpleNamespace

import pytest

from backend.app.agent.trace import (
    TraceExporter,
    get_current_parent,
    get_current_trace,
)
from backend.app.services.phoenix_exporter import span_attributes


def test_trace_bindings_restore_nested_runs_and_explicit_root():
    first, second = TraceExporter("first"), TraceExporter("second")
    assert get_current_trace() is None
    with first.span("outer") as outer:
        assert get_current_trace() is first
        assert get_current_parent() is outer
        with second.activate():
            assert get_current_trace() is second
            assert get_current_parent() is None
            with second.span("inner") as inner:
                assert inner.parent_span_id is None
        assert get_current_parent() is outer
        with first.activate(parent=None):
            with first.span("explicit-root") as root:
                assert root.parent_span_id is None
        assert get_current_parent() is outer
        with pytest.raises(ValueError), first.span("failed"):
            raise ValueError("synthetic")
        assert get_current_parent() is outer
        with pytest.raises(CancelledError), first.span("cancelled"):
            raise CancelledError()
        assert get_current_parent() is outer
    assert get_current_trace() is None
    assert get_current_parent() is None


def test_parallel_workers_inherit_parent_without_interleaving_stacks():
    exporter = TraceExporter("parallel")
    barrier = Barrier(2)

    def worker(index):
        with exporter.span(f"worker-{index}") as child:
            barrier.wait(timeout=5)
            assert get_current_trace() is exporter
            assert get_current_parent() is child
            with exporter.span(f"request-{index}", span_kind="LLM") as request:
                assert request.parent_span_id == child.span_id
            return child

    with exporter.span("supervisor") as parent:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(copy_context().run, worker, index) for index in range(2)]
            children = [future.result() for future in futures]
        assert exporter.current_span() is parent
        assert all(child.parent_span_id == parent.span_id for child in children)
    assert len(exporter.record.spans) == 5
    assert len({span.span_id for span in exporter.record.spans}) == 5


def test_hook_subtracts_observed_llm_usage_and_keeps_unobserved_delta():
    exporter = TraceExporter("usage")
    state = SimpleNamespace(token_usage=SimpleNamespace(
        prompt_tokens=100, completion_tokens=20, total_tokens=120,
    ))
    ctx = SimpleNamespace(action="judge", state=state, outcome=SimpleNamespace(
        success=True, error_type=None, error_message=None,
    ))
    exporter.pre_hook(ctx)
    with exporter.span("nested") as nested:
        exporter.record_child_span(
            "llm.request", parent=nested, start_time=1, end_time=2, success=True,
            token_usage={"prompt": 10, "completion": 5, "total": 15}, span_kind="LLM",
        )
    state.token_usage = SimpleNamespace(prompt_tokens=120, completion_tokens=25, total_tokens=145)
    exporter.post_hook(ctx)
    assert exporter.record.total_tokens == 25
    assert exporter.record.spans[-1].token_usage == {"prompt": 10, "completion": 0, "total": 10}
    assert get_current_trace() is None


def test_failed_hook_cleans_binding_and_snapshot():
    exporter = TraceExporter("failed-hook")
    ctx = SimpleNamespace(action="judge", state=None, outcome=None)
    exporter.pre_hook(ctx)
    exporter.post_hook(ctx)
    assert get_current_trace() is None
    assert exporter.record.spans[0].error_type == "no_outcome"
    assert exporter._hook_usage.get() == ()


def test_root_llm_span_exports_model_status_and_provider_usage():
    exporter = TraceExporter("root-request")
    span = exporter.record_child_span(
        "llm.request", parent=None, start_time=1, end_time=2, success=False,
        error_type="rate_limit", token_usage={"prompt": 3, "completion": 0, "total": 3},
        span_kind="LLM", model="test-model", status_code=429,
    )
    attributes = span_attributes(span)
    assert span.parent_span_id is None
    assert attributes["openinference.span.kind"] == "LLM"
    assert attributes["llm.model_name"] == "test-model"
    assert attributes["http.response.status_code"] == 429
    assert attributes["llm.token_count.total"] == 3
    assert attributes["rumor_checking.success"] is False


@pytest.mark.parametrize("outcome", [None, True, False])
def test_completed_runs_leave_no_exporter_variables_in_long_lived_context(outcome):
    before = copy_context()
    for index in range(20):
        exporter = TraceExporter(f"transient-{index}")
        ctx = SimpleNamespace(action="judge", state=None, outcome=(
            None if outcome is None else SimpleNamespace(
                success=outcome, error_type=None, error_message=None,
            )
        ))
        with exporter.activate():
            with exporter.span("outer") as parent:
                exporter.pre_hook(ctx)
                with pytest.raises(ValueError), exporter.span("failed"):
                    raise ValueError("synthetic")
                exporter.post_hook(ctx)
                assert exporter.current_span() is parent
                assert exporter._hook_usage.get() == ()
            with pytest.raises(CancelledError), exporter.span("cancelled"):
                raise CancelledError()
        after = copy_context()
        assert exporter._frames not in after
        assert exporter._hook_usage not in after
        assert len(after) == len(before)
        assert set(after) == set(before)


def test_copied_worker_restores_inherited_frame_bindings():
    exporter = TraceExporter("inherited")
    ctx = SimpleNamespace(action="judge", state=None, outcome=None)
    with exporter.span("outer") as parent:
        exporter.pre_hook(ctx)
        inherited = copy_context()

        def worker():
            before = dict(copy_context().items())
            child_ctx = SimpleNamespace(action="child", state=None, outcome=None)
            exporter.pre_hook(child_ctx)
            with exporter.span("request"):
                pass
            exporter.post_hook(child_ctx)
            assert dict(copy_context().items()) == before

        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(inherited.run, worker).result()
        exporter.post_hook(ctx)
        assert exporter.current_span() is parent
    assert exporter._frames not in copy_context()
    assert exporter._hook_usage not in copy_context()


def test_activation_cleans_interrupted_hook_without_post_callback():
    before = dict(copy_context().items())
    exporter = TraceExporter("cancelled-hook")
    with pytest.raises(CancelledError), exporter.activate():
        exporter.pre_hook(SimpleNamespace(action="cancelled", state=None))
        raise CancelledError()
    assert dict(copy_context().items()) == before
    assert exporter.current_span() is None
    assert exporter._hook_usage.get() == ()
