from __future__ import annotations

from backend.app.agent.state import AgentState
from backend.app.agent_tools.base import ToolContext
from backend.app.services.analyze_pipeline import (
    _bundle_quality,
    _claim_details,
    _event_details,
    _question_resolution_details,
    _retrieval_bundle_details,
    _timeline_details,
)
from backend.app.services.progress import emit_log, emit_stage

# Provenance fallback reason: LLM synthesis was expected (Kimi enabled) but did
# not produce a grounded result, so the rule engine answered instead.
LLM_SYNTHESIS_FALLBACK_REASON = "llm_synthesis_unavailable_rule_fallback"


def normalize(ctx: ToolContext, state: AgentState) -> None:
    request = state.request
    emit_stage(
        stage_key="normalize_input",
        title="标准化输入",
        status="running",
        summary="正在识别输入类型并抽取基础事件线索。",
        details=[
            f"input_type={request.input_type or 'auto'}",
            f"input_chars={len(request.raw_input.strip())}",
        ],
    )
    normalized_event = ctx.input_normalizer.normalize(request)
    state.normalized_event = normalized_event
    state.resolved_event = normalized_event
    emit_stage(
        stage_key="normalize_input",
        title="标准化输入",
        status="completed",
        summary="已整理出初始事件草稿。",
        details=_event_details(normalized_event),
    )
    state.record("normalize", "标准化输入完成", _event_details(normalized_event))


def search_news(ctx: ToolContext, state: AgentState) -> None:
    emit_stage(
        stage_key="retrieval_initial",
        title="首轮检索",
        status="running",
        summary="正在生成 query plan 并拉取第一批公开网页结果。",
        details=[f"provider={ctx.settings.retrieval_provider}"],
    )
    bundle = ctx.retriever.retrieve_for_event(
        state.normalized_event, request_context=state.request.request_context
    )
    state.initial_retrieval_bundle = bundle
    state.retrieval_bundle = bundle
    emit_stage(
        stage_key="retrieval_initial",
        title="首轮检索",
        status="completed",
        summary="首轮检索已返回结果集。",
        details=_retrieval_bundle_details(bundle),
    )
    state.record("search_news", "首轮检索完成", _retrieval_bundle_details(bundle))


def resolve_question(ctx: ToolContext, state: AgentState) -> None:
    event = state.normalized_event
    bundle = state.initial_retrieval_bundle
    emit_stage(
        stage_key="question_resolution",
        title="问题消歧",
        status="running",
        summary="正在判断这次输入是否能稳定锚定到单一事件。",
        details=[f"question_only={event.input_type == 'question_only'}"],
    )
    resolution = _resolve_question(ctx, event=event, retrieval_bundle=bundle)
    state.question_resolution = resolution
    state.resolved_event = resolution.event
    status = "skipped" if event.input_type != "question_only" else "completed"
    summary = "输入不是纯问题，沿用当前事件草稿。" if status == "skipped" else "问题消歧已完成。"
    emit_stage(
        stage_key="question_resolution",
        title="问题消歧",
        status=status,
        summary=summary,
        details=_question_resolution_details(resolution),
    )
    state.record("resolve_question", summary, _question_resolution_details(resolution))


def follow_up_retrieval(ctx: ToolContext, state: AgentState) -> None:
    resolution = state.question_resolution
    if resolution is not None and resolution.follow_up_query:
        emit_stage(
            stage_key="retrieval_follow_up",
            title="追加检索",
            status="running",
            summary="已根据候选事件生成 follow-up query，正在补抓更精准的结果。",
            details=[f"follow_up_query={resolution.follow_up_query}"],
        )
        follow_up_context = dict(state.request.request_context)
        follow_up_context["force_retrieval_query"] = resolution.follow_up_query
        follow_up_bundle = ctx.retriever.retrieve_for_event(
            state.resolved_event, request_context=follow_up_context
        )
        state.follow_up_bundle = follow_up_bundle
        if follow_up_bundle.canonical_results or follow_up_bundle.matched_case_id:
            state.retrieval_bundle = follow_up_bundle
            state.follow_up_used = True
        emit_stage(
            stage_key="retrieval_follow_up",
            title="追加检索",
            status="completed",
            summary="follow-up 检索已结束。",
            details=_retrieval_bundle_details(follow_up_bundle),
        )
    else:
        emit_stage(
            stage_key="retrieval_follow_up",
            title="追加检索",
            status="skipped",
            summary="当前输入不需要 follow-up query。",
            details=[],
        )
    state.record("follow_up_retrieval", "follow-up 阶段结束")


