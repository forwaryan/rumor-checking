from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.models.schemas import AnalysisRunEvent, AnalyzeRequest
from backend.app.services.analysis_runs import AnalysisRunManager, get_analysis_run_manager
from backend.tests.test_analysis_runs import sample_report, wait_for_terminal


@pytest.fixture
def run_client(tmp_path):
    manager = AnalysisRunManager(tmp_path, pipeline_factory=lambda: SimpleNamespace(analyze=lambda request: sample_report()))
    app = create_app()
    app.dependency_overrides[get_analysis_run_manager] = lambda: manager
    with TestClient(app) as client:
        yield client, manager


def test_create_get_replay_and_completed_resume(run_client):
    client, manager = run_client
    response = client.post("/api/v1/analysis-runs", json={"raw_input": "待核查", "request_context": {"run_id": str(uuid4())}})
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    terminal = wait_for_terminal(manager, run_id)
    fetched = client.get(f"/api/v1/analysis-runs/{run_id}")
    assert fetched.status_code == 200
    assert fetched.json()["report"] == sample_report().model_dump(mode="json")
    response = client.get(f"/api/v1/analysis-runs/{run_id}/events")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in response.text.splitlines()]
    assert [AnalysisRunEvent.model_validate(event).model_dump() for event in events] == events
    assert [entry["event_id"] for entry in events] == list(range(1, terminal.last_event_id + 1))
    response = client.get(f"/api/v1/analysis-runs/{run_id}/events?after=1")
    assert [json.loads(line) for line in response.text.splitlines()] == events[1:]
    response = client.get(f"/api/v1/analysis-runs/{run_id}/events?after={terminal.last_event_id}")
    assert response.text == ""
    assert client.post(f"/api/v1/analysis-runs/{run_id}/resume").json()["status"] == "completed"


def test_unknown_ids_invalid_ids_and_cursors(run_client):
    client, manager = run_client
    for suffix, method in [("", client.get), ("/events", client.get), ("/resume", client.post)]:
        assert method(f"/api/v1/analysis-runs/{uuid4()}{suffix}").status_code == 404
        assert method(f"/api/v1/analysis-runs/not-a-uuid{suffix}").status_code == 422
    run = manager.create(AnalyzeRequest(raw_input="测试"))
    wait_for_terminal(manager, run.run_id)
    assert client.get(f"/api/v1/analysis-runs/{run.run_id}/events?after=-1").status_code == 422
    assert client.get(f"/api/v1/analysis-runs/{run.run_id}/events?after=999").status_code == 422
    assert client.get("/api/v1/analysis-runs").status_code == 405


def test_api_capacity_status(run_client, monkeypatch):
    client, manager = run_client
    manager.max_active = 1
    monkeypatch.setattr(manager, "_launch", lambda run_id, owner, execution_lock: execution_lock.close())
    assert client.post("/api/v1/analysis-runs", json={"raw_input": "first"}).status_code == 202
    assert client.post("/api/v1/analysis-runs", json={"raw_input": "second"}).status_code == 429


def test_resume_keeps_original_request_and_failed_run_requires_new_request(run_client, monkeypatch):
    client, manager = run_client
    now = [1000.0]
    owners = []
    monkeypatch.setattr(manager, "clock", lambda: now[0])
    monkeypatch.setattr(manager, "_launch", lambda run_id, owner, execution_lock: (owners.append(owner), execution_lock.close()))
    run = manager.create(AnalyzeRequest(raw_input="原始输入", request_context={"mode": "deep"}))
    now[0] += 31
    response = client.get(f"/api/v1/analysis-runs/{run.run_id}")
    assert response.json()["status"] == "interrupted"
    assert response.json()["resumable"]
    response = client.post(f"/api/v1/analysis-runs/{run.run_id}/resume", json={"raw_input": "替换输入", "request_context": {"mode": "fast"}})
    assert response.status_code == 200
    assert response.json()["run_id"] == run.run_id
    assert response.json()["mode"] == "deep"
    assert response.json()["input_preview"] == "原始输入"
    with manager._connection() as connection:
        stored = json.loads(connection.execute("SELECT request_json FROM runs WHERE run_id=?", (run.run_id,)).fetchone()[0])
    assert stored["raw_input"] == "原始输入"
    assert stored["request_context"]["mode"] == "deep"
    manager._finish(run.run_id, owners[-1], error="analysis_failed")
    assert client.post(f"/api/v1/analysis-runs/{run.run_id}/resume").status_code == 409


def test_private_run_response_preserves_full_input(run_client):
    client, manager = run_client
    raw_input = "完整核查请求。" * 40
    response = client.post("/api/v1/analysis-runs", json={"raw_input": raw_input})
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    wait_for_terminal(manager, run_id)
    data = client.get(f"/api/v1/analysis-runs/{run_id}").json()
    assert data["raw_input"] == raw_input
    assert len(data["input_preview"]) == 140


@pytest.mark.parametrize("suffix", ["", "/stream"])
def test_legacy_endpoints_cannot_write_into_a_client_selected_run(client, monkeypatch, suffix):
    seen = []
    selected_run_id = "a" * 32
    monkeypatch.setattr(
        "backend.app.api.v1.endpoints.analyze.AnalyzePipeline",
        lambda: SimpleNamespace(analyze=lambda request: seen.append(request.request_context["run_id"]) or sample_report()),
    )
    response = client.post(
        f"/api/v1/analyze{suffix}",
        json={"raw_input": "隔离旧接口", "request_context": {"run_id": selected_run_id}},
    )
    assert response.status_code == 200
    assert len(seen) == 1
    assert seen[0] != selected_run_id
    assert len(seen[0]) == 32
    if suffix:
        session = json.loads(response.text.splitlines()[0])
        assert session["run_id"] == seen[0]


def test_resume_returns_retryable_conflict_while_old_execution_lock_is_held(run_client, monkeypatch):
    client, manager = run_client
    now = [1000.0]
    handles = []
    monkeypatch.setattr(manager, "clock", lambda: now[0])
    monkeypatch.setattr(manager, "_launch", lambda run_id, owner, execution_lock: handles.append(execution_lock))
    run = manager.create(AnalyzeRequest(raw_input="still executing"))
    now[0] += 31
    try:
        response = client.post(f"/api/v1/analysis-runs/{run.run_id}/resume")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "run_still_executing"
    finally:
        handles[0].close()
