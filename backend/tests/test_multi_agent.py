"""Tests for the multi-agent Supervisor architecture."""
from __future__ import annotations

import pytest

from backend.app.agent.multi import AgentRole, AgentStatus
from backend.app.agent.multi.analysis_agent import AnalysisAgent
from backend.app.agent.multi.critic_agent import CriticAgent
from backend.app.agent.multi.report_agent import ReportAgent
from backend.app.agent.multi.retrieval_agent import RetrievalAgent
from backend.app.agent.multi.supervisor import Supervisor
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
    supervisor = Supervisor(tool_context, retrieval_mode="sequential")
    request = AnalyzeRequest(raw_input="听说京东开始造游轮了")
    report = supervisor.run(request)
    assert report is not None
    assert hasattr(report, "claim_results") or hasattr(report, "credibility_label")


def test_supervisor_default_agents():
    """Sequential DAG should be Retrieval -> Analysis -> Critic -> Report."""
    from backend.app.agent_tools.base import ToolContext
    ctx = ToolContext.__new__(ToolContext)
    supervisor = Supervisor(ctx, retrieval_mode="sequential")
    roles = [a.role for a in supervisor.agents]
    assert roles == [AgentRole.RETRIEVAL, AgentRole.ANALYSIS, AgentRole.CRITIC, AgentRole.REPORT]


def test_parallel_dag_fans_out_sources():
    """Parallel DAG: normalize -> 4 source agents (all dep only on normalize) -> merge -> chain."""
    from backend.app.agent.multi.source_agents import SOURCE_ROLES
    from backend.app.agent_tools.base import ToolContext
    ctx = ToolContext.__new__(ToolContext)
    supervisor = Supervisor(ctx, retrieval_mode="parallel")
    roles = [a.role for a in supervisor.agents]
    assert roles[0] == AgentRole.NORMALIZE
    assert set(SOURCE_ROLES).issubset(set(roles))
    assert AgentRole.RETRIEVAL_MERGE in roles
    # Every source agent depends solely on NORMALIZE, so they're all ready in the
    # same tick — that's what makes the fan-out genuinely parallel.
    for agent in supervisor.agents:
        if agent.role in SOURCE_ROLES:
            assert agent.dependencies == [AgentRole.NORMALIZE]
    # Merge waits on all four source roles.
    merge = next(a for a in supervisor.agents if a.role == AgentRole.RETRIEVAL_MERGE)
    assert set(merge.dependencies) == set(SOURCE_ROLES)


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
    supervisor = Supervisor(tool_context, retrieval_mode="sequential")
    request = AnalyzeRequest(raw_input="听说京东开始造游轮了")
    state = AgentState(request=request)
    state.cancelled = True
    # Directly test the _ready_agents logic with cancelled state
    # (full run would still attempt force_finalize)
    agent_map = {a.role: a for a in supervisor.agents}
    ready = supervisor._ready_agents(agent_map, set(), set())
    assert AgentRole.RETRIEVAL in [a.role for a in ready]


def test_dependency_graph_resolution():
    """When retrieval fails, analysis/critic/report should be skipped (sequential DAG)."""
    from backend.app.agent_tools.base import ToolContext
    ctx = ToolContext.__new__(ToolContext)
    supervisor = Supervisor(ctx, retrieval_mode="sequential")
    agent_map = {a.role: a for a in supervisor.agents}
    failed = {AgentRole.RETRIEVAL}
    completed = set()
    ready = supervisor._ready_agents(agent_map, completed, failed)
    # Nothing should be ready since all depend (transitively) on retrieval
    assert len(ready) == 0


def test_parallel_normalize_failure_cascades():
    """Parallel DAG: when NORMALIZE fails, all source agents + downstream are skipped."""
    from backend.app.agent_tools.base import ToolContext
    ctx = ToolContext.__new__(ToolContext)
    supervisor = Supervisor(ctx, retrieval_mode="parallel")
    agent_map = {a.role: a for a in supervisor.agents}
    ready = supervisor._ready_agents(agent_map, completed=set(), failed={AgentRole.NORMALIZE})
    # No source agent can run (all depend on NORMALIZE), so nothing is ready.
    assert ready == []


def test_per_agent_model_config(tool_context):
    """Each agent should use its configured model and restore after."""
    from backend.app.agent.multi import AgentConfig

    configs = {
        AgentRole.RETRIEVAL: AgentConfig(model="fast-model-v1"),
        AgentRole.ANALYSIS: AgentConfig(model="reasoning-model-v2"),
        AgentRole.CRITIC: AgentConfig(model="critic-model-v3"),
    }
    supervisor = Supervisor(tool_context, agent_configs=configs, retrieval_mode="sequential")

    assert supervisor.agents[0].config.model == "fast-model-v1"
    assert supervisor.agents[1].config.model == "reasoning-model-v2"
    assert supervisor.agents[2].config.model == "critic-model-v3"
    assert supervisor.agents[3].config.model is None  # Report has no override