def investigate(ctx: ToolContext, state: AgentState) -> None:
    """Optional evidence-driven extra retrieval rounds (LLM planner)."""
    if not ctx.settings.lightweight_agent_ready or not ctx.agent_reasoner.enabled:
        return
    bundle = state.retrieval_bundle
    if bundle is None:
        return

    max_rounds = ctx.settings.agent_max_extra_rounds
    current_bundle = bundle
    for round_index in range(1, max_rounds + 1):
        emit_stage(
            stage_key="investigation_plan",
            title="调查决策",
            status="running",
            summary=f"第 {round_index} 轮：正在评估当前证据是否足够，决定要不要再补一轮检索。",
            details=[
                f"round={round_index}/{max_rounds}",
                f"evidence_grade={current_bundle.evidence_grade}",
                f"independent_high_trust={current_bundle.independent_high_trust_source_count}",
            ],
        )
        try:
            plan = ctx.agent_reasoner.plan_investigation(
                event=state.resolved_event,
                retrieval_bundle=current_bundle,
                round_index=round_index,
            )
        except Exception as exc:
            emit_log(
                stage_key="investigation_plan",
                level="warning",
                title="调查决策失败",
                summary="investigation planner 抛错，停止补检索并沿用当前证据。",
                details=[f"error_type={exc.__class__.__name__}"],
            )
            break

        if plan is None or not plan.should_continue or not plan.follow_up_query:
            emit_stage(
                stage_key="investigation_plan",
                title="调查决策",
                status="completed",
                summary="决策：当前证据已足够或无法收紧，停止补检索。",
                details=[f"reason={plan.reason}" if plan is not None else "reason=planner_unavailable"],
            )
            break

        emit_stage(
            stage_key="investigation_plan",
            title="调查决策",
            status="completed",
            summary="决策：证据仍偏弱，追加一轮定向检索。",
            details=[f"reason={plan.reason}", f"follow_up_query={plan.follow_up_query}"],
        )

        follow_up_context = dict(state.request.request_context)
        follow_up_context["force_retrieval_query"] = plan.follow_up_query
        emit_stage(
            stage_key="investigation_retrieval",
            title="调查补检索",
            status="running",
            summary="正在按调查决策补抓更权威的结果。",
            details=[f"follow_up_query={plan.follow_up_query}"],
        )
        candidate_bundle = ctx.retriever.retrieve_for_event(
            state.resolved_event, request_context=follow_up_context
        )
        adopted = _bundle_quality(candidate_bundle) > _bundle_quality(current_bundle)
        emit_stage(
            stage_key="investigation_retrieval",
            title="调查补检索",
            status="completed" if adopted else "warning",
            summary="补检索获得更强证据，已采用。" if adopted else "补检索未带来更强证据，沿用原结果。",
            details=[
                f"adopted={adopted}",
                f"grade={current_bundle.evidence_grade}->{candidate_bundle.evidence_grade}",
                f"independent_high_trust={current_bundle.independent_high_trust_source_count}"
                f"->{candidate_bundle.independent_high_trust_source_count}",
            ],
        )
        state.investigation_rounds += 1
        if adopted:
            current_bundle = candidate_bundle
    state.retrieval_bundle = current_bundle


def synthesize(ctx: ToolContext, state: AgentState) -> bool:
    """Try the agent synthesis path. Returns True if it produced a result."""
    # "Attempted" only when the LLM reasoner is actually enabled — on the
    # zero-key off+mock path this stays False so no fallback signal is emitted.
    state.synthesis_attempted = bool(getattr(ctx.agent_reasoner, "enabled", False))
    emit_stage(
        stage_key="agent_synthesis",
        title="Agent 综合判断",
        status="running",
        summary="正在让 Kimi 基于检索结果生成事件、claims、verdict 和 timeline。",
        details=[f"enabled={ctx.agent_reasoner.enabled}"],
    )
    agent_synthesis = _synthesize_with_agent(
        ctx,
        request=state.request,
        event=state.resolved_event,
        retrieval_bundle=state.retrieval_bundle,
    )
    if agent_synthesis is None:
        emit_stage(
            stage_key="agent_synthesis",
            title="Agent 综合判断",
            status="warning",
            summary="Agent 没有稳定产出，退回规则兜底链路。",
            details=[
                f"retrieval_hits={len(state.retrieval_bundle.canonical_results) if state.retrieval_bundle else 0}"
            ],
        )
        return False

    state.final_event = agent_synthesis.event
    state.provider_claims = agent_synthesis.claim_extraction.claims
    state.claim_extraction = agent_synthesis.claim_extraction
    state.verdict = agent_synthesis.verdict
    state.timeline = agent_synthesis.timeline
    state.agent_synthesized = True
    emit_stage(
        stage_key="agent_synthesis",
        title="Agent 综合判断",
        status="completed",
        summary="Agent 路径已产出结构化结论。",
        details=[
            f"event_title={state.final_event.title or 'unknown'}",
            f"claims={len(state.claim_extraction.claims)}",
            f"timeline_nodes={len(state.timeline.nodes)}",
            f"evidence_grade={state.verdict.evidence_grade}",
        ],
    )
    state.record("synthesize", "Agent 综合判断完成")
    return True


