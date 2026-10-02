from __future__ import annotations

import json
import multiprocessing
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.core.exceptions import AppError
from backend.app.main import create_app
from backend.app.models.schemas import AnalysisRecheckRequest, AnalyzeRequest, ClaimResult, EvidenceItem
from backend.app.services.analysis_runs import AnalysisRunManager, get_analysis_run_manager
from backend.app.services.report_revisions import compare_reports
from backend.app.services.review_scope import restrict_review_results
from backend.app.services.run_control import RunStopped, check_run_control
from backend.tests.test_analysis_runs import sample_report, wait_for_terminal


def claim(text="博物馆周三免费", verdict="insufficient", url="https://example.org/notice"):
    return ClaimResult(
        claim=text, claim_type="fact", verdict=verdict, confidence=0.5, notes="原始调查",
        evidence=[EvidenceItem(
            title="公告", url=url, source_name="博物馆", published_at="2026-09-01", snippet="票价公告", relevance_reason="核验票价",
        )],
    )


def report_with_claims(*claims):
    return sample_report().model_copy(update={"claim_results": list(claims)})


def recheck_request(**kwargs):
    return AnalysisRecheckRequest(request_id=str(uuid4()), **kwargs)


@pytest.fixture
def manager_state(tmp_path, monkeypatch):
    now = [1000.0]
    owners = {}
    manager = AnalysisRunManager(tmp_path, retention_seconds=10, lease_seconds=100, max_active=20, clock=lambda: now[0])

    def launch(run_id, owner, execution_lock):
        owners[run_id] = owner
        execution_lock.close()

    monkeypatch.setattr(manager, "_launch", launch)
    return manager, owners, now


def completed_parent(manager, owners):
    parent = manager.create(AnalyzeRequest(raw_input="博物馆周三免费，周一闭馆。"))
    manager._finish(parent.run_id, owners[parent.run_id], report=report_with_claims(claim(), claim("博物馆周一闭馆", "supported")))
    return manager.get(parent.run_id)


def test_recheck_copies_parent_and_preserves_original_report(manager_state):
    manager, owners, _ = manager_state
    parent = completed_parent(manager, owners)
    review = manager.recheck(parent.run_id, recheck_request(claim_indices=[0], source_urls=["https://example.org/tickets"], note="补充票价公告"))
    assert review.parent_run_id == parent.run_id
    assert review.root_run_id == parent.run_id
    assert review.revision == 2
    assert review.mode == "deep"
    assert review.review_note == "补充票价公告"
    assert review.review_claim_indices == [0]
    assert review.raw_input == parent.raw_input
    with manager._connection() as connection:
        payload = json.loads(manager._row(connection, review.run_id)["request_json"])
    assert payload["request_context"]["review_claim_texts"] == ["博物馆周三免费"]
    assert payload["request_context"]["supplemental_urls"] == ["https://example.org/tickets"]
    assert payload["request_context"]["run_id"] == review.run_id
    assert manager.get(parent.run_id).model_dump() == parent.model_dump()


def test_recheck_preserves_nonfactual_claim_types(manager_state):
    manager, owners, _ = manager_state
    parent = manager.create(AnalyzeRequest(raw_input="观点与预测"))
    claims = [claim("这所学校是最好的").model_copy(update={"claim_type": "opinion"}),
              claim("球队下周将夺冠").model_copy(update={"claim_type": "prediction"})]
    manager._finish(parent.run_id, owners[parent.run_id], report=report_with_claims(*claims))
    child = manager.recheck(parent.run_id, recheck_request())
    with manager._connection() as connection:
        context = json.loads(manager._row(connection, child.run_id)["request_json"])["request_context"]
    assert context["review_claim_types"] == ["opinion", "prediction"]


def test_recheck_keeps_previous_supplemental_links_when_no_replacement_is_given(manager_state):
    manager, owners, _ = manager_state
    parent = completed_parent(manager, owners)
    child = manager.recheck(parent.run_id, recheck_request(source_urls=["https://example.org/tickets"]))
    manager._finish(child.run_id, owners[child.run_id], report=report_with_claims(claim()))
    unchanged = manager.recheck(child.run_id, recheck_request())
    replaced = manager.recheck(child.run_id, recheck_request(source_urls=["https://example.org/latest"]))
    with manager._connection() as connection:
        existing_context = json.loads(manager._row(connection, unchanged.run_id)["request_json"])["request_context"]
        replaced_context = json.loads(manager._row(connection, replaced.run_id)["request_json"])["request_context"]
    assert existing_context["supplemental_urls"] == ["https://example.org/tickets"]
    assert replaced_context["supplemental_urls"] == ["https://example.org/latest"]


