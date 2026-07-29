"""Tests for the multi-agent Supervisor architecture."""
from __future__ import annotations

import pytest

from backend.app.agent.multi import AgentRole, AgentStatus
from backend.app.agent.multi.supervisor import Supervisor
from backend.app.agent.multi.retrieval_agent import RetrievalAgent
from backend.app.agent.multi.analysis_agent import AnalysisAgent
from backend.app.agent.multi.critic_agent import CriticAgent
from backend.app.agent.multi.report_agent import ReportAgent
from backend.app.agent.state import AgentState
from backend.app.models.schemas import AnalyzeRequest
from backend.app.services.analyze_pipeline import AnalyzePipeline


@pytest.fixture
def pipeline():
    return AnalyzePipeline()


@pytest.fixture
def tool_context(pipeline):
    from backend.app.agent_tools.base import ToolContext
    return ToolContext(
        settings=pipeline.settings,
        input_normalizer=pipeline.input_normalizer,
        retriever=pipeline.retriever,
        url_content_extractor=pipeline.input_normalizer.url_content_extractor,
        url_fetch_cache=pipeline.url_fetch_cache,
        question_resolver=pipeline.question_resolver,
        agent_reasoner=pipeline.agent_reasoner,
        provider_enricher=pipeline.provider_enricher,
        claim_extractor=pipeline.claim_extractor,
        verdict_engine=pipeline.verdict_engine,
        timeline_builder=pipeline.timeline_builder,
        report_builder=pipeline.report_builder,
        content_check_builder=pipeline.content_check_builder,
        pipeline_trace_builder=pipeline.pipeline_trace_builder,
    )


def test_supervisor_produces_report(tool_context):
    """The supervisor should produce a Report via the full agent chain."""
    supervisor = Supervisor(tool_context)
    request = AnalyzeRequest(raw_input="听说京东开始造游轮了")
    report = supervisor.run(request)
    assert report is not None
    assert hasattr(report, "claim_results") or hasattr(report, "credibility_label")


def test_supervisor_default_agents():
    """Default agent set should be Retrieval -> Analysis -> Critic -> Report."""
    from backend.app.agent_tools.base import ToolContext
    ctx = ToolContext.__new__(ToolContext)
    supervisor = Supervisor(ctx)
    roles = [a.role for a in supervisor.agents]
    assert roles == [AgentRole.RETRIEVAL, AgentRole.ANALYSIS, AgentRole.CRITIC, AgentRole.REPORT]


def test_retrieval_agent_has_no_deps():
    agent = RetrievalAgent()
    assert agent.dependencies == []


def test_analysis_agent_depends_on_retrieval():
    agent = AnalysisAgent()
    assert AgentRole.RETRIEVAL in agent.dependencies


def test_critic_agent_depends_on_analysis():
    agent = CriticAgent()
    assert AgentRole.ANALYSIS in agent.dependencies


def test_report_agent_depends_on_critic():
    agent = ReportAgent()
    assert AgentRole.CRITIC in agent.dependencies


def test_supervisor_handles_cancellation(tool_context):
    """Cancellation should force early report generation."""
    supervisor = Supervisor(tool_context)
    request = AnalyzeRequest(raw_input="听说京东开始造游轮了")
    state = AgentState(request=request)
    state.cancelled = True
    # Directly test the _ready_agents logic with cancelled state
    # (full run would still attempt force_finalize)
    agent_map = {a.role: a for a in supervisor.agents}
    ready = supervisor._ready_agents(agent_map, set(), set())
    assert AgentRole.RETRIEVAL in [a.role for a in ready]


def test_dependency_graph_resolution():
    """When retrieval fails, analysis/critic/report should be skipped."""
    from backend.app.agent_tools.base import ToolContext
    ctx = ToolContext.__new__(ToolContext)
    supervisor = Supervisor(ctx)
    agent_map = {a.role: a for a in supervisor.agents}
    failed = {AgentRole.RETRIEVAL}
    completed = set()
    ready = supervisor._ready_agents(agent_map, completed, failed)
    # Nothing should be ready since all depend (transitively) on retrieval
    assert len(ready) == 0


def test_per_agent_model_config(tool_context):
    """Each agent should use its configured model and restore after."""
    from backend.app.agent.multi import AgentConfig

    configs = {
        AgentRole.RETRIEVAL: AgentConfig(model="fast-model-v1"),
        AgentRole.ANALYSIS: AgentConfig(model="reasoning-model-v2"),
        AgentRole.CRITIC: AgentConfig(model="critic-model-v3"),
    }
    supervisor = Supervisor(tool_context, agent_configs=configs)

    assert supervisor.agents[0].config.model == "fast-model-v1"
    assert supervisor.agents[1].config.model == "reasoning-model-v2"
    assert supervisor.agents[2].config.model == "critic-model-v3"
    assert supervisor.agents[3].config.model is None  # Report has no override


