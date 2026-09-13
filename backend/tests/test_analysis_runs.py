from __future__ import annotations

import asyncio
import json
import multiprocessing
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from backend.app.agent.checkpoint import Checkpoint, DiskCheckpointStore
from backend.app.core.exceptions import AppError
from backend.app.models.schemas import AnalyzeRequest, Event, Report, ReportProvenance
from backend.app.services.analysis_runs import AnalysisRunManager
from backend.app.services.progress import emit_progress


def hold_run_lock(directory, run_id, channel):
    manager = AnalysisRunManager(directory)
    with manager._transaction():
        execution_lock = manager._try_execution_lock(run_id)
    channel.send(execution_lock is not None)
    try:
        channel.recv()
    finally:
        if execution_lock is not None:
            execution_lock.close()


def wait_for_released_lock(execution_lock):
    deadline = time.monotonic() + 5
    while not execution_lock.closed and time.monotonic() < deadline:
        time.sleep(0.01)
    assert execution_lock.closed


def sample_report() -> Report:
    return Report(
        mode="safe_mode",
        event=Event(title="待核实消息", summary="待核实", source_url="", source_name="用户", published_at="", keywords=[], mode="safe_mode"),
        final_summary="证据不足，不能判定真假。",
        overall_credibility_label="insufficient_evidence",
        provenance=ReportProvenance(source_type="backend_mock", event_source="input_normalized", claim_source="rule", evidence_source="none", timeline_source="none"),
    )