def test_root_creation_discards_caller_supplied_revision_fields(manager_state):
    manager, _, _ = manager_state
    run = manager.create(AnalyzeRequest(raw_input="test", request_context={
        "parent_run_id": "forged", "root_run_id": "forged", "revision": 9,
        "review_claim_indices": [42], "review_claim_texts": ["forged"], "review_note": "forged",
        "supplemental_urls": ["http://localhost/private"],
    }))
    assert run.parent_run_id is None
    assert run.root_run_id == run.run_id
    assert run.revision == 1
    assert run.review_claim_indices == []
    assert run.review_note == ""
    with manager._connection() as connection:
        context = json.loads(manager._row(connection, run.run_id)["request_json"])["request_context"]
    assert set(context) == {"mode", "run_id"}


def test_recheck_defaults_to_all_claims_and_is_idempotent(manager_state):
    manager, owners, _ = manager_state
    parent = completed_parent(manager, owners)
    request = recheck_request()
    first = manager.recheck(parent.run_id, request)
    manager.max_active = 1
    assert manager.recheck(parent.run_id, request).run_id == first.run_id
    assert first.review_claim_indices == [0, 1]
    assert len(manager.versions(first.run_id).revisions) == 2


@pytest.mark.parametrize("indices", [[2], [100], [0, 2]])
def test_recheck_rejects_indices_outside_parent(manager_state, indices):
    manager, owners, _ = manager_state
    parent = completed_parent(manager, owners)
    with pytest.raises(AppError) as error:
        manager.recheck(parent.run_id, recheck_request(claim_indices=indices))
    assert error.value.code == "invalid_claim_indices"
    assert len(manager.versions(parent.run_id).revisions) == 1


def test_recheck_requires_completed_report_with_claims(manager_state):
    manager, owners, _ = manager_state
    parent = manager.create(AnalyzeRequest(raw_input="test"))
    with pytest.raises(AppError) as error:
        manager.recheck(parent.run_id, recheck_request())
    assert error.value.status_code == 409
    manager._finish(parent.run_id, owners[parent.run_id], report=sample_report())
    with pytest.raises(AppError) as error:
        manager.recheck(parent.run_id, recheck_request())
    assert error.value.status_code == 422


def test_concurrent_rechecks_allocate_unique_case_revisions(manager_state):
    manager, owners, _ = manager_state
    parent = completed_parent(manager, owners)
    requests = [recheck_request() for _ in range(8)]
    with ThreadPoolExecutor(max_workers=8) as executor:
        reviews = list(executor.map(lambda request: manager.recheck(parent.run_id, request), requests))
    assert sorted(review.revision for review in reviews) == list(range(2, 10))
    duplicate_request = recheck_request()
    with ThreadPoolExecutor(max_workers=8) as executor:
        duplicates = list(executor.map(lambda _: manager.recheck(parent.run_id, duplicate_request), range(8)))
    assert len({review.run_id for review in duplicates}) == 1
    assert len(manager.versions(parent.run_id).revisions) == 10


def test_new_version_retains_ancestors_until_whole_case_expires(manager_state):
    manager, owners, now = manager_state
    parent = completed_parent(manager, owners)
    now[0] += 9
    child = manager.recheck(parent.run_id, recheck_request())
    now[0] += 5
    assert manager.get(parent.run_id).report is not None
    manager._finish(child.run_id, owners[child.run_id], report=report_with_claims(claim()))
    now[0] += 9
    assert len(manager.versions(child.run_id).revisions) == 2
    now[0] += 2
    for run_id in [parent.run_id, child.run_id]:
        with pytest.raises(AppError) as error:
            manager.get(run_id)
        assert error.value.status_code == 404


def test_versions_are_case_scoped_and_parent_report_is_compared(manager_state):
    manager, owners, _ = manager_state
    parent = completed_parent(manager, owners)
    unrelated = completed_parent(manager, owners)
    child = manager.recheck(parent.run_id, recheck_request(claim_indices=[0]))
    with pytest.raises(AppError) as error:
        manager.changes(child.run_id)
    assert error.value.status_code == 409
    manager._finish(child.run_id, owners[child.run_id], report=report_with_claims(claim(verdict="refuted")))
    assert [revision.run_id for revision in manager.versions(child.run_id).revisions] == [parent.run_id, child.run_id]
    assert len(manager.versions(unrelated.run_id).revisions) == 1
    differences = manager.changes(child.run_id)
    assert [(change.kind, change.before_verdict, change.after_verdict) for change in differences.changes] == [
        ("changed", "insufficient", "refuted"), ("not_rechecked", "supported", None),
    ]
    assert manager.changes(parent.run_id).changes == []