def enrich(ctx: ToolContext, state: AgentState) -> None:
    emit_stage(
        stage_key="provider_enrichment",
        title="结构化补全",
        status="running",
        summary="正在调用 provider 对事件和 claims 做结构化补全。",
        details=[],
    )
    try:
        event, provider_claims = ctx.provider_enricher.enrich(state.resolved_event)
        status = "completed"
        summary = "Provider enrichment 已返回结构化事件草稿。"
        details = _event_details(event)
    except Exception as exc:
        event, provider_claims = state.resolved_event, None
        status = "warning"
        summary = "Provider enrichment 失败，继续使用当前事件草稿。"
        details = [f"error_type={exc.__class__.__name__}"]
    state.final_event = event
    state.provider_claims = provider_claims
    emit_stage(
        stage_key="provider_enrichment",
        title="结构化补全",
        status=status,
        summary=summary,
        details=details,
    )
    state.record("enrich", summary, details)


def extract_claims(ctx: ToolContext, state: AgentState) -> None:
    emit_stage(
        stage_key="claim_extraction",
        title="Claim 拆解",
        status="running",
        summary="正在把事件表述拆成可核查的 atomic claims。",
        details=[],
    )
    claim_extraction = ctx.claim_extractor.extract_with_source(
        state.final_event, provider_claims=state.provider_claims
    )
    state.claim_extraction = claim_extraction
    emit_stage(
        stage_key="claim_extraction",
        title="Claim 拆解",
        status="completed",
        summary="Claim 拆解完成。",
        details=_claim_details(claim_extraction.claims),
    )
    state.record("extract_claims", "Claim 拆解完成", _claim_details(claim_extraction.claims))


def judge_claims(ctx: ToolContext, state: AgentState) -> None:
    emit_stage(
        stage_key="verdict_engine",
        title="Claim 判定",
        status="running",
        summary="正在结合 retrieval hits 为每条 claim 打 verdict。",
        details=[],
    )
    verdict = ctx.verdict_engine.evaluate_with_source(
        request=state.request,
        event=state.final_event,
        claims=state.claim_extraction.claims,
        retrieval_bundle=state.retrieval_bundle,
    )
    state.verdict = verdict
    emit_stage(
        stage_key="verdict_engine",
        title="Claim 判定",
        status="completed",
        summary="Claim verdict 已生成。",
        details=[
            f"claim_results={len(verdict.claim_results)}",
            f"evidence_items={len(verdict.evidence)}",
            f"evidence_grade={verdict.evidence_grade}",
            f"evidence_source={verdict.evidence_source}",
        ],
    )
    state.record("judge_claims", "Claim 判定完成")


def build_timeline(ctx: ToolContext, state: AgentState) -> None:
    emit_stage(
        stage_key="timeline_builder",
        title="时间线构建",
        status="running",
        summary="正在从检索结果里挑选传播与澄清节点。",
        details=[],
    )
    timeline = ctx.timeline_builder.build_with_source(
        state.final_event, retrieval_bundle=state.retrieval_bundle
    )
    state.timeline = timeline
    emit_stage(
        stage_key="timeline_builder",
        title="时间线构建",
        status="completed",
        summary="时间线节点已生成。",
        details=_timeline_details(timeline.nodes, timeline.source, timeline.completeness, timeline.confidence),
    )
    state.record("build_timeline", "时间线构建完成")


