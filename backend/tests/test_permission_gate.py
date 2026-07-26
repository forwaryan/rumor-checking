"""Tests for permission gate on tools (P3)."""
from __future__ import annotations

from backend.app.agent_tools.base import PermissionGate, ToolSpec


def _spec(name: str, requires_permission: bool = True) -> ToolSpec:
    return ToolSpec(name=name, description="test", requires_permission=requires_permission)


# --- PermissionGate ---


def test_gate_allows_unrestricted_tool():
    gate = PermissionGate()
    spec = _spec("normalize", requires_permission=False)
    assert gate.check(spec) is True


def test_gate_allows_when_no_callback():
    gate = PermissionGate(callback=None)
    spec = _spec("dangerous_tool")
    assert gate.check(spec) is True


def test_gate_denies_via_callback():
    gate = PermissionGate(callback=lambda name, spec: False)
    spec = _spec("dangerous_tool")
    assert gate.check(spec) is False


def test_gate_approves_via_callback():
    gate = PermissionGate(callback=lambda name, spec: True)
    spec = _spec("safe_tool")
    assert gate.check(spec) is True


def test_gate_remembers_approval():
    calls = []
    def cb(name, spec):
        calls.append(name)
        return True

    gate = PermissionGate(callback=cb)
    spec = _spec("tool_a")

    assert gate.check(spec) is True
    assert gate.check(spec) is True
    # Callback only called once (cached)
    assert len(calls) == 1


def test_gate_remembers_denial():
    calls = []
    def cb(name, spec):
        calls.append(name)
        return False

    gate = PermissionGate(callback=cb)
    spec = _spec("tool_b")

    assert gate.check(spec) is False
    assert gate.check(spec) is False
    assert len(calls) == 1


def test_gate_reset_clears_memory():
    gate = PermissionGate(callback=lambda n, s: True)
    spec = _spec("tool_c")
    gate.check(spec)
    gate.reset()
    # After reset, callback is called again
    calls = []
    gate._callback = lambda n, s: (calls.append(n), False)[1]
    assert gate.check(spec) is False
    assert len(calls) == 1


def test_gate_callback_exception_allows():
    def bad_cb(name, spec):
        raise RuntimeError("callback crashed")

    gate = PermissionGate(callback=bad_cb)
    spec = _spec("tool_d")
    # Exception → default allow
    assert gate.check(spec) is True


def test_gate_selective_by_name():
    def selective(name, spec):
        return name != "blocked_tool"

    gate = PermissionGate(callback=selective)
    assert gate.check(_spec("allowed_tool")) is True
    assert gate.check(_spec("blocked_tool")) is False


# --- Integration with runner ---


def test_runner_skips_denied_tool(monkeypatch):
    from backend.app.agent.runner import AgentRunner
    from backend.app.agent.state import AgentState, StepOutcome
    from backend.app.agent_tools.base import ToolContext
    import backend.app.agent_tools.base as base_mod

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

    # Gate that denies "fetch_url"
    gate = PermissionGate(callback=lambda name, spec: name != "fetch_url")
    runner = AgentRunner(ctx, permission_gate=gate)

    # Monkeypatch get_tool_spec to return a spec that requires permission
    original_get = base_mod.get_tool_spec
    def patched_get(name):
        spec = original_get(name)
        if spec and name == "fetch_url":
            return ToolSpec(name=name, description=spec.description, requires_permission=True)
        return spec
    monkeypatch.setattr(base_mod, "get_tool_spec", patched_get)
    # Also patch in runner module since it imported the name
    import backend.app.agent.runner as runner_mod
    monkeypatch.setattr(runner_mod, "get_tool_spec", patched_get)

    from backend.app.models.schemas import AnalyzeRequest
    runner._state = AgentState(request=AnalyzeRequest(raw_input="test"))

    # fetch_url should be denied
    outcome = runner._safe_dispatch("fetch_url", runner._state)
    assert outcome.success is False
    assert outcome.error_type == "PermissionDenied"


def test_runner_allows_approved_tool(monkeypatch):
    from backend.app.agent.runner import AgentRunner
    from backend.app.agent.state import AgentState, StepOutcome
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

    gate = PermissionGate(callback=lambda name, spec: True)
    runner = AgentRunner(ctx, permission_gate=gate)

    from backend.app.models.schemas import AnalyzeRequest, NormalizedEvent
    state = AgentState(request=AnalyzeRequest(raw_input="test"))
    runner._state = state

    # Mock the dispatch
    monkeypatch.setattr(runner, "_dispatch", lambda a, s: None)

    outcome = runner._safe_dispatch("normalize", state)
    assert outcome.success is True