def wait_for_terminal(manager, run_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        run = manager.get(run_id)
        if run.status not in {"queued", "running"}:
            return run
        time.sleep(0.01)
    pytest.fail("analysis worker did not finish")


def test_disconnect_reconnect_does_not_repeat_pipeline_and_report_survives_restart(tmp_path):
    started, release = threading.Event(), threading.Event()
    requests = []

    def analyze(payload):
        requests.append(payload)
        emit_progress("log", summary="原始证据已读取")
        started.set()
        assert release.wait(5)
        return sample_report()

    manager = AnalysisRunManager(tmp_path, pipeline_factory=lambda: SimpleNamespace(analyze=analyze))
    request = AnalyzeRequest(raw_input="测试消息", request_context={"run_id": "caller-controlled", "mode": " DEEP "})
    run = manager.create(request)
    assert started.wait(5)
    assert requests[0].request_context["run_id"] == run.run_id != "caller-controlled"
    assert request.request_context["run_id"] == "caller-controlled"
    assert run.mode == "deep"

    async def disconnect():
        stream = manager.events(run.run_id)
        first = json.loads(await anext(stream))
        await stream.aclose()
        return first

    first = asyncio.run(disconnect())
    assert first["event_id"] == 1
    second_manager = AnalysisRunManager(tmp_path)
    assert second_manager.get(run.run_id).status == "running"
    assert second_manager.resume(run.run_id).status == "running"
    release.set()
    terminal = wait_for_terminal(manager, run.run_id)
    assert terminal.status == "completed"
    assert terminal.report.overall_credibility_label == "insufficient_evidence"

    async def reconnect():
        return [json.loads(line) async for line in second_manager.events(run.run_id, after=first["event_id"])]

    remaining = asyncio.run(reconnect())
    assert [first["event_id"], *[entry["event_id"] for entry in remaining]] == list(range(1, terminal.last_event_id + 1))
    assert remaining[-2]["event"]["report"] == sample_report().model_dump(mode="json")
    assert remaining[-1]["event"]["success"] is True
    assert second_manager.get(run.run_id).report == sample_report()
    assert second_manager.resume(run.run_id).status == "completed"
    assert len(requests) == 1


def test_lease_expiry_concurrent_resume_preserves_id_and_fences_previous_owner(tmp_path, monkeypatch):
    now = [1000.0]
    manager = AnalysisRunManager(tmp_path, clock=lambda: now[0], lease_seconds=30)
    launches = []
    monkeypatch.setattr(manager, "_launch", lambda run_id, owner, execution_lock: launches.append((run_id, owner, execution_lock)))
    run = manager.create(AnalyzeRequest(raw_input="原始请求", request_context={"mode": "deep"}))
    old_owner = launches[0][1]
    manager._push(run.run_id, old_owner, {"type": "log", "summary": "中断前的进度"})
    launches[0][2].close()
    now[0] += 31
    assert manager.get(run.run_id).status == "interrupted"
    assert manager.get(run.run_id).resumable
    other = AnalysisRunManager(tmp_path, clock=lambda: now[0])
    monkeypatch.setattr(other, "_launch", lambda run_id, owner, execution_lock: launches.append((run_id, owner, execution_lock)))
    with ThreadPoolExecutor(max_workers=8) as executor:
        resumed = list(executor.map(lambda index: (manager if index % 2 else other).resume(run.run_id), range(8)))
    assert {item.run_id for item in resumed} == {run.run_id}
    assert len(launches) == 2
    with pytest.raises(RuntimeError, match="lease lost"):
        manager._push(run.run_id, old_owner, {"type": "log", "summary": "过期写入"})
    manager._finish(run.run_id, old_owner, report=sample_report())
    assert manager.get(run.run_id).status == "queued"
    seen = []
    manager.pipeline_factory = lambda: SimpleNamespace(analyze=lambda payload: seen.append(payload) or sample_report())
    manager._worker(run.run_id, launches[-1][1], launches[-1][2])
    assert seen[0].raw_input == "原始请求"
    assert seen[0].request_context["run_id"] == run.run_id
    events, terminal = manager.event_page(run.run_id, 0)
    assert terminal.status == "completed"
    assert [entry["event_id"] for entry in events] == list(range(1, terminal.last_event_id + 1))
    assert events[0]["event"]["summary"] == "中断前的进度"


def test_lease_renewal_keeps_silent_pipeline_active(tmp_path):
    started, release = threading.Event(), threading.Event()

    def analyze(payload):
        started.set()
        assert release.wait(5)
        return sample_report()

    manager = AnalysisRunManager(tmp_path, lease_seconds=0.3, pipeline_factory=lambda: SimpleNamespace(analyze=analyze))
    run = manager.create(AnalyzeRequest(raw_input="slow"))
    assert started.wait(5)
    time.sleep(0.5)
    try:
        assert AnalysisRunManager(tmp_path).get(run.run_id).status == "running"
    finally:
        release.set()
    assert wait_for_terminal(manager, run.run_id).status == "completed"


@pytest.mark.parametrize("failure", [
    RuntimeError("secret-token internal.example"),
    AppError(status_code=503, code="private-provider-token", message="secret-token internal.example", details={"key": "secret"}),
])
def test_failure_finishes_safely_and_cannot_be_resumed(tmp_path, failure):
    def analyze(payload):
        raise failure

    manager = AnalysisRunManager(tmp_path, pipeline_factory=lambda: SimpleNamespace(analyze=analyze))
    run = manager.create(AnalyzeRequest(raw_input="错误测试"))
    terminal = wait_for_terminal(manager, run.run_id)
    events, _ = manager.event_page(run.run_id, 0)
    assert terminal.status == "failed"
    assert not terminal.resumable
    assert terminal.report is None
    assert events[-2]["event"]["type"] == "error"
    assert events[-1]["event"]["success"] is False
    serialized = terminal.model_dump_json() + json.dumps(events)
    assert "secret" not in serialized
    assert "internal.example" not in serialized
    assert "private-provider" not in serialized
    with pytest.raises(AppError) as error:
        manager.resume(run.run_id)
    assert error.value.status_code == 409


def test_capacity_and_retention_cleanup_protect_active_runs(tmp_path, monkeypatch):
    now = [1000.0]
    manager = AnalysisRunManager(tmp_path, max_active=1, retention_seconds=10, lease_seconds=100, clock=lambda: now[0])
    owners = {}
    monkeypatch.setattr(manager, "_launch", lambda run_id, owner, execution_lock: (owners.update({run_id: owner}), execution_lock.close()))
    run = manager.create(AnalyzeRequest(raw_input="first"))
    manager._push(run.run_id, owners[run.run_id], {"type": "log"})
    now[0] += 11
    assert manager.get(run.run_id).status == "queued"
    with pytest.raises(AppError) as error:
        manager.create(AnalyzeRequest(raw_input="second"))
    assert error.value.status_code == 429
    manager._finish(run.run_id, owners[run.run_id], report=sample_report())
    next_run = manager.create(AnalyzeRequest(raw_input="second"))
    now[0] += 11
    with pytest.raises(AppError) as error:
        manager.get(run.run_id)
    assert error.value.status_code == 404
    assert manager.get(next_run.run_id).status == "queued"
    with manager._connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM events WHERE run_id=?", (run.run_id,)).fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM runs WHERE run_id=?", (run.run_id,)).fetchone()[0] == 0


