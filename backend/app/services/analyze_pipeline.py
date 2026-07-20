from __future__ import annotations

from backend.app.core.config import get_settings
from backend.app.models.schemas import AnalyzeRequest, Report, ReportProvenance, RetrievalDiagnostics
from backend.app.services.agent_reasoner import KimiAgentReasoner
from backend.app.services.claim_extractor import ClaimExtractor
from backend.app.services.content_check_builder import ContentCheckBuilder
from backend.app.services.input_normalizer import InputNormalizer
from backend.app.services.pipeline_trace_builder import PipelineTraceBuilder
from backend.app.services.progress import emit_log, emit_stage
from backend.app.services.provider_enricher import ProviderEnricher
from backend.app.services.question_resolver import QuestionResolver
from backend.app.services.report_builder import ReportBuilder
from backend.app.services.retrieval_service import RetrievalService
from backend.app.services.timeline_builder import TimelineBuilder
from backend.app.services.url_fetch_cache import UrlFetchCache
from backend.app.services.verdict_engine import VerdictEngine


class AnalyzePipeline:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.input_normalizer = InputNormalizer()
        self.url_fetch_cache = UrlFetchCache(
            cache_root=self.settings.url_fetch_cache_dir,
            ttl_seconds=self.settings.url_fetch_cache_ttl_seconds,
        )
        self.agent_reasoner = KimiAgentReasoner()
        self.provider_enricher = ProviderEnricher()
        self.retriever = RetrievalService(agent_reasoner=self.agent_reasoner)
        self.question_resolver = QuestionResolver()
        self.claim_extractor = ClaimExtractor()
        self.verdict_engine = VerdictEngine()
        self.timeline_builder = TimelineBuilder()
        self.report_builder = ReportBuilder()
        self.content_check_builder = ContentCheckBuilder()
        self.pipeline_trace_builder = PipelineTraceBuilder()

    def analyze(self, request: AnalyzeRequest) -> Report:
        if request.request_context.get("force_error"):
            raise RuntimeError("forced_error_for_testing")

        if self.settings.agent_orchestrator_enabled:
            report = self._run_agent_orchestrator(request)
            if report is not None:
                return report

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
        normalized_event = self.input_normalizer.normalize(request)
        emit_stage(
            stage_key="normalize_input",
            title="标准化输入",
            status="completed",
            summary="已整理出初始事件草稿。",
            details=_event_details(normalized_event),
        )

        emit_stage(
            stage_key="retrieval_initial",
            title="首轮检索",
            status="running",
            summary="正在生成 query plan 并拉取第一批公开网页结果。",
            details=[f"provider={self.settings.retrieval_provider}"],
        )
        initial_retrieval_bundle = self.retriever.retrieve_for_event(normalized_event, request_context=request.request_context)
        retrieval_bundle = initial_retrieval_bundle
        emit_stage(
            stage_key="retrieval_initial",
            title="首轮检索",
            status="completed",
            summary="首轮检索已返回结果集。",
            details=_retrieval_bundle_details(initial_retrieval_bundle),
        )

        emit_stage(
            stage_key="question_resolution",
            title="问题消歧",
            status="running",
            summary="正在判断这次输入是否能稳定锚定到单一事件。",
            details=[f"question_only={normalized_event.input_type == 'question_only'}"],
        )
        question_resolution = self._resolve_question(event=normalized_event, retrieval_bundle=initial_retrieval_bundle)
        resolved_event = question_resolution.event
        resolution_status = "skipped" if normalized_event.input_type != "question_only" else "completed"
        resolution_summary = "输入不是纯问题，沿用当前事件草稿。" if resolution_status == "skipped" else "问题消歧已完成。"
        emit_stage(
            stage_key="question_resolution",
            title="问题消歧",
            status=resolution_status,
            summary=resolution_summary,
            details=_question_resolution_details(question_resolution),
        )

        follow_up_bundle = None
        follow_up_used = False
        if question_resolution.follow_up_query:
            emit_stage(
                stage_key="retrieval_follow_up",
                title="追加检索",
                status="running",
                summary="已根据候选事件生成 follow-up query，正在补抓更精准的结果。",
                details=[f"follow_up_query={question_resolution.follow_up_query}"],
            )
            follow_up_context = dict(request.request_context)
            follow_up_context["force_retrieval_query"] = question_resolution.follow_up_query
            follow_up_bundle = self.retriever.retrieve_for_event(resolved_event, request_context=follow_up_context)
            if follow_up_bundle.canonical_results or follow_up_bundle.matched_case_id:
                retrieval_bundle = follow_up_bundle
                follow_up_used = True
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

        retrieval_bundle = self._run_investigation(
            request=request,
            event=resolved_event,
            retrieval_bundle=retrieval_bundle,
        )

        emit_stage(
            stage_key="agent_synthesis",
            title="Agent 综合判断",
            status="running",
            summary="正在让 Kimi 基于检索结果生成事件、claims、verdict 和 timeline。",
            details=[f"enabled={self.agent_reasoner.enabled}"],
        )
        agent_synthesis = self._synthesize_with_agent(
            request=request,
            event=resolved_event,
            retrieval_bundle=retrieval_bundle,
        )
        if agent_synthesis is not None:
            event = agent_synthesis.event
            provider_claims = agent_synthesis.claim_extraction.claims
            claim_extraction = agent_synthesis.claim_extraction
            verdict = agent_synthesis.verdict
            timeline = agent_synthesis.timeline
            emit_stage(
                stage_key="agent_synthesis",
                title="Agent 综合判断",
                status="completed",
                summary="Agent 路径已产出结构化结论。",
                details=[
                    f"event_title={event.title or 'unknown'}",
                    f"claims={len(claim_extraction.claims)}",
                    f"timeline_nodes={len(timeline.nodes)}",
                    f"evidence_grade={verdict.evidence_grade}",
                ],
            )
        else:
            emit_stage(
                stage_key="agent_synthesis",
                title="Agent 综合判断",
                status="warning",
                summary="Agent 没有稳定产出，退回规则兜底链路。",
                details=[f"retrieval_hits={len(retrieval_bundle.canonical_results) if retrieval_bundle else 0}"],
            )
            emit_stage(
                stage_key="provider_enrichment",
                title="结构化补全",
                status="running",
                summary="正在调用 provider 对事件和 claims 做结构化补全。",
                details=[],
            )
            try:
                event, provider_claims = self.provider_enricher.enrich(resolved_event)
                provider_status = "completed"
                provider_summary = "Provider enrichment 已返回结构化事件草稿。"
                provider_details = _event_details(event)
            except Exception as exc:
                event, provider_claims = resolved_event, None
                provider_status = "warning"
                provider_summary = "Provider enrichment 失败，继续使用当前事件草稿。"
                provider_details = [f"error_type={exc.__class__.__name__}"]
            emit_stage(
                stage_key="provider_enrichment",
                title="结构化补全",
                status=provider_status,
                summary=provider_summary,
                details=provider_details,
            )

            emit_stage(
                stage_key="claim_extraction",
                title="Claim 拆解",
                status="running",
                summary="正在把事件表述拆成可核查的 atomic claims。",
                details=[],
            )
            claim_extraction = self.claim_extractor.extract_with_source(event, provider_claims=provider_claims)
            emit_stage(
                stage_key="claim_extraction",
                title="Claim 拆解",
                status="completed",
                summary="Claim 拆解完成。",
                details=_claim_details(claim_extraction.claims),
            )

            emit_stage(
                stage_key="verdict_engine",
                title="Claim 判定",
                status="running",
                summary="正在结合 retrieval hits 为每条 claim 打 verdict。",
                details=[],
            )
            verdict = self.verdict_engine.evaluate_with_source(
                request=request,
                event=event,
                claims=claim_extraction.claims,
                retrieval_bundle=retrieval_bundle,
            )
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

            emit_stage(
                stage_key="timeline_builder",
                title="时间线构建",
                status="running",
                summary="正在从检索结果里挑选传播与澄清节点。",
                details=[],
            )
            timeline = self.timeline_builder.build_with_source(event, retrieval_bundle=retrieval_bundle)
            emit_stage(
                stage_key="timeline_builder",
                title="时间线构建",
                status="completed",
                summary="时间线节点已生成。",
                details=_timeline_details(timeline.nodes, timeline.source, timeline.completeness, timeline.confidence),
            )

        provenance = self._build_provenance(
            request=request,
            event=event,
            retrieval_bundle=retrieval_bundle,
            claim_source=claim_extraction.source,
            evidence_source=verdict.evidence_source,
            timeline_source=timeline.source,
            provider_used=bool(provider_claims) or event.event_source == "provider_enriched",
        )
        retrieval_hits = retrieval_bundle.to_retrieval_hit_items() if retrieval_bundle is not None else []
        retrieval_diagnostics = self._build_retrieval_diagnostics(retrieval_bundle)

        emit_stage(
            stage_key="report_build",
            title="生成报告",
            status="running",
            summary="正在组装最终报告、内容核查视图和 pipeline trace。",
            details=[],
        )
        report = self.report_builder.build(
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
        content_check = self.content_check_builder.build(
            report=report,
            original_input=request.raw_input,
        )
        pipeline_trace = self.pipeline_trace_builder.build(
            request=request,
            normalized_event=normalized_event,
            resolved_event=resolved_event,
            final_event=event,
            initial_retrieval_bundle=initial_retrieval_bundle,
            question_resolution=question_resolution,
            follow_up_bundle=follow_up_bundle,
            follow_up_used=follow_up_used,
            provider_claims=provider_claims,
            claim_extraction=claim_extraction,
            verdict=verdict,
            timeline=timeline,
            report=report,
        )
        final_report = report.model_copy(update={"content_check": content_check, "pipeline_trace": pipeline_trace})
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
        return final_report

    def _resolve_question(self, *, event, retrieval_bundle):
        try:
            agent_resolution = self.agent_reasoner.resolve_question(event=event, retrieval_bundle=retrieval_bundle)
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
        return self.question_resolver.resolve(event=event, retrieval_bundle=retrieval_bundle)

    def _synthesize_with_agent(self, *, request, event, retrieval_bundle):
        try:
            return self.agent_reasoner.synthesize(
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

    def _run_agent_orchestrator(self, request: AnalyzeRequest):
        from backend.app.agent.planner import LlmPlanner, RulePlanner
        from backend.app.agent.runner import AgentRunner
        from backend.app.agent_tools.base import ToolContext

        ctx = ToolContext(
            settings=self.settings,
            input_normalizer=self.input_normalizer,
            retriever=self.retriever,
            url_content_extractor=self.input_normalizer.url_content_extractor,
            url_fetch_cache=self.url_fetch_cache,
            question_resolver=self.question_resolver,
            agent_reasoner=self.agent_reasoner,
            provider_enricher=self.provider_enricher,
            claim_extractor=self.claim_extractor,
            verdict_engine=self.verdict_engine,
            timeline_builder=self.timeline_builder,
            report_builder=self.report_builder,
            content_check_builder=self.content_check_builder,
            pipeline_trace_builder=self.pipeline_trace_builder,
        )
        use_llm_planner = self.settings.kimi_enabled and self.agent_reasoner.enabled
        planner = LlmPlanner(self.agent_reasoner) if use_llm_planner else RulePlanner()
        emit_log(
            stage_key="agent_orchestrator",
            title="Agent 编排启动",
            summary="Agent orchestrator 接管本次分析。",
            details=[f"planner={'llm' if use_llm_planner else 'rule'}"],
        )
        try:
            return AgentRunner(ctx, planner=planner).run(request)
        except Exception as exc:
            emit_log(
                stage_key="agent_orchestrator",
                level="warning",
                title="Agent 编排失败",
                summary="Agent orchestrator 抛错，退回固定 pipeline。",
                details=[f"error_type={exc.__class__.__name__}"],
            )
            return None

    def _run_investigation(self, *, request, event, retrieval_bundle):
        if not self.settings.lightweight_agent_ready or not self.agent_reasoner.enabled:
            return retrieval_bundle
        if retrieval_bundle is None:
            return retrieval_bundle

        max_rounds = self.settings.agent_max_extra_rounds
        current_bundle = retrieval_bundle
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
                plan = self.agent_reasoner.plan_investigation(
                    event=event,
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

            follow_up_context = dict(request.request_context)
            follow_up_context["force_retrieval_query"] = plan.follow_up_query
            emit_stage(
                stage_key="investigation_retrieval",
                title="调查补检索",
                status="running",
                summary="正在按调查决策补抓更权威的结果。",
                details=[f"follow_up_query={plan.follow_up_query}"],
            )
            candidate_bundle = self.retriever.retrieve_for_event(event, request_context=follow_up_context)
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
            if adopted:
                current_bundle = candidate_bundle
        return current_bundle

    def _build_retrieval_diagnostics(self, retrieval_bundle) -> RetrievalDiagnostics | None:
        if retrieval_bundle is None:
            return None
        return retrieval_bundle.to_diagnostics()

    def _build_provenance(
        self,
        *,
        request: AnalyzeRequest,
        event,
        retrieval_bundle,
        claim_source: str,
        evidence_source: str,
        timeline_source: str,
        provider_used: bool,
    ) -> ReportProvenance:
        fallback_reasons: list[str] = []
        for reason in [event.fallback_reason, retrieval_bundle.fallback_reason if retrieval_bundle else None]:
            if reason and reason not in fallback_reasons:
                fallback_reasons.append(reason)

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


_GRADE_RANK = {"A": 3, "B": 2, "C": 1, "D": 0}


def _bundle_quality(bundle) -> tuple[int, int, int]:
    if bundle is None:
        return (-1, -1, -1)
    return (
        _GRADE_RANK.get(bundle.evidence_grade, 0),
        bundle.independent_high_trust_source_count,
        len(bundle.canonical_results),
    )


def _event_details(event) -> list[str]:
    return [
        f"title={event.title or 'unknown'}",
        f"source_name={event.source_name or 'unknown'}",
        f"published_at={event.published_at or 'unknown'}",
        f"event_source={event.event_source}",
    ]


def _retrieval_bundle_details(bundle) -> list[str]:
    if bundle is None:
        return ["bundle=none"]
    details = [
        f"provider={bundle.provider_name}",
        f"query={bundle.query}",
        f"cache_status={bundle.cache_status}",
        f"canonical_results={len(bundle.canonical_results)}",
        f"raw_results={len(bundle.raw_results)}",
        f"evidence_grade={bundle.evidence_grade}",
    ]
    for result in bundle.canonical_results[:3]:
        details.append(f"hit={result.title} | {result.source_name} | {result.published_at}")
    if bundle.failure_detail:
        details.append(f"failure_detail={bundle.failure_detail}")
    return details


def _question_resolution_details(question_resolution) -> list[str]:
    details = [
        f"resolved_title={question_resolution.event.title or 'unknown'}",
        f"follow_up_query={question_resolution.follow_up_query or 'none'}",
    ]
    if question_resolution.selected_result is not None:
        details.append(f"selected_result={question_resolution.selected_result.title}")
    else:
        details.append("selected_result=none")
    return details


def _claim_details(claims) -> list[str]:
    details = [f"claims={len(claims)}"]
    for claim in claims[:4]:
        details.append(f"claim={claim.claim}")
    return details


def _timeline_details(nodes, source: str, completeness: int, confidence: int) -> list[str]:
    details = [
        f"source={source}",
        f"nodes={len(nodes)}",
        f"completeness={completeness}",
        f"confidence={confidence}",
    ]
    for node in nodes[:4]:
        details.append(f"node={node.node_type}:{node.title}")
    return details


def _report_details(report: Report) -> list[str]:
    details = [
        f"mode={report.mode}",
        f"claim_results={len(report.claim_results)}",
        f"timeline_nodes={len(report.timeline)}",
        f"sources={len(report.sources)}",
        f"retrieval_hits={len(report.retrieval_hits or [])}",
        f"fallback_used={report.provenance.fallback_used}",
    ]
    if report.overall_credibility_score is not None:
        details.append(f"overall_credibility_score={report.overall_credibility_score}")
    if report.overall_credibility_label:
        details.append(f"overall_credibility_label={report.overall_credibility_label}")
    return details
