"""Tests for checkpoint/resume system (P0)."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from backend.app.agent.checkpoint import (
    Checkpoint,
    DiskCheckpointStore,
    MemoryCheckpointStore,
    _deserialize_value,
    _serialize_value,
    restore_state,
    snapshot_state,
)
from backend.app.agent.state import AgentState, StepOutcome, TokenUsage
from backend.app.models.schemas import AnalyzeRequest, Event, NormalizedEvent, PossibilityItem, Report, ReportProvenance


def _fake_report():
    return Report(
        mode="complete_mode",
        event=Event(title="t", summary="s", source_name="n", source_url="",
                    source_type="text_news", published_at="2026-01-01", mode="complete_mode"),
        final_summary="summary",
        provenance=ReportProvenance(
            source_type="backend_live", event_source="input_normalized",
            claim_source="rule", evidence_source="none", timeline_source="none",
        ),
    )


# --- Serialization round-trip tests ---


def test_serialize_primitives():
    assert _serialize_value(None) is None
    assert _serialize_value(42) == 42
    assert _serialize_value("hello") == "hello"
    assert _serialize_value(True) is True
    assert _serialize_value(3.14) == 3.14


def test_serialize_containers():
    lst = [1, "a", None]
    assert _serialize_value(lst) == [1, "a", None]
    assert _deserialize_value([1, "a", None]) == [1, "a", None]

    tpl = (1, 2, 3)
    serialized = _serialize_value(tpl)
    assert serialized["__tuple__"] is True
    assert _deserialize_value(serialized) == (1, 2, 3)

    st = {"x", "y"}
    serialized = _serialize_value(st)
    assert serialized["__set__"] is True
    assert _deserialize_value(serialized) == {"x", "y"}


def test_serialize_dict():
    d = {"key": "value", "nested": {"a": 1}}
    assert _serialize_value(d) == {"key": "value", "nested": {"a": 1}}
    assert _deserialize_value({"key": "value", "nested": {"a": 1}}) == d


def test_serialize_pydantic_model():
    req = AnalyzeRequest(raw_input="test rumor")
    serialized = _serialize_value(req)
    assert "__pydantic__" in serialized
    restored = _deserialize_value(serialized)
    assert isinstance(restored, AnalyzeRequest)
    assert restored.raw_input == "test rumor"


def test_serialize_pydantic_normalized_event():
    event = NormalizedEvent(
        title="测试事件",
        summary="摘要",
        raw_input="raw",
        input_type="text_news",
        source_name="来源",
        source_url="https://example.com",
    )
    serialized = _serialize_value(event)
    restored = _deserialize_value(serialized)
    assert isinstance(restored, NormalizedEvent)
    assert restored.title == "测试事件"
    assert restored.input_type == "text_news"


def test_serialize_dataclass():
    usage = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150, call_count=2)
    serialized = _serialize_value(usage)
    assert "__dataclass__" in serialized
    restored = _deserialize_value(serialized)
    assert isinstance(restored, TokenUsage)
    assert restored.prompt_tokens == 100
    assert restored.call_count == 2


def test_serialize_step_outcome():
    outcome = StepOutcome(action="search_news", success=True, summary="ok")
    serialized = _serialize_value(outcome)
    restored = _deserialize_value(serialized)
    assert isinstance(restored, StepOutcome)
    assert restored.action == "search_news"
    assert restored.success is True


# --- Snapshot / Restore full state ---


def _make_state() -> AgentState:
    req = AnalyzeRequest(raw_input="拼多多在雄安买楼了吗")
    state = AgentState(request=req)
    state.done_actions = ["normalize", "search_news"]
    state.token_usage.add(prompt=100, completion=50)
    state.fetched_urls = {"https://a.com", "https://b.com"}
    state.fetched_bodies = {"r1": "body content"}
    state.normalized_event = NormalizedEvent(
        title="拼多多雄安买楼",
        summary="网传拼多多在雄安买楼",
        raw_input="拼多多在雄安买楼了吗",
        input_type="question_only",
        source_name="用户",
        source_url="",
    )
    return state


def test_snapshot_and_restore_roundtrip():
    state = _make_state()
    cp = snapshot_state(state, action="search_news", step_index=1)

    assert cp.step_index == 1
    assert cp.action == "search_news"
    assert cp.timestamp > 0

    restored = restore_state(cp)
    assert restored.request.raw_input == "拼多多在雄安买楼了吗"
    assert restored.done_actions == ["normalize", "search_news"]
    assert restored.token_usage.prompt_tokens == 100
    assert restored.token_usage.completion_tokens == 50
    assert restored.token_usage.call_count == 1
    assert restored.fetched_urls == {"https://a.com", "https://b.com"}
    assert restored.fetched_bodies == {"r1": "body content"}
    assert restored.normalized_event is not None
    assert restored.normalized_event.title == "拼多多雄安买楼"


def test_snapshot_empty_state():
    req = AnalyzeRequest(raw_input="test")
    state = AgentState(request=req)
    cp = snapshot_state(state, action="normalize", step_index=0)
    restored = restore_state(cp)
    assert restored.done_actions == []
    assert restored.normalized_event is None
    assert restored.token_usage.total_tokens == 0


# --- Checkpoint JSON serialization ---


def test_checkpoint_to_and_from_json():
    state = _make_state()
    cp = snapshot_state(state, action="search_news", step_index=1)

    json_str = cp.to_json()
    assert isinstance(json_str, str)
    parsed = json.loads(json_str)
    assert parsed["step_index"] == 1
    assert parsed["action"] == "search_news"

    restored_cp = Checkpoint.from_json(json_str)
    assert restored_cp.step_index == cp.step_index
    assert restored_cp.action == cp.action

    restored_state = restore_state(restored_cp)
    assert restored_state.done_actions == ["normalize", "search_news"]


# --- MemoryCheckpointStore ---


def test_memory_store_save_and_latest():
    store = MemoryCheckpointStore()
    state = _make_state()

    cp1 = snapshot_state(state, "normalize", 0)
    cp2 = snapshot_state(state, "search_news", 1)

    store.save("run-1", cp1)
    store.save("run-1", cp2)

    latest = store.latest("run-1")
    assert latest is not None
    assert latest.action == "search_news"
    assert latest.step_index == 1

    all_cps = store.all_checkpoints("run-1")
    assert len(all_cps) == 2


def test_memory_store_latest_returns_none_for_unknown():
    store = MemoryCheckpointStore()
    assert store.latest("nonexistent") is None


def test_memory_store_clear():
    store = MemoryCheckpointStore()
    state = _make_state()
    store.save("run-1", snapshot_state(state, "normalize", 0))
    store.clear("run-1")
    assert store.latest("run-1") is None


# --- DiskCheckpointStore ---


def test_disk_store_save_and_latest():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = DiskCheckpointStore(Path(tmpdir))
        state = _make_state()

        cp1 = snapshot_state(state, "normalize", 0)
        cp2 = snapshot_state(state, "search_news", 1)

        store.save("run-1", cp1)
        store.save("run-1", cp2)

        latest = store.latest("run-1")
        assert latest is not None
        assert latest.action == "search_news"

        all_cps = store.all_checkpoints("run-1")
        assert len(all_cps) == 2

        # Verify files on disk
        run_dir = Path(tmpdir) / "run-1"
        assert run_dir.exists()
        json_files = list(run_dir.glob("*.json"))
        assert len(json_files) == 2


def test_disk_store_clear():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = DiskCheckpointStore(Path(tmpdir))
        state = _make_state()
        store.save("run-1", snapshot_state(state, "normalize", 0))
        store.clear("run-1")
        assert store.latest("run-1") is None


def test_disk_store_survives_new_instance():
    with tempfile.TemporaryDirectory() as tmpdir:
        store1 = DiskCheckpointStore(Path(tmpdir))
        state = _make_state()
        store1.save("run-1", snapshot_state(state, "search_news", 1))

        store2 = DiskCheckpointStore(Path(tmpdir))
        latest = store2.latest("run-1")
        assert latest is not None
        assert latest.action == "search_news"
        restored = restore_state(latest)
        assert restored.done_actions == ["normalize", "search_news"]


# --- Runner integration (checkpoint is saved on success) ---


def test_runner_saves_checkpoints(monkeypatch):
    from backend.app.agent.runner import AgentRunner
    from backend.app.agent_tools.base import ToolContext

    # Minimal ToolContext mock
    class FakeSettings:
        agent_max_url_fetches = 0
        agent_max_token_budget = 0
        agent_tool_max_retries = 0

    class FakeReasoner:
        pass

    ctx = ToolContext(
        settings=FakeSettings(),
        input_normalizer=None,
        retriever=None,
        url_content_extractor=None,
        question_resolver=None,
        agent_reasoner=FakeReasoner(),
        provider_enricher=None,
        claim_extractor=None,
        verdict_engine=None,
        timeline_builder=None,
        report_builder=None,
        content_check_builder=None,
        pipeline_trace_builder=None,
    )

    store = MemoryCheckpointStore()
    runner = AgentRunner(ctx, checkpoint_store=store)

    # Patch tools to be no-ops and planner to run 2 steps then DONE
    step_count = {"n": 0}
    def fake_dispatch(action, state):
        step_count["n"] += 1
        if action == "finalize_report":
            state.report = _fake_report()

    actions_seq = ["normalize", "search_news", "finalize_report"]
    action_idx = {"i": 0}
    def fake_planner_next(state):
        from backend.app.agent import planner as p
        if action_idx["i"] >= len(actions_seq):
            return p.DONE
        a = actions_seq[action_idx["i"]]
        action_idx["i"] += 1
        return a

    monkeypatch.setattr(runner, "_dispatch", fake_dispatch)
    monkeypatch.setattr(runner.planner, "next_action", fake_planner_next)

    report = runner.run(AnalyzeRequest(raw_input="test"), run_id="test-run")
    assert report is not None

    # Verify checkpoints were saved
    all_cps = store.all_checkpoints("test-run")
    assert len(all_cps) == 3
    assert all_cps[0].action == "normalize"
    assert all_cps[1].action == "search_news"
    assert all_cps[2].action == "finalize_report"


def test_runner_resume_from_checkpoint(monkeypatch):
    from backend.app.agent.runner import AgentRunner
    from backend.app.agent_tools.base import ToolContext
    from backend.app.models.schemas import Report

    class FakeSettings:
        agent_max_url_fetches = 0
        agent_max_token_budget = 0
        agent_tool_max_retries = 0

    class FakeReasoner:
        pass

    ctx = ToolContext(
        settings=FakeSettings(),
        input_normalizer=None,
        retriever=None,
        url_content_extractor=None,
        question_resolver=None,
        agent_reasoner=FakeReasoner(),
        provider_enricher=None,
        claim_extractor=None,
        verdict_engine=None,
        timeline_builder=None,
        report_builder=None,
        content_check_builder=None,
        pipeline_trace_builder=None,
    )

    store = MemoryCheckpointStore()

    # Simulate a prior run that completed 2 steps then crashed
    state = AgentState(request=AnalyzeRequest(raw_input="test"))
    state.done_actions = ["normalize", "search_news"]
    state.normalized_event = NormalizedEvent(
        title="t", summary="s", raw_input="test",
        input_type="text_news", source_name="n", source_url="",
    )
    cp = snapshot_state(state, "search_news", 1)
    store.save("resume-run", cp)

    runner = AgentRunner(ctx, checkpoint_store=store)

    # Patch: after resume, next action should be whatever comes after search_news
    dispatched_actions = []
    def fake_dispatch(action, state):
        dispatched_actions.append(action)
        if action == "finalize_report":
            state.report = _fake_report()

    remaining_actions = ["resolve_question", "follow_up_retrieval", "finalize_report"]
    remaining_idx = {"i": 0}
    def fake_planner_next(state):
        from backend.app.agent import planner as p
        if remaining_idx["i"] >= len(remaining_actions):
            return p.DONE
        a = remaining_actions[remaining_idx["i"]]
        remaining_idx["i"] += 1
        return a

    monkeypatch.setattr(runner, "_dispatch", fake_dispatch)
    monkeypatch.setattr(runner.planner, "next_action", fake_planner_next)

    report = runner.resume("resume-run")
    assert report is not None
    # Should NOT have re-run normalize or search_news
    assert "normalize" not in dispatched_actions
    assert "search_news" not in dispatched_actions
    assert "finalize_report" in dispatched_actions


def test_runner_resume_raises_without_store():
    from backend.app.agent.runner import AgentRunner
    from backend.app.agent_tools.base import ToolContext

    class FakeSettings:
        agent_max_url_fetches = 0
        agent_max_token_budget = 0
        agent_tool_max_retries = 0

    ctx = ToolContext(
        settings=FakeSettings(),
        input_normalizer=None, retriever=None,
        url_content_extractor=None, question_resolver=None,
        agent_reasoner=object(), provider_enricher=None,
        claim_extractor=None, verdict_engine=None,
        timeline_builder=None, report_builder=None,
        content_check_builder=None, pipeline_trace_builder=None,
    )
    runner = AgentRunner(ctx)
    with pytest.raises(RuntimeError, match="cannot resume"):
        runner.resume("any-id")


def test_runner_resume_raises_on_missing_checkpoint():
    from backend.app.agent.runner import AgentRunner
    from backend.app.agent_tools.base import ToolContext

    class FakeSettings:
        agent_max_url_fetches = 0
        agent_max_token_budget = 0
        agent_tool_max_retries = 0

    ctx = ToolContext(
        settings=FakeSettings(),
        input_normalizer=None, retriever=None,
        url_content_extractor=None, question_resolver=None,
        agent_reasoner=object(), provider_enricher=None,
        claim_extractor=None, verdict_engine=None,
        timeline_builder=None, report_builder=None,
        content_check_builder=None, pipeline_trace_builder=None,
    )
    store = MemoryCheckpointStore()
    runner = AgentRunner(ctx, checkpoint_store=store)
    with pytest.raises(RuntimeError, match="no checkpoint found"):
        runner.resume("nonexistent-run")