def test_resume_obeys_shared_capacity(tmp_path, monkeypatch):
    now = [1000.0]
    manager = AnalysisRunManager(tmp_path, max_active=1, clock=lambda: now[0])
    monkeypatch.setattr(manager, "_launch", lambda run_id, owner, execution_lock: execution_lock.close())
    interrupted = manager.create(AnalyzeRequest(raw_input="first"))
    now[0] += 31
    manager.create(AnalyzeRequest(raw_input="second"))
    with pytest.raises(AppError) as error:
        manager.resume(interrupted.run_id)
    assert error.value.status_code == 429
    with manager._transaction():
        execution_lock = manager._try_execution_lock(interrupted.run_id)
        assert execution_lock is not None
        execution_lock.close()


def test_concurrent_creation_obeys_database_capacity(tmp_path, monkeypatch):
    manager = AnalysisRunManager(tmp_path, max_active=2)
    monkeypatch.setattr(manager, "_launch", lambda run_id, owner, execution_lock: execution_lock.close())

    def create(index):
        try:
            return manager.create(AnalyzeRequest(raw_input=str(index))).run_id
        except AppError as exc:
            assert exc.status_code == 429
            return None

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(create, range(8)))
    assert len({run_id for run_id in results if run_id}) == 2
    assert results.count(None) == 6


def test_event_pagination_replays_all_events_in_order(tmp_path, monkeypatch):
    manager = AnalysisRunManager(tmp_path)
    owners = []
    monkeypatch.setattr(manager, "_launch", lambda run_id, owner, execution_lock: (owners.append(owner), execution_lock.close()))
    run = manager.create(AnalyzeRequest(raw_input="many events"))
    with manager._transaction() as connection:
        for index in range(405):
            manager._append(connection, run.run_id, {"type": "log", "index": index})
    manager._finish(run.run_id, owners[0], report=sample_report())

    async def read_all():
        return [json.loads(line) async for line in manager.events(run.run_id)]

    events = asyncio.run(read_all())
    assert [entry["event_id"] for entry in events] == list(range(1, 408))


