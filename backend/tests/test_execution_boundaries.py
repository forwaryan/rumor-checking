import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app.agent.multi import AgentRole
from backend.app.agent.multi.supervisor import Supervisor
from backend.app.core.exceptions import AppError
from backend.app.main import create_app
from backend.app.models.schemas import AnalyzeRequest
from backend.app.services.analysis_runs import AnalysisRunManager, get_analysis_run_manager
from backend.app.services.run_control import check_run_control, get_run_control, reserve_llm_call
from backend.tests.test_analysis_runs import sample_report, wait_for_terminal


@pytest.mark.parametrize("mode", ["single", "sequential_batch", "parallel_batch"])
def test_timeout_is_published_before_worker_drains_and_lock_stays_held(tmp_path, mode):
    entered = threading.Event()
    release = threading.Event()
    late_effects = []

    def blocked_agent(state, context):
        entered.set()
        release.wait(5)
        check_run_control()
        late_effects.append("late event")

    class Pipeline:
        def analyze(self, request):
            supervisor = Supervisor(SimpleNamespace(agent_reasoner=None), max_parallel=1 if mode == "sequential_batch" else 2)
            if mode == "single":
                supervisor._invoke_agent(SimpleNamespace(run=blocked_agent), None, timeout_seconds=0.05)
            else:
                agents = [
                    SimpleNamespace(role=role, description="blocked", config=None, run=blocked_agent)
                    for role in (AgentRole.RETRIEVAL_BAIDU, AgentRole.RETRIEVAL_XHS)
                ]
                supervisor._execute_batch(agents, None, deadline=time.monotonic() + 0.05)
            late_effects.append("fallback report")
            return sample_report()

    manager = AnalysisRunManager(tmp_path, max_active=1, pipeline_factory=Pipeline)
    try:
        started = manager.create(AnalyzeRequest(raw_input="超时回归"))
        assert entered.wait(1)
        stopped = wait_for_terminal(manager, started.run_id)
        assert not release.is_set()
        assert stopped.status == "cancelled"
        assert stopped.stop_reason == "agent_timeout"
        assert stopped.report is None
        assert manager._try_execution_lock(started.run_id) is None
        with pytest.raises(AppError) as error:
            manager.create(AnalyzeRequest(raw_input="清退前不得重用容量"))
        assert error.value.status_code == 429
    finally:
        release.set()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        execution_lock = manager._try_execution_lock(started.run_id)
        if execution_lock is not None:
            execution_lock.close()
            break
        time.sleep(0.01)
    else:
        pytest.fail("worker did not release execution lock after draining")
    assert not late_effects


@pytest.mark.parametrize("path", ["/api/v1/analyze", "/api/v1/analyze/stream"])
def test_legacy_entrypoints_share_run_capacity(tmp_path, path):
    entered = threading.Event()
    release = threading.Event()

    class Pipeline:
        def analyze(self, request):
            entered.set()
            release.wait(3)
            return sample_report()

    manager = AnalysisRunManager(tmp_path, max_active=1, pipeline_factory=Pipeline)
    app = create_app()
    app.dependency_overrides[get_analysis_run_manager] = lambda: manager
    try:
        active = manager.create(AnalyzeRequest(raw_input="占用容量"))
        assert entered.wait(1)
        with TestClient(app) as client:
            response = client.post(path, json={"raw_input": "旧接口"})
        assert response.status_code == 429
    finally:
        release.set()
        wait_for_terminal(manager, active.run_id)


@pytest.mark.parametrize("path", ["/api/v1/analyze", "/api/v1/analyze/stream"])
def test_legacy_entrypoints_install_persisted_call_budget(tmp_path, monkeypatch, path):
    seen_controls = []

    class Pipeline:
        def analyze(self, request):
            seen_controls.append(get_run_control())
            reserve_llm_call(system_prompt="system", user_prompt="test", max_output_tokens=2)
            reserve_llm_call(system_prompt="system", user_prompt="test", max_output_tokens=2)
            return sample_report()

    monkeypatch.setenv("ANALYSIS_RUN_MAX_LLM_CALLS", "1")
    from backend.app.core.config import get_settings
    get_settings.cache_clear()
    manager = AnalysisRunManager(tmp_path, pipeline_factory=Pipeline)
    app = create_app()
    app.dependency_overrides[get_analysis_run_manager] = lambda: manager
    with TestClient(app) as client:
        response = client.post(path, json={"raw_input": "旧入口预算"})
    assert len(seen_controls) == 1 and seen_controls[0] is not None
    assert response.headers.get("x-analysis-run-id")
    run = manager.get(response.headers["x-analysis-run-id"])
    assert run.status == "cancelled"
    assert run.stop_reason == "call_budget_exhausted"
    assert run.report is None