def test_comparison_matches_normalized_text_and_evidence_only_changes():
    before = report_with_claims(claim("Museum  A", "supported", "https://example.org/old"))
    after = report_with_claims(claim("ＭＵＳＥＵＭ A", "supported", "https://example.org/new"))
    comparison = compare_reports(uuid4().hex, uuid4().hex, before, after, [0])
    assert len(comparison.changes) == 1
    change = comparison.changes[0]
    assert change.kind == "changed"
    assert change.added_evidence_urls == ["https://example.org/new"]
    assert change.removed_evidence_urls == ["https://example.org/old"]
    assert comparison.added_source_urls == ["https://example.org/new"]
    assert comparison.removed_source_urls == ["https://example.org/old"]


def test_comparison_does_not_guess_identity_or_drop_duplicate_claims():
    before = report_with_claims(claim("博物馆周一闭馆"), claim("博物馆周一闭馆"))
    after = report_with_claims(claim("博物馆周二闭馆"), claim("博物馆周一闭馆"))
    comparison = compare_reports(uuid4().hex, uuid4().hex, before, after, [0, 1])
    assert [(change.kind, change.claim) for change in comparison.changes] == [
        ("removed", "博物馆周一闭馆"), ("added", "博物馆周二闭馆"),
    ]


def test_evidence_content_changes_at_same_url_are_reported():
    previous = claim(verdict="supported")
    current = previous.model_copy(deep=True)
    current.evidence[0].snippet = "公告正文已补充最新票价"
    comparison = compare_reports(uuid4().hex, uuid4().hex, report_with_claims(previous), report_with_claims(current), [0])
    assert len(comparison.changes) == 1
    assert comparison.changes[0].kind == "changed"
    assert comparison.changes[0].added_evidence_urls == []
    assert comparison.changes[0].removed_evidence_urls == []


def test_unreviewed_claim_sources_are_not_reported_as_removed():
    before = report_with_claims(claim("票价", url="https://example.org/price"), claim("开放时间", url="https://example.org/hours"))
    after = report_with_claims(claim("票价", url="https://example.org/price"))
    comparison = compare_reports(uuid4().hex, uuid4().hex, before, after, [0])
    assert comparison.removed_source_urls == []
    assert comparison.changes[0].kind == "not_rechecked"


def test_review_punctuation_does_not_create_removed_and_added_claims():
    previous = claim("博物馆周三免费", "supported")
    request = AnalyzeRequest(raw_input=previous.claim, request_context={
        "review_claim_texts": [previous.claim], "review_claim_types": ["fact"],
    })
    restored = restrict_review_results([previous.model_copy(update={"claim": previous.claim + "。"})], request)
    comparison = compare_reports(uuid4().hex, uuid4().hex, report_with_claims(previous), report_with_claims(*restored), [0])
    assert restored[0].claim == previous.claim
    assert comparison.changes == []


def test_cancel_is_terminal_and_late_worker_cannot_replace_it(manager_state):
    manager, owners, _ = manager_state
    run = manager.create(AnalyzeRequest(raw_input="stop"))
    cancelled = manager.cancel(run.run_id)
    assert cancelled.status == "cancelled"
    assert cancelled.cancel_requested
    assert cancelled.stop_reason == "user_cancelled"
    assert not cancelled.resumable
    assert manager.cancellation_requested(run.run_id)
    manager._finish(run.run_id, owners[run.run_id], report=sample_report())
    assert manager.cancel(run.run_id) == cancelled
    assert manager.resume(run.run_id) == cancelled
    assert not manager._renew(run.run_id, owners[run.run_id])
    events, terminal = manager.event_page(run.run_id, 0)
    assert terminal.report is None
    assert events[-1]["event"]["cancelled"] is True


def test_cancel_completed_run_preserves_report_and_history(manager_state):
    manager, owners, _ = manager_state
    parent = completed_parent(manager, owners)
    assert manager.cancel(parent.run_id) == parent
    assert not manager.cancellation_requested(parent.run_id)