def test_per_agent_model_from_env(tool_context, monkeypatch):
    """Model configs can come from environment variables."""
    monkeypatch.setenv("MULTI_AGENT_ANALYSIS_MODEL", "deepseek-r1")
    monkeypatch.setenv("MULTI_AGENT_CRITIC_MODEL", "gpt-4o")

    supervisor = Supervisor(tool_context)
    assert supervisor.agents[1].config.model == "deepseek-r1"
    assert supervisor.agents[2].config.model == "gpt-4o"
    assert supervisor.agents[0].config.model is None  # not set


def test_model_isolation_between_agents(tool_context):
    """Model override should not bleed between agents."""
    from backend.app.agent.multi import AgentConfig

    configs = {
        AgentRole.RETRIEVAL: AgentConfig(model="model-A"),
        AgentRole.ANALYSIS: AgentConfig(model="model-B"),
    }
    supervisor = Supervisor(tool_context, agent_configs=configs)
    request = AnalyzeRequest(raw_input="测试模型隔离")

    report = supervisor.run(request)
    assert report is not None

    # After all agents run, the reasoner's model_override should be restored
    reasoner = tool_context.agent_reasoner
    assert getattr(reasoner, "model_override", None) is None


def test_request_level_model_override(tool_context):
    """Per-request agent_models in request_context should override agent configs."""
    supervisor = Supervisor(tool_context)
    request = AnalyzeRequest(
        raw_input="测试请求级模型覆盖",
        request_context={
            "agent_models": {
                "retrieval": "fast-model",
                "analysis": "reasoning-model",
                "critic": "critic-model",
            }
        },
    )
    report = supervisor.run(request)
    assert report is not None
    assert supervisor.agents[0].config.model == "fast-model"
    assert supervisor.agents[1].config.model == "reasoning-model"
    assert supervisor.agents[2].config.model == "critic-model"


# --- CriticAgent: real verification (was dead code before) ---


def _fact_claim(claim, verdict, evidence=None):
    from backend.app.models.schemas import ClaimResult
    return ClaimResult(
        claim=claim,
        claim_type="fact",
        verdict=verdict,
        confidence="high",
        evidence=evidence or [],
        notes="",
    )


def _evidence(tier="C"):
    from backend.app.models.schemas import EvidenceItem
    return EvidenceItem(
        title="t", url="http://x", source_name="s", published_at="2026-01-01",
        snippet="snip", relevance_reason="r", source_tier=tier,
    )


def _verdict(claim_results):
    from backend.app.services.verdict_engine import VerdictEvaluation
    return VerdictEvaluation(
        claim_results=claim_results, evidence=[], evidence_grade="weak",
        evidence_source="retrieval_live",
    )


class _StubSettings:
    agent_synthesis_critic_enabled = True
    multi_agent_critic_perspectives = 1


class _StubCtx:
    """Minimal ToolContext stand-in: only what CriticAgent reads."""
    def __init__(self, reasoner=None, settings=None):
        self.agent_reasoner = reasoner
        self.settings = settings or _StubSettings()


def test_critic_rule_path_downgrades_weak_source():
    """Zero-LLM critic: a decisive verdict with only one C-tier source is downgraded."""
    from backend.app.agent.multi.critic_agent import CriticAgent
    from backend.app.agent.state import AgentState
    from backend.app.models.schemas import AnalyzeRequest

    state = AgentState(request=AnalyzeRequest(raw_input="x"))
    state.verdict = _verdict([_fact_claim("传闻A", "supported", [_evidence("C")])])
    ctx = _StubCtx(reasoner=None)  # no LLM → rule path

    result = CriticAgent().run(state, ctx)
    assert result.status.value == "completed"
    assert state.verdict.claim_results[0].verdict == "insufficient"


def test_critic_rule_path_keeps_strong_source():
    """A decisive verdict backed by an A-tier source survives."""
    from backend.app.agent.multi.critic_agent import CriticAgent
    from backend.app.agent.state import AgentState
    from backend.app.models.schemas import AnalyzeRequest

    state = AgentState(request=AnalyzeRequest(raw_input="x"))
    state.verdict = _verdict([_fact_claim("传闻B", "refuted", [_evidence("A")])])
    ctx = _StubCtx(reasoner=None)

    CriticAgent().run(state, ctx)
    assert state.verdict.claim_results[0].verdict == "refuted"