def finalize_report(ctx: ToolContext, state: AgentState) -> None:
    from backend.app.services.analyze_pipeline import _report_details

    event = state.final_event
    claim_extraction = state.claim_extraction
    verdict = state.verdict
    timeline = state.timeline
    retrieval_bundle = state.retrieval_bundle
    request = state.request

    provenance = _build_provenance(
        request=request,
        event=event,
        retrieval_bundle=retrieval_bundle,
        claim_source=claim_extraction.source,
        evidence_source=verdict.evidence_source,
        timeline_source=timeline.source,
        provider_used=bool(state.provider_claims) or event.event_source == "provider_enriched",
        synthesis_fell_back=(
            state.synthesis_attempted
            and not state.agent_synthesized
            and claim_extraction.source == "rule"
        ),
    )
    retrieval_hits = retrieval_bundle.to_retrieval_hit_items() if retrieval_bundle is not None else []
    retrieval_diagnostics = retrieval_bundle.to_diagnostics() if retrieval_bundle is not None else None

    emit_stage(
        stage_key="report_build",
        title="生成报告",
        status="running",
        summary="正在组装最终报告、内容核查视图和 pipeline trace。",
        details=[],
    )
    report = ctx.report_builder.build(
        event=event,
        claim_results=verdict.claim_results,
        timeline=timeline.nodes,
        evidence=verdict.evidence,
        retrieval_hits=retrieval_hits,
        retrieval_diagnostics=retrieval_diagnostics,
        evidence_grade=verdict.evidence_grade,
        provenance=provenance,
        original_input=request.raw_input,
    )
    content_check = ctx.content_check_builder.build(
        report=report,
        original_input=request.raw_input,
    )
    pipeline_trace = ctx.pipeline_trace_builder.build(
        request=request,
        normalized_event=state.normalized_event,
        resolved_event=state.resolved_event,
        final_event=event,
        initial_retrieval_bundle=state.initial_retrieval_bundle,
        question_resolution=state.question_resolution,
        follow_up_bundle=state.follow_up_bundle,
        follow_up_used=state.follow_up_used,
        provider_claims=state.provider_claims,
        claim_extraction=claim_extraction,
        verdict=verdict,
        timeline=timeline,
        report=report,
    )
    final_report = report.model_copy(update={"content_check": content_check, "pipeline_trace": pipeline_trace})
    state.report = final_report
    emit_stage(
        stage_key="report_build",
        title="生成报告",
        status="completed",
        summary="最终报告已组装完成。",
        details=_report_details(final_report),
    )
    emit_log(
        stage_key="report_build",
        title="分析结束",
        summary="后端已返回最终 Report payload。",
        details=[
            f"mode={final_report.mode}",
            f"fallback_used={final_report.provenance.fallback_used}",
            f"retrieval_provider={final_report.provenance.retrieval_provider or 'unknown'}",
        ],
    )
    state.record("finalize_report", "报告组装完成")


# --- helpers reused from the legacy pipeline (kept behaviourally identical) ---


def _resolve_question(ctx: ToolContext, *, event, retrieval_bundle):
    try:
        agent_resolution = ctx.agent_reasoner.resolve_question(event=event, retrieval_bundle=retrieval_bundle)
    except Exception as exc:
        emit_log(
            stage_key="question_resolution",
            level="warning",
            title="Agent 消歧失败",
            summary="Agent question resolution 抛错，退回规则消歧。",
            details=[f"error_type={exc.__class__.__name__}"],
        )
        agent_resolution = None
    if agent_resolution is not None:
        return agent_resolution
    return ctx.question_resolver.resolve(event=event, retrieval_bundle=retrieval_bundle)


def _synthesize_with_agent(ctx: ToolContext, *, request, event, retrieval_bundle):
    try:
        return ctx.agent_reasoner.synthesize(
            request=request,
            event=event,
            retrieval_bundle=retrieval_bundle,
        )
    except Exception as exc:
        emit_log(
            stage_key="agent_synthesis",
            level="warning",
            title="Agent 综合失败",
            summary="Agent synthesis 抛错，退回规则链。",
            details=[f"error_type={exc.__class__.__name__}"],
        )
        return None


def _build_provenance(
    *,
    request,
    event,
    retrieval_bundle,
    claim_source,
    evidence_source,
    timeline_source,
    provider_used,
    synthesis_fell_back: bool = False,
):
    from backend.app.models.schemas import ReportProvenance

    fallback_reasons: list[str] = []
    for reason in [event.fallback_reason, retrieval_bundle.fallback_reason if retrieval_bundle else None]:
        if reason and reason not in fallback_reasons:
            fallback_reasons.append(reason)
    if synthesis_fell_back and LLM_SYNTHESIS_FALLBACK_REASON not in fallback_reasons:
        fallback_reasons.append(LLM_SYNTHESIS_FALLBACK_REASON)

    source_type = "backend_live"
    retrieval_provider = None
    retrieval_cache_status = None
    if retrieval_bundle is not None:
        retrieval_provider = retrieval_bundle.provider_name or None
        retrieval_cache_status = retrieval_bundle.cache_status or None
        if retrieval_bundle.provider_name == "mock" or evidence_source == "retrieval_mock":
            source_type = "backend_mock"

    return ReportProvenance(
        source_type=source_type,
        event_source=event.event_source,
        claim_source=claim_source,
        evidence_source=evidence_source,
        timeline_source=timeline_source,
        retrieval_provider=retrieval_provider,
        retrieval_cache_status=retrieval_cache_status,
        provider_used=provider_used,
        fallback_used=event.fallback_used or bool(retrieval_bundle and retrieval_bundle.fallback_used) or bool(fallback_reasons),
        fallback_reasons=fallback_reasons,
    )