def test_per_agent_model_from_env(tool_context, monkeypatch):
    """Model configs can come from environment variables."""
    monkeypatch.setenv("MULTI_AGENT_ANALYSIS_MODEL", "deepseek-r1")
    monkeypatch.setenv("MULTI_AGENT_CRITIC_MODEL", "gpt-4o")

    supervisor = Supervisor(tool_context, retrieval_mode="sequential")
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
    supervisor = Supervisor(tool_context, agent_configs=configs, retrieval_mode="sequential")
    request = AnalyzeRequest(raw_input="测试模型隔离")

    report = supervisor.run(request)
    assert report is not None

    # After all agents run, the reasoner's model_override should be restored
    reasoner = tool_context.agent_reasoner
    assert getattr(reasoner, "model_override", None) is None


def test_request_level_model_override(tool_context):
    """Per-request agent_models in request_context should override agent configs."""
    supervisor = Supervisor(tool_context, retrieval_mode="sequential")
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


def test_critic_llm_path_majority_vote():
    """Multi-perspective LLM critic downgrades only when ≥2 lenses flag a claim."""
    from backend.app.agent.multi.critic_agent import CriticAgent
    from backend.app.agent.state import AgentState
    from backend.app.models.schemas import AnalyzeRequest

    calls = {"n": 0}

    class _FakeReasoner:
        enabled = True
        model_override = None

        def critique_claims(self, claim_results, lens_instruction=None):
            # All perspectives flag claim 0; only one flags claim 1.
            calls["n"] += 1
            if calls["n"] <= 2:
                return claim_results, {0}
            return claim_results, {1}

    state = AgentState(request=AnalyzeRequest(raw_input="x"))
    state.verdict = _verdict([
        _fact_claim("c0", "supported", [_evidence("A")]),
        _fact_claim("c1", "refuted", [_evidence("A")]),
    ])
    settings = _StubSettings()
    settings.multi_agent_critic_perspectives = 3
    ctx = _StubCtx(reasoner=_FakeReasoner(), settings=settings)

    CriticAgent().run(state, ctx)
    # Claim 0 downgraded (flagged by 2/3 lenses), claim 1 NOT (flagged by 1/3).
    assert state.verdict.claim_results[0].verdict == "insufficient"
    assert state.verdict.claim_results[1].verdict == "refuted"
    assert calls["n"] == 3


# --- Supervisor LLM routing ---


def test_llm_routing_disabled_falls_back_to_rule():
    """With routing off, loop-back uses the >70% insufficient rule threshold."""
    from backend.app.agent.multi.supervisor import Supervisor
    from backend.app.agent.state import AgentState
    from backend.app.agent_tools.base import ToolContext
    from backend.app.models.schemas import AnalyzeRequest

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
    from backend.app.agent_tools.base import ToolContext
    from backend.app.models.schemas import AnalyzeRequest
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
    from backend.app.agent_tools.base import ToolContext
    from backend.app.models.schemas import AnalyzeRequest

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


def test_dead_config_fields_removed():
    """temperature/output/IDLE/RUNNING were dead — they should be gone."""
    from backend.app.agent.multi import AgentConfig, AgentStatus, SubAgentResult
    assert not hasattr(AgentConfig(), "temperature")
    assert not hasattr(SubAgentResult(role=AgentRole.REPORT, status=AgentStatus.COMPLETED), "output")
    assert not hasattr(AgentStatus, "IDLE")
    assert not hasattr(AgentStatus, "RUNNING")


# --- Parallel retrieval DAG ---


def _bundle_with(source_key, n):
    """A minimal RetrievalBundle carrying n canonical results tagged by source."""
    from backend.app.services.retrieval_models import RetrievalBundle, SearchResult
    results = tuple(
        SearchResult(
            case_id="c", query="q", result_id=f"{source_key}-{i}",
            title=f"{source_key} hit {i}", url=f"http://{source_key}.test/{i}",
            source_name=source_key, published_at="2026-01-01", snippet="s",
            source_tier="C", independence_key=f"{source_key}-{i}",
        )
        for i in range(n)
    )
    return RetrievalBundle(query="q", canonical_results=results, raw_results=results)


def test_retrieval_mode_selects_dag():
    """The retrieval_mode arg picks which topology the supervisor builds."""
    from backend.app.agent_tools.base import ToolContext
    ctx = ToolContext.__new__(ToolContext)
    seq = {a.role for a in Supervisor(ctx, retrieval_mode="sequential").agents}
    par = {a.role for a in Supervisor(ctx, retrieval_mode="parallel").agents}
    assert AgentRole.RETRIEVAL in seq and AgentRole.NORMALIZE not in seq
    assert AgentRole.NORMALIZE in par and AgentRole.RETRIEVAL_MERGE in par