def test_critic_llm_path_union_of_perspectives():
    """Multi-perspective LLM critic downgrades the UNION of flagged indices."""
    from backend.app.agent.multi.critic_agent import CriticAgent
    from backend.app.agent.state import AgentState
    from backend.app.models.schemas import AnalyzeRequest

    calls = {"n": 0}

    class _FakeReasoner:
        enabled = True
        model_override = None

        def critique_claims(self, claim_results):
            # Perspective 0 flags claim 0; perspective 1 flags claim 1.
            idx = calls["n"] % 2
            calls["n"] += 1
            return claim_results, {idx}

    state = AgentState(request=AnalyzeRequest(raw_input="x"))
    state.verdict = _verdict([
        _fact_claim("c0", "supported", [_evidence("A")]),
        _fact_claim("c1", "refuted", [_evidence("A")]),
    ])
    settings = _StubSettings()
    settings.multi_agent_critic_perspectives = 2
    ctx = _StubCtx(reasoner=_FakeReasoner(), settings=settings)

    CriticAgent().run(state, ctx)
    # Both claims downgraded (union of {0} and {1}).
    assert state.verdict.claim_results[0].verdict == "insufficient"
    assert state.verdict.claim_results[1].verdict == "insufficient"
    assert calls["n"] == 2


# --- Supervisor LLM routing ---


def test_llm_routing_disabled_falls_back_to_rule():
    """With routing off, loop-back uses the >70% insufficient rule threshold."""
    from backend.app.agent.multi.supervisor import Supervisor
    from backend.app.agent.state import AgentState
    from backend.app.models.schemas import AnalyzeRequest
    from backend.app.agent_tools.base import ToolContext

    class _S:
        multi_agent_llm_routing_enabled = False

    ctx = ToolContext.__new__(ToolContext)
    ctx.settings = _S()
    ctx.agent_reasoner = None
    sup = Supervisor.__new__(Supervisor)
    sup.ctx = ctx

    state = AgentState(request=AnalyzeRequest(raw_input="x"))
    state.verdict = _verdict([
        _fact_claim("c0", "insufficient"),
        _fact_claim("c1", "insufficient"),
        _fact_claim("c2", "supported"),
    ])
    # 2/3 = 0.67 < 0.7 → no loop-back
    assert sup._should_loop_back(state) is False
    state.verdict.claim_results[2].verdict = "insufficient"  # now 3/3
    assert sup._should_loop_back(state) is True


def test_llm_routing_enabled_uses_reasoner():
    """With routing on, the reasoner's plan_next_action decides loop-back."""
    from backend.app.agent.multi.supervisor import Supervisor
    from backend.app.agent.state import AgentState
    from backend.app.models.schemas import AnalyzeRequest
    from backend.app.agent_tools.base import ToolContext
    from backend.app.services.agent_reasoner import NextActionPlan

    class _S:
        multi_agent_llm_routing_enabled = True

    class _FakeReasoner:
        enabled = True

        def plan_next_action(self, *, evidence_snapshot, allowed_actions):
            assert set(allowed_actions) == {"loop_back", "finalize"}
            return NextActionPlan(next_action="finalize", reason="证据充足")

    ctx = ToolContext.__new__(ToolContext)
    ctx.settings = _S()
    ctx.agent_reasoner = _FakeReasoner()
    sup = Supervisor.__new__(Supervisor)
    sup.ctx = ctx

    state = AgentState(request=AnalyzeRequest(raw_input="x"))
    # All insufficient → rule would loop back, but LLM says finalize.
    state.verdict = _verdict([_fact_claim("c0", "insufficient")])
    assert sup._should_loop_back(state) is False


def test_loop_back_fires_at_most_once():
    """The supervisor_loop_back marker prevents infinite re-entry."""
    from backend.app.agent.multi.supervisor import Supervisor
    from backend.app.agent.state import AgentState
    from backend.app.models.schemas import AnalyzeRequest
    from backend.app.agent_tools.base import ToolContext

    class _S:
        multi_agent_llm_routing_enabled = False

    ctx = ToolContext.__new__(ToolContext)
    ctx.settings = _S()
    ctx.agent_reasoner = None
    sup = Supervisor.__new__(Supervisor)
    sup.ctx = ctx

    state = AgentState(request=AnalyzeRequest(raw_input="x"))
    state.verdict = _verdict([_fact_claim("c0", "insufficient")])
    assert sup._should_loop_back(state) is True
    state.done_actions.append("supervisor_loop_back")
    assert sup._should_loop_back(state) is False


def test_agent_message_removed():
    """AgentMessage was dead scaffolding — it should no longer be exported."""
    import backend.app.agent.multi as multi
    assert not hasattr(multi, "AgentMessage")
