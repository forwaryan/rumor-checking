"""Offline integration checks for request traces across pipeline execution paths."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
from types import SimpleNamespace

import pytest

from backend.app.agent.multi import AgentConfig, AgentRole, AgentStatus, SubAgentResult
from backend.app.agent.multi.supervisor import Supervisor
from backend.app.agent.runner import AgentRunner
from backend.app.agent.state import AgentState
from backend.app.agent.trace import TraceExporter, get_current_parent, get_current_trace
from backend.app.core.config import get_settings
from backend.app.models.schemas import AnalyzeRequest
from backend.app.services.analyze_pipeline import AnalyzePipeline
from backend.app.services.model_call_observer import observe_model_call


@pytest.fixture
def traced_pipeline(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_TRACE_ENABLED", "true")
    monkeypatch.setenv("AGENT_TRACE_DIR", str(tmp_path / "traces"))
    monkeypatch.setenv("MODEL_LEDGER_ENABLED", "false")
    monkeypatch.setenv("PHOENIX_ENABLED", "false")
    monkeypatch.setenv("AGENT_CHECKPOINT_ENABLED", "false")
    monkeypatch.setenv("VERDICT_CACHE_ENABLED", "false")
    get_settings.cache_clear()
    return AnalyzePipeline()


def _observe(settings, model="synthetic-model"):
    observation = observe_model_call(
        settings=settings, provider="test", model=model, stage_key="synthetic",
        request={"model": model, "messages": [{"role": "user", "content": "synthetic request"}]},
    )
    with observation:
        observation.response({
            "choices": [{"message": {"content": "synthetic response"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        }, status_code=200)
    return observation


def _request(run_id, *, mode="fast"):
    return AnalyzeRequest(
        raw_input="海边城市新增一条公交线路", input_type="text",
        request_context={"run_id": run_id, "mode": mode},
    )


def _read_trace(pipeline, run_id):
    return json.loads((pipeline.settings.agent_trace_dir / f"{run_id}.json").read_text())


def test_fixed_pipeline_exports_observed_request_with_run_context(traced_pipeline, monkeypatch):
    pipeline = traced_pipeline
    normalize = pipeline.input_normalizer.normalize
    observations = []

    def observed_normalize(request):
        observations.append(_observe(pipeline.settings))
        assert request.request_context["run_id"] == observations[-1].run_id
        return normalize(request)

    monkeypatch.setattr(pipeline.input_normalizer, "normalize", observed_normalize)
    report = pipeline.analyze(_request("fixed-run"))
    assert report is not None
    trace = _read_trace(pipeline, "fixed-run")
    assert trace["run_id"] == "fixed-run"
    assert trace["total_tokens"] == 14
    llm = [span for span in trace["spans"] if span["metadata"].get("span_kind") == "LLM"]
    assert len(llm) == 1
    assert llm[0]["metadata"]["call_id"] == observations[0].call_id
    assert llm[0]["success"] is True
    assert llm[0]["parent_span_id"] is None
    assert get_current_trace() is None
    assert get_current_parent() is None
    serialized = json.dumps(trace)
    assert "synthetic request" not in serialized
    assert "synthetic response" not in serialized


def test_trace_export_failure_preserves_original_pipeline_exception(traced_pipeline, monkeypatch, caplog):
    pipeline = traced_pipeline
    original_error = ValueError("synthetic analysis failure")
    attempted = []

    def fail_normalize(request):
        _observe(pipeline.settings)
        raise original_error

    def fail_export(exporter, path):
        attempted.append(exporter.record)
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(pipeline.input_normalizer, "normalize", fail_normalize)
    monkeypatch.setattr(TraceExporter, "export_to_file", fail_export)
    with pytest.raises(ValueError) as caught:
        pipeline.analyze(_request("failed-run"))
    assert caught.value is original_error
    assert len(attempted) == 1
    assert attempted[0].run_id == "failed-run"
    assert attempted[0].total_tokens == 14
    assert "agent_trace_export_failed" in caplog.text
    assert get_current_trace() is None


def test_concurrent_pipeline_runs_keep_separate_traces(traced_pipeline, monkeypatch):
    pipelines = [traced_pipeline, AnalyzePipeline()]
    barrier = Barrier(2)

    def install(pipeline, run_id):
        normalize = pipeline.input_normalizer.normalize

        def observed_normalize(request):
            exporter = get_current_trace()
            barrier.wait(timeout=5)
            observed = _observe(pipeline.settings, model=run_id)
            assert observed.run_id == run_id
            assert get_current_trace() is exporter
            return normalize(request)

        monkeypatch.setattr(pipeline.input_normalizer, "normalize", observed_normalize)

    for index, pipeline in enumerate(pipelines):
        install(pipeline, f"parallel-{index}")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(pipeline.analyze, _request(f"parallel-{index}"))
                   for index, pipeline in enumerate(pipelines)]
        assert all(future.result() is not None for future in futures)
    call_ids = []
    for index, pipeline in enumerate(pipelines):
        trace = _read_trace(pipeline, f"parallel-{index}")
        llm = [span for span in trace["spans"] if span["metadata"].get("span_kind") == "LLM"]
        assert len(llm) == 1
        assert llm[0]["metadata"]["model"] == f"parallel-{index}"
        assert trace["total_tokens"] == 14
        call_ids.append(llm[0]["metadata"]["call_id"])
    assert len(set(call_ids)) == 2
    assert get_current_trace() is None


def test_parallel_supervisor_llm_spans_keep_agent_parent_and_failure(traced_pipeline, monkeypatch):
    exporter = TraceExporter("supervisor-run")
    agents = [SimpleNamespace(role=role, config=AgentConfig())
              for role in (AgentRole.ANALYSIS, AgentRole.CRITIC)]
    supervisor = Supervisor(
        SimpleNamespace(settings=traced_pipeline.settings), agents=agents,
        max_parallel=2, trace_exporter=exporter,
    )
    barrier = Barrier(2)

    def run_agent(agent, state, deadline):
        barrier.wait(timeout=5)
        _observe(traced_pipeline.settings, model=agent.role.value)
        failed = agent.role == AgentRole.CRITIC
        return SubAgentResult(
            role=agent.role, status=AgentStatus.FAILED if failed else AgentStatus.COMPLETED,
            error="synthetic agent failure" if failed else None,
        )

    def run_impl(request, run_id):
        return supervisor._execute_batch_impl(agents, AgentState(request=request), None)

    monkeypatch.setattr(supervisor, "_run_agent_impl", run_agent)
    monkeypatch.setattr(supervisor, "_run_impl", run_impl)
    results = supervisor.run(_request("supervisor-run"), run_id="supervisor-run")
    assert len(results) == 2
    spans = {span.action: span for span in exporter.record.spans if span.metadata.get("span_kind") != "LLM"}
    root = spans["supervisor.run"]
    for span in exporter.record.spans:
        if span.metadata.get("span_kind") == "LLM":
            parent = spans[f"agent.{span.metadata['model']}"]
            assert span.parent_span_id == parent.span_id
            assert parent.parent_span_id == root.span_id
    assert spans["agent.analysis"].success is True
    assert spans["agent.critic"].success is False
    assert spans["agent.critic"].error_message == "synthetic agent failure"
    assert exporter.record.total_tokens == 28
    assert get_current_trace() is None


@pytest.mark.parametrize("multi_agent", [False, True])
def test_agent_fallback_keeps_one_trace_and_exports_once(traced_pipeline, monkeypatch, multi_agent):
    pipeline = traced_pipeline
    pipeline.settings = replace(
        pipeline.settings, agent_orchestrator_enabled=True, multi_agent_enabled=multi_agent,
    )
    run_id = f"fallback-{multi_agent}"
    normalize = pipeline.input_normalizer.normalize
    export = pipeline._export_trace
    exports = []
    observed_exporters = []

    def fail_agent(*args, **kwargs):
        observed_exporters.append(get_current_trace())
        _observe(pipeline.settings, model="agent-attempt")
        raise RuntimeError("synthetic agent failure")

    def observed_normalize(request):
        observed_exporters.append(get_current_trace())
        _observe(pipeline.settings, model="fixed-fallback")
        return normalize(request)

    def capture_export(exporter):
        exports.append(exporter)
        return export(exporter)

    monkeypatch.setattr(Supervisor, "_run_impl", fail_agent)
    monkeypatch.setattr(AgentRunner, "run", fail_agent)
    monkeypatch.setattr(pipeline.input_normalizer, "normalize", observed_normalize)
    monkeypatch.setattr(pipeline, "_export_trace", capture_export)
    assert pipeline.analyze(_request(run_id, mode="deep")) is not None
    assert len(observed_exporters) == 2
    assert observed_exporters[0] is observed_exporters[1]
    assert exports == [observed_exporters[0]]
    trace = _read_trace(pipeline, run_id)
    llm = [span for span in trace["spans"] if span["metadata"].get("span_kind") == "LLM"]
    assert [span["metadata"]["model"] for span in llm] == ["agent-attempt", "fixed-fallback"]
    assert trace["total_tokens"] == 28
    assert get_current_trace() is None


@pytest.mark.parametrize("run_id", ["../outside", "/tmp/outside", "private input with spaces", "x" * 129])
def test_trace_run_identity_cannot_be_used_as_a_file_path(traced_pipeline, monkeypatch, run_id):
    pipeline = traced_pipeline
    monkeypatch.setattr(pipeline, "_analyze_with_cache", lambda request: request.request_context["run_id"])
    safe_id = pipeline.analyze(_request(run_id))
    assert len(safe_id) == 32 and safe_id.isalnum()
    assert (pipeline.settings.agent_trace_dir / f"{safe_id}.json").is_file()