def test_fan_out_is_parallel():
    """4 source agents each sleeping 0.4s must finish in well under their 1.6s sum."""
    import time

    from backend.app.agent.multi import AgentRole as R
    from backend.app.agent.multi import AgentStatus, SubAgentResult
    from backend.app.agent_tools.base import ToolContext

    class _SleepAgent:
        def __init__(self, role):
            self.role = role
            self.config = None  # no model → passes the parallel model assertion
            self.description = "sleep"
        @property
        def dependencies(self):
            return []
        def run(self, state, ctx):
            time.sleep(0.4)
            return SubAgentResult(role=self.role, status=AgentStatus.COMPLETED)

    ctx = ToolContext.__new__(ToolContext)
    ctx.agent_reasoner = None
    sup = Supervisor.__new__(Supervisor)
    sup.ctx = ctx
    sup.max_parallel = 4
    agents = [_SleepAgent(r) for r in (R.RETRIEVAL_BAIDU, R.RETRIEVAL_XHS, R.RETRIEVAL_TOUTIAO, R.RETRIEVAL_WEIXIN)]

    state = AgentState(request=AnalyzeRequest(raw_input="x"))
    t0 = time.monotonic()
    results = sup._execute_batch(agents, state, deadline=None)
    elapsed = time.monotonic() - t0
    assert len(results) == 4
    assert all(r.status == AgentStatus.COMPLETED for r in results)
    assert elapsed < 1.0, f"fan-out not parallel: {elapsed:.2f}s"


def test_parallel_batch_propagates_progress_context():
    """Progress events emitted from a parallel-batch worker must reach the parent
    callback. ContextVars don't cross into pool threads by default, so without
    context propagation every source-agent emit_log/emit_api_call silently no-ops
    and the whole parallel retrieval phase vanishes from the trace UI."""
    from backend.app.agent.multi import AgentRole as R
    from backend.app.agent.multi import AgentStatus, SubAgentResult
    from backend.app.agent_tools.base import ToolContext
    from backend.app.services.progress import emit_log, reset_progress_callback, set_progress_callback

    class _EmittingAgent:
        def __init__(self, role):
            self.role = role
            self.config = None
            self.description = "emit"
        @property
        def dependencies(self):
            return []
        def run(self, state, ctx):
            emit_log(stage_key=f"agent_retrieval_{self.role.value}", title="worker", summary="from thread")
            return SubAgentResult(role=self.role, status=AgentStatus.COMPLETED)

    ctx = ToolContext.__new__(ToolContext)
    ctx.agent_reasoner = None
    sup = Supervisor.__new__(Supervisor)
    sup.ctx = ctx
    sup.max_parallel = 4
    agents = [_EmittingAgent(r) for r in (R.RETRIEVAL_BAIDU, R.RETRIEVAL_XHS)]

    events: list = []
    token = set_progress_callback(lambda e: events.append(e))
    try:
        state = AgentState(request=AnalyzeRequest(raw_input="x"))
        sup._execute_batch(agents, state, deadline=None)
    finally:
        reset_progress_callback(token)

    # Both workers' log events must have reached the parent callback.
    worker_logs = [e for e in events if e.get("type") == "log" and e.get("summary") == "from thread"]
    assert len(worker_logs) == 2, f"expected 2 propagated events, got {len(worker_logs)}"


def test_parallel_batch_rejects_model_override():
    """A parallel batch with any agent declaring a model must raise (race guard)."""
    from backend.app.agent.multi import AgentConfig, AgentStatus, SubAgentResult
    from backend.app.agent.multi import AgentRole as R
    from backend.app.agent_tools.base import ToolContext

    class _A:
        def __init__(self, role, model):
            self.role = role
            self.config = AgentConfig(model=model)
            self.description = "a"
        @property
        def dependencies(self):
            return []
        def run(self, state, ctx):
            return SubAgentResult(role=self.role, status=AgentStatus.COMPLETED)

    ctx = ToolContext.__new__(ToolContext)
    sup = Supervisor.__new__(Supervisor)
    sup.ctx = ctx
    sup.max_parallel = 2
    agents = [_A(R.RETRIEVAL_BAIDU, None), _A(R.RETRIEVAL_XHS, "some-model")]
    state = AgentState(request=AnalyzeRequest(raw_input="x"))
    with pytest.raises(RuntimeError, match="parallel_batch_declares_model_override"):
        sup._execute_batch(agents, state, deadline=None)