def test_cancelled_worker_retains_capacity_and_lock_until_return(tmp_path):
    started, release = threading.Event(), threading.Event()

    def analyze(payload):
        started.set()
        assert release.wait(5)
        return sample_report()

    manager = AnalysisRunManager(tmp_path, max_active=1, pipeline_factory=lambda: SimpleNamespace(analyze=analyze))
    run = manager.create(AnalyzeRequest(raw_input="slow provider"))
    assert started.wait(5)
    try:
        assert manager.cancel(run.run_id).status == "cancelled"
        with pytest.raises(AppError) as error:
            manager.create(AnalyzeRequest(raw_input="second"))
        assert error.value.status_code == 429
    finally:
        release.set()
    assert wait_for_terminal(manager, run.run_id).status == "cancelled"


def _read_legacy_run_in_process(directory, run_id, barrier, results):
    barrier.wait(timeout=15)
    manager = AnalysisRunManager(directory, clock=lambda: 1000)
    results.put((manager.get(run_id).model_dump(), manager.event_page(run_id, 0)[0]))


@pytest.mark.parametrize("concurrency", ["threads", "processes"])
def test_old_database_migrates_atomically_and_preserves_events(tmp_path, concurrency):
    run_id = uuid4().hex
    database = tmp_path / "analysis-runs.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("""CREATE TABLE runs (
            run_id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
            request_json TEXT NOT NULL, mode TEXT NOT NULL, input_preview TEXT NOT NULL,
            report_json TEXT, error TEXT, last_event_id INTEGER NOT NULL DEFAULT 0, owner TEXT, lease_until REAL
        )""")
        connection.execute(
            "INSERT INTO runs (run_id,status,created_at,updated_at,request_json,mode,input_preview,report_json) "
            "VALUES (?, 'completed', 1000, 1000, ?, 'fast', 'legacy', ?)",
            (run_id, AnalyzeRequest(raw_input="legacy").model_dump_json(), report_with_claims(claim()).model_dump_json()),
        )
        connection.execute("""CREATE TABLE events (
            run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
            event_id INTEGER NOT NULL, event_json TEXT NOT NULL, PRIMARY KEY (run_id, event_id)
        )""")
        connection.execute("UPDATE runs SET last_event_id=1 WHERE run_id=?", (run_id,))
        connection.execute("INSERT INTO events VALUES (?, 1, ?)", (run_id, '{"type":"complete","success":true}'))
    if concurrency == "threads":
        barrier = threading.Barrier(4)

        def initialize(_):
            barrier.wait(timeout=15)
            manager = AnalysisRunManager(tmp_path, clock=lambda: 1000)
            return manager.get(run_id).model_dump(), manager.event_page(run_id, 0)[0]

        with ThreadPoolExecutor(max_workers=4) as executor:
            observations = list(executor.map(initialize, range(4)))
    else:
        context = multiprocessing.get_context("spawn")
        barrier = context.Barrier(4)
        results = context.Queue()
        processes = [context.Process(target=_read_legacy_run_in_process, args=(tmp_path, run_id, barrier, results)) for _ in range(4)]
        try:
            for process in processes:
                process.start()
            observations = [results.get(timeout=20) for _ in processes]
            for process in processes:
                process.join(timeout=5)
                assert process.exitcode == 0
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
            results.close()
    for legacy, events in observations:
        assert legacy["root_run_id"] == run_id
        assert legacy["parent_run_id"] is None
        assert legacy["revision"] == 1
        assert not legacy["cancel_requested"]
        assert legacy["report"]["claim_results"][0]["claim"] == "博物馆周三免费"
        assert events == [{"event_id": 1, "event": {"type": "complete", "success": True}}]


def test_schema_lock_timeout_is_bounded_and_sentinel_survives_cleanup(manager_state, monkeypatch):
    manager, owners, now = manager_state
    parent = completed_parent(manager, owners)
    monkeypatch.setattr("backend.app.services.analysis_runs._INITIALIZATION_TIMEOUT_SECONDS", 0.03)
    schema_lock = manager._try_execution_lock("__schema_initialization__")
    assert schema_lock is not None
    try:
        with pytest.raises(sqlite3.OperationalError, match="schema initialization timed out"):
            AnalysisRunManager(manager.directory)
        now[0] += 11
        with pytest.raises(AppError):
            manager.get(parent.run_id)
        assert (manager.lock_directory / "__schema_initialization__.lock").exists()
        assert manager._try_execution_lock("__schema_initialization__") is None
    finally:
        schema_lock.close()
    assert AnalysisRunManager(manager.directory).database.exists()


def test_cancelled_child_execution_lock_keeps_entire_case_from_expiring(manager_state, monkeypatch):
    manager, owners, now = manager_state
    parent = completed_parent(manager, owners)
    handles = []
    monkeypatch.setattr(manager, "_launch", lambda run_id, owner, execution_lock: handles.append(execution_lock))
    child = manager.recheck(parent.run_id, recheck_request())
    manager.cancel(child.run_id)
    now[0] += 11
    try:
        assert manager.get(parent.run_id).status == "completed"
        assert manager.get(child.run_id).status == "cancelled"
    finally:
        handles[0].close()
    now[0] += 2  # read paths sweep at most once per cleanup interval
    with pytest.raises(AppError) as error:
        manager.get(parent.run_id)
    assert error.value.status_code == 404


@pytest.fixture
def revision_client(manager_state):
    manager, owners, _ = manager_state
    app = create_app()
    app.dependency_overrides[get_analysis_run_manager] = lambda: manager
    parent = completed_parent(manager, owners)
    with TestClient(app) as client:
        yield client, manager, owners, parent


def test_recheck_versions_changes_and_cancel_routes(revision_client):
    client, manager, owners, parent = revision_client
    payload = {"request_id": str(uuid4()), "claim_indices": [0], "source_urls": ["https://example.org/new"], "note": "新公告"}
    response = client.post(f"/api/v1/analysis-runs/{parent.run_id}/recheck", json=payload)
    assert response.status_code == 202
    child_id = response.json()["run_id"]
    assert client.post(f"/api/v1/analysis-runs/{parent.run_id}/recheck", json=payload).json()["run_id"] == child_id
    response = client.get(f"/api/v1/analysis-runs/{child_id}/versions")
    assert response.status_code == 200
    assert response.json()["root_run_id"] == parent.run_id
    assert [run["revision"] for run in response.json()["revisions"]] == [1, 2]
    assert all("raw_input" not in run and "report" not in run for run in response.json()["revisions"])
    assert client.get(f"/api/v1/analysis-runs/{child_id}/changes").status_code == 409
    manager._finish(child_id, owners[child_id], report=report_with_claims(claim(verdict="refuted")))
    response = client.get(f"/api/v1/analysis-runs/{child_id}/changes")
    assert response.status_code == 200
    assert [change["kind"] for change in response.json()["changes"]] == ["changed", "not_rechecked"]
    assert client.post(f"/api/v1/analysis-runs/{child_id}/cancel").json()["status"] == "completed"
    queued = manager.recheck(child_id, recheck_request())
    response = client.post(f"/api/v1/analysis-runs/{queued.run_id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["cancel_requested"]


@pytest.mark.parametrize("invalid", [
    {"claim_indices": [-1]}, {"claim_indices": [True]}, {"claim_indices": ["0"]},
    {"claim_indices": [1.1]}, {"source_urls": ["file:///etc/passwd"]},
    {"source_urls": ["javascript:alert(1)"]}, {"source_urls": ["https://user:secret@example.org"]},
    {"source_urls": ["https://"]}, {"source_urls": ["https://example.org"] * 6},
    {"note": "a" * 2001}, {"request_id": ""},
])
def test_recheck_route_validates_request_before_creating_run(revision_client, invalid):
    client, manager, _, parent = revision_client
    response = client.post(f"/api/v1/analysis-runs/{parent.run_id}/recheck", json={"request_id": str(uuid4()), **invalid})
    assert response.status_code == 422
    assert len(manager.versions(parent.run_id).revisions) == 1


def test_recheck_cannot_override_parent_input_or_source_metadata(revision_client):
    client, manager, _, parent = revision_client
    response = client.post(f"/api/v1/analysis-runs/{parent.run_id}/recheck", json={
        "request_id": str(uuid4()), "raw_input": "forged", "parent_run_id": uuid4().hex,
        "root_run_id": uuid4().hex, "source_tier": "S", "request_context": {"mode": "fast"},
    })
    if response.status_code == 422:
        assert len(manager.versions(parent.run_id).revisions) == 1
        return
    assert response.status_code == 202
    assert response.json()["raw_input"] == parent.raw_input
    assert response.json()["parent_run_id"] == parent.run_id
    assert response.json()["root_run_id"] == parent.run_id
    assert response.json()["mode"] == "deep"


@pytest.mark.parametrize("suffix,method", [("versions", "get"), ("changes", "get"), ("cancel", "post"), ("recheck", "post")])
def test_revision_routes_require_a_valid_known_private_run_link(revision_client, suffix, method):
    client, _, _, _ = revision_client
    kwargs = {"json": {"request_id": str(uuid4())}} if suffix == "recheck" else {}
    assert getattr(client, method)(f"/api/v1/analysis-runs/{uuid4()}/{suffix}", **kwargs).status_code == 404
    assert getattr(client, method)(f"/api/v1/analysis-runs/invalid/{suffix}", **kwargs).status_code == 422


def test_budget_reservations_are_atomic_and_failed_calls_do_not_consume_budget(manager_state):
    manager, owners, _ = manager_state
    run = manager.create(AnalyzeRequest(raw_input="budget"))

    def reserve(_):
        try:
            manager._reserve_model_call(run.run_id, owners[run.run_id], 10, max_llm_calls=3, max_tokens=100)
            return "reserved"
        except RunStopped as exc:
            return exc.reason

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(reserve, range(8)))
    assert outcomes.count("reserved") == 3
    assert outcomes.count("call_budget_exhausted") == 5
    with manager._connection() as connection:
        row = manager._row(connection, run.run_id)
    assert row["llm_call_count"] == 3
    assert row["reserved_tokens"] == 30
    assert "reserved_tokens" not in manager.get(run.run_id).model_dump()


def test_budget_consumption_survives_resume_and_database_reload(manager_state):
    manager, owners, now = manager_state
    manager.retention_seconds = 1000
    run = manager.create(AnalyzeRequest(raw_input="persistent budget"))
    manager._reserve_model_call(run.run_id, owners[run.run_id], 80, max_llm_calls=10, max_tokens=100)
    now[0] += 101
    manager.resume(run.run_id)
    with pytest.raises(RunStopped) as error:
        manager._reserve_model_call(run.run_id, owners[run.run_id], 21, max_llm_calls=10, max_tokens=100)
    assert error.value.reason == "token_budget_exhausted"
    reopened = AnalysisRunManager(manager.directory, retention_seconds=1000, clock=lambda: now[0])
    with reopened._connection() as connection:
        row = reopened._row(connection, run.run_id)
    assert row["llm_call_count"] == 1
    assert row["reserved_tokens"] == 80


def test_cancelled_or_stale_owner_cannot_reserve_calls(manager_state):
    manager, owners, _ = manager_state
    run = manager.create(AnalyzeRequest(raw_input="check owner"))
    with pytest.raises(RunStopped) as error:
        manager._reserve_model_call(run.run_id, "stale", 10, max_llm_calls=0, max_tokens=0)
    assert error.value.reason == "lease_lost"
    manager.cancel(run.run_id)
    with pytest.raises(RunStopped) as error:
        manager._reserve_model_call(run.run_id, owners[run.run_id], 10, max_llm_calls=0, max_tokens=0)
    assert error.value.reason == "user_cancelled"


def test_worker_budget_stop_has_no_completed_report_and_is_not_resumable(tmp_path):
    def analyze(payload):
        raise RunStopped("token_budget_exhausted")

    manager = AnalysisRunManager(tmp_path, pipeline_factory=lambda: SimpleNamespace(analyze=analyze))
    run = manager.create(AnalyzeRequest(raw_input="budget stop"))
    terminal = wait_for_terminal(manager, run.run_id)
    assert terminal.status == "cancelled"
    assert terminal.stop_reason == "token_budget_exhausted"
    assert terminal.report is None
    assert not terminal.resumable
    assert manager.resume(run.run_id).status == "cancelled"
    events, _ = manager.event_page(run.run_id, 0)
    assert events[-1]["event"]["success"] is False
    assert not any(envelope["event"]["type"] == "report" for envelope in events)


def test_worker_installs_cancellation_control_between_pipeline_steps(tmp_path):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    later_steps = []

    def analyze(payload):
        started.set()
        assert release.wait(5)
        try:
            check_run_control()
            later_steps.append("should not run")
            return sample_report()
        finally:
            finished.set()

    manager = AnalysisRunManager(tmp_path, pipeline_factory=lambda: SimpleNamespace(analyze=analyze))
    run = manager.create(AnalyzeRequest(raw_input="stop between steps"))
    assert started.wait(5)
    try:
        manager.cancel(run.run_id)
    finally:
        release.set()
    assert finished.wait(5)
    assert later_steps == []
    assert manager.get(run.run_id).status == "cancelled"