@pytest.mark.parametrize("enabled", [True, False])
def test_experience_recording_is_optional_and_cannot_fail_analysis(tmp_path, monkeypatch, enabled):
    calls = []

    def record(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("experience store unavailable")

    monkeypatch.setattr("backend.app.services.analysis_runs.record_checking_experience", record)
    monkeypatch.setattr("backend.app.services.analysis_runs.get_settings", lambda: SimpleNamespace(
        agent_playbooks_enabled=enabled, analysis_run_dir=tmp_path, agent_playbook_dir=tmp_path / "playbooks",
    ))
    manager = AnalysisRunManager(tmp_path, pipeline_factory=lambda: SimpleNamespace(analyze=lambda payload: sample_report()))
    run = manager.create(AnalyzeRequest(raw_input="policy test"))
    assert wait_for_terminal(manager, run.run_id).status == "completed"
    assert len(calls) == int(enabled)
    if enabled:
        assert calls[0]["run_id"] == run.run_id
        assert calls[0]["raw_input"] == "policy test"
        assert calls[0]["report"] == sample_report()
        assert calls[0]["output_dir"] == tmp_path / "experience"


def test_old_pipeline_cannot_overlap_resumed_checkpoint_writer(tmp_path, monkeypatch):
    now = [1000.0]
    started, release = threading.Event(), threading.Event()
    checkpoints = DiskCheckpointStore(tmp_path / "checkpoints")
    write_order = []
    handles = []

    def old_pipeline(payload):
        checkpoints.save(payload.request_context["run_id"], Checkpoint(1, "retrieve", now[0], {"generation": "old-start"}))
        started.set()
        assert release.wait(5)
        checkpoints.save(payload.request_context["run_id"], Checkpoint(1, "retrieve", now[0], {"generation": "old-late"}))
        write_order.append("old")
        return sample_report()

    def new_pipeline(payload):
        checkpoints.save(payload.request_context["run_id"], Checkpoint(1, "retrieve", now[0], {"generation": "new"}))
        write_order.append("new")
        return sample_report()

    manager = AnalysisRunManager(tmp_path, clock=lambda: now[0], pipeline_factory=lambda: SimpleNamespace(analyze=old_pipeline))
    original_launch = manager._launch

    def capture_launch(run_id, owner, execution_lock):
        handles.append(execution_lock)
        original_launch(run_id, owner, execution_lock)

    monkeypatch.setattr(manager, "_launch", capture_launch)
    run = manager.create(AnalyzeRequest(raw_input="checkpoint race"))
    assert started.wait(5)
    replacement = AnalysisRunManager(tmp_path, max_active=1, clock=lambda: now[0], pipeline_factory=lambda: SimpleNamespace(analyze=new_pipeline))
    now[0] += 31
    try:
        assert replacement.get(run.run_id).status == "interrupted"
        with pytest.raises(AppError) as error:
            replacement.resume(run.run_id)
        assert error.value.status_code == 409
        assert error.value.code == "run_still_executing"
        assert checkpoints.latest(run.run_id).state_data["generation"] == "old-start"
        assert write_order == []
    finally:
        release.set()
    wait_for_released_lock(handles[0])
    assert checkpoints.latest(run.run_id).state_data["generation"] == "old-late"
    replacement.resume(run.run_id)
    assert wait_for_terminal(replacement, run.run_id).status == "completed"
    assert write_order == ["old", "new"]
    assert checkpoints.latest(run.run_id).state_data["generation"] == "new"


def test_process_death_releases_execution_lock_for_resume(tmp_path, monkeypatch):
    now = [1000.0]
    manager = AnalysisRunManager(tmp_path, clock=lambda: now[0], pipeline_factory=lambda: SimpleNamespace(analyze=lambda payload: sample_report()))
    launch = manager._launch
    monkeypatch.setattr(manager, "_launch", lambda run_id, owner, execution_lock: execution_lock.close())
    run = manager.create(AnalyzeRequest(raw_input="process crash"))
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe()
    process = context.Process(target=hold_run_lock, args=(tmp_path, run.run_id, sender))
    process.start()
    try:
        assert receiver.poll(10)
        assert receiver.recv()
        now[0] += 31
        with pytest.raises(AppError) as error:
            manager.resume(run.run_id)
        assert error.value.code == "run_still_executing"
    finally:
        process.terminate()
        process.join(5)
        receiver.close()
        sender.close()
    assert not process.is_alive()
    monkeypatch.setattr(manager, "_launch", launch)
    manager.resume(run.run_id)
    assert wait_for_terminal(manager, run.run_id).status == "completed"


def test_ttl_and_capacity_preserve_expired_but_executing_run(tmp_path, monkeypatch):
    now = [1000.0]
    handles = []
    manager = AnalysisRunManager(tmp_path, retention_seconds=10, max_active=1, clock=lambda: now[0])
    monkeypatch.setattr(manager, "_launch", lambda run_id, owner, execution_lock: handles.append(execution_lock))
    run = manager.create(AnalyzeRequest(raw_input="paused process"))
    lock_path = manager.lock_directory / f"{run.run_id}.lock"
    now[0] += 31
    try:
        assert manager.get(run.run_id).status == "interrupted"
        assert lock_path.exists()
        with pytest.raises(AppError) as error:
            manager.create(AnalyzeRequest(raw_input="new run"))
        assert error.value.status_code == 429
        with pytest.raises(AppError) as error:
            manager.resume(run.run_id)
        assert error.value.code == "run_still_executing"
        assert lock_path.exists()
    finally:
        handles[0].close()
    with pytest.raises(AppError) as error:
        manager.get(run.run_id)
    assert error.value.status_code == 404
    assert not lock_path.exists()


def test_worker_start_failure_releases_execution_lock(tmp_path, monkeypatch):
    def fail_start():
        raise RuntimeError("thread unavailable")

    monkeypatch.setattr("backend.app.services.analysis_runs.Thread", lambda **kwargs: SimpleNamespace(start=fail_start))
    manager = AnalysisRunManager(tmp_path)
    run = manager.create(AnalyzeRequest(raw_input="start failure"))
    assert manager.get(run.run_id).status == "failed"
    with manager._transaction():
        execution_lock = manager._try_execution_lock(run.run_id)
        assert execution_lock is not None
        execution_lock.close()