def test_merge_agent_combines_bundles():
    """MergeAgent unions per-source bundles into a deduped retrieval_bundle."""
    from backend.app.agent.multi.merge_agent import MergeAgent
    from backend.app.agent_tools.base import ToolContext

    class _S:
        lightweight_agent_ready = False
    ctx = ToolContext.__new__(ToolContext)
    ctx.settings = _S()
    ctx.agent_reasoner = None

    state = AgentState(request=AnalyzeRequest(raw_input="x"))
    state.primary_query = "q"
    state.source_bundles = {
        "baidu": _bundle_with("baidu", 3),
        "xiaohongshu": _bundle_with("xiaohongshu", 2),
        "toutiao": _bundle_with("toutiao", 0),
        "sogou_weixin": _bundle_with("sogou_weixin", 1),
    }
    # Merge only (skip refinement tools: no question_resolution, no fetch budget).
    merged = MergeAgent()._merge_source_bundles(state)
    assert merged is not None
    # 3+2+0+1 = 6 distinct results across sources (all independence keys unique).
    assert len(merged.canonical_results) == 6
    # result_ids are namespaced by source so nothing collides.
    ids = [r.result_id for r in merged.canonical_results]
    assert len(ids) == len(set(ids))
    assert any(i.startswith("baidu::") for i in ids)
    assert any(i.startswith("sogou_weixin::") for i in ids)


def test_merge_agent_handles_all_empty():
    """No source produced anything → merge returns None, no crash."""
    from backend.app.agent.multi.merge_agent import MergeAgent
    state = AgentState(request=AnalyzeRequest(raw_input="x"))
    state.source_bundles = {}
    assert MergeAgent()._merge_source_bundles(state) is None


def test_token_usage_add_threadsafe():
    """Concurrent add() from many threads must not lose increments."""
    import threading

    from backend.app.agent.state import TokenUsage

    usage = TokenUsage()
    n_threads, per_thread = 16, 500

    def _hammer():
        for _ in range(per_thread):
            usage.add(prompt=1, completion=1)

    threads = [threading.Thread(target=_hammer) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert usage.call_count == n_threads * per_thread
    assert usage.prompt_tokens == n_threads * per_thread
    assert usage.total_tokens == n_threads * per_thread * 2


def test_source_agent_skips_when_deselected():
    """A source agent must SKIP when its key isn't in request_context.search_sources,
    so the frontend source toggle actually takes effect on the parallel DAG."""
    from backend.app.agent.multi import AgentRole as R
    from backend.app.agent.multi.source_agents import SourceRetrievalAgent
    from backend.app.agent_tools.base import ToolContext

    ctx = ToolContext.__new__(ToolContext)
    agent = SourceRetrievalAgent(role=R.RETRIEVAL_TOUTIAO, source_key="toutiao", force_primary_query=True)
    # User selected only baidu + xiaohongshu; toutiao is deselected.
    state = AgentState(request=AnalyzeRequest(
        raw_input="x",
        request_context={"search_sources": ["baidu", "xiaohongshu"]},
    ))
    result = agent.run(state, ctx)
    assert result.status == AgentStatus.SKIPPED
    assert "toutiao" not in state.source_bundles


def test_source_agent_runs_when_no_filter():
    """With no search_sources filter, the source agent proceeds to retrieval (it
    fails fast here only because the bare ToolContext has no retriever — the point
    is it does NOT short-circuit to SKIPPED)."""
    from backend.app.agent.multi import AgentRole as R
    from backend.app.agent.multi.source_agents import SourceRetrievalAgent
    from backend.app.agent_tools.base import ToolContext

    ctx = ToolContext.__new__(ToolContext)
    agent = SourceRetrievalAgent(role=R.RETRIEVAL_BAIDU, source_key="baidu", force_primary_query=False)
    state = AgentState(request=AnalyzeRequest(raw_input="x"))  # no search_sources key
    result = agent.run(state, ctx)
    assert result.status != AgentStatus.SKIPPED


def test_run_summary_emits_metrics_event(tool_context):
    """The supervisor emits a structured `metrics` progress event at end of run,
    carrying mode, timings, token usage, and per-source hit counts."""
    from backend.app.services.progress import reset_progress_callback, set_progress_callback

    events: list = []
    token = set_progress_callback(lambda e: events.append(e))
    try:
        supervisor = Supervisor(tool_context, retrieval_mode="sequential")
        supervisor.run(AnalyzeRequest(raw_input="听说京东开始造游轮了"))
    finally:
        reset_progress_callback(token)

    metrics_events = [e for e in events if e.get("type") == "metrics"]
    assert len(metrics_events) == 1
    m = metrics_events[0]["metrics"]
    assert m["mode"] == "sequential"
    assert m["total_ms"] >= 0
    assert "tokens" in m and "total" in m["tokens"]
    assert isinstance(m["agents"], list) and len(m["agents"]) >= 1
    # Every agent entry carries a timing field for the observability panel.
    assert all("elapsed_ms" in a for a in m["agents"])
