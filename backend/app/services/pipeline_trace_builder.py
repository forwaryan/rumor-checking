from __future__ import annotations

from collections import Counter
from typing import Iterable, Optional

from backend.app.models.schemas import AnalyzeRequest, NormalizedEvent, PipelineTrace, PipelineTraceStep, Report
from backend.app.services.claim_extractor import ClaimExtraction
from backend.app.services.question_intent import is_broad_trend_question
from backend.app.services.question_resolver import QuestionResolution
from backend.app.services.retrieval_models import RetrievalBundle, SearchResult
from backend.app.services.timeline_builder import TimelineBuild
from backend.app.services.verdict_engine import VerdictEvaluation

INPUT_TYPE_LABELS = {
    "text_news": "文本新闻",
    "url_news": "新闻链接",
    "url_unknown": "未知链接",
    "question_only": "问句",
}
MODE_HINT_LABELS = {
    "complete": "complete",
    "partial": "partial",
    "safe": "safe",
}


def _preview(value: Optional[str], limit: int = 88) -> str:
    if not value:
        return "无"
    compact = " ".join(value.split())
    return compact if len(compact) <= limit else f"{compact[: limit - 3]}..."


def _result_line(result: SearchResult) -> str:
    return f"{result.published_at} | {result.source_name} | {result.title}"


def _iter_top_results(bundle: RetrievalBundle | None, limit: int = 3) -> Iterable[str]:
    if bundle is None:
        return []
    ordered = sorted(
        bundle.canonical_results,
        key=lambda item: (-item.tier_weight, item.published_at, item.result_id),
    )
    return [_result_line(item) for item in ordered[:limit]]


class PipelineTraceBuilder:
    def build(
        self,
        *,
        request: AnalyzeRequest,
        normalized_event: NormalizedEvent,
        resolved_event: NormalizedEvent,
        final_event: NormalizedEvent,
        initial_retrieval_bundle: RetrievalBundle | None,
        question_resolution: QuestionResolution,
        follow_up_bundle: RetrievalBundle | None,
        follow_up_used: bool,
        provider_claims,
        claim_extraction: ClaimExtraction,
        verdict: VerdictEvaluation,
        timeline: TimelineBuild,
        report: Report,
    ) -> PipelineTrace:
        steps = [
            self._build_input_step(request=request, normalized_event=normalized_event),
            self._build_normalization_step(event=normalized_event),
            self._build_retrieval_step(
                stage_key="initial_retrieval",
                title="初次检索",
                bundle=initial_retrieval_bundle,
                fallback_summary="当前没有发起外部检索。",
            ),
            self._build_question_resolution_step(
                normalized_event=normalized_event,
                resolved_event=resolved_event,
                question_resolution=question_resolution,
                initial_retrieval_bundle=initial_retrieval_bundle,
            ),
            self._build_follow_up_retrieval_step(
                normalized_event=normalized_event,
                follow_up_query=question_resolution.follow_up_query,
                follow_up_bundle=follow_up_bundle,
                follow_up_used=follow_up_used,
            ),
            self._build_provider_step(
                resolved_event=resolved_event,
                final_event=final_event,
                provider_claims=provider_claims,
            ),
            self._build_claim_step(claim_extraction=claim_extraction),
            self._build_verdict_step(verdict=verdict),
            self._build_timeline_step(timeline=timeline),
            self._build_report_step(report=report),
        ]
        return PipelineTrace(steps=steps)

    def _build_input_step(self, *, request: AnalyzeRequest, normalized_event: NormalizedEvent) -> PipelineTraceStep:
        details = [f"原始输入：{_preview(request.raw_input, limit=120)}"]
        if request.input_type:
            details.append(f"用户指定类型：{request.input_type}")
        if request.mock_fetch_result is not None:
            details.append(f"mock_fetch_result 状态：{request.mock_fetch_result.status}")
        if request.mock_evidence:
            details.append(f"mock_evidence：{len(request.mock_evidence)} 条")
        return PipelineTraceStep(
            stage_key="input_received",
            title="接收输入",
            status="completed",
            summary=f"收到{INPUT_TYPE_LABELS.get(normalized_event.input_type, normalized_event.input_type)}输入，长度 {len(request.raw_input.strip())} 字。",
            details=details,
        )

    def _build_normalization_step(self, *, event: NormalizedEvent) -> PipelineTraceStep:
        details = [f"摘要锚点：{_preview(event.summary)}"]
        if event.title:
            details.append(f"标题锚点：{_preview(event.title)}")
        if event.keywords:
            details.append(f"关键词：{' / '.join(event.keywords[:6])}")
        if event.source_name:
            details.append(f"来源名：{event.source_name}")
        if event.fallback_reason:
            details.append(f"回退原因：{event.fallback_reason}")
        return PipelineTraceStep(
            stage_key="normalize_input",
            title="输入归一化",
            status="warning" if event.fallback_used else "completed",
            summary=(
                f"输入被归一化为 {event.input_type}，模式提示 {MODE_HINT_LABELS.get(event.mode_hint, event.mode_hint)}，"
                f"事件来源标记为 {event.event_source}。"
            ),
            details=details,
        )

    def _build_retrieval_step(
        self,
        *,
        stage_key: str,
        title: str,
        bundle: RetrievalBundle | None,
        fallback_summary: str,
    ) -> PipelineTraceStep:
        if bundle is None:
            return PipelineTraceStep(
                stage_key=stage_key,
                title=title,
                status="skipped",
                summary=fallback_summary,
                details=[],
            )

        details = [
            f"query：{_preview(bundle.query, limit=96)}",
            f"provider：{bundle.provider_name}",
            f"cache：{bundle.cache_status}",
        ]
        if bundle.retrieved_at:
            details.append(f"retrieved_at：{bundle.retrieved_at}")
        if bundle.matched_case_id:
            details.append(f"matched_case_id：{bundle.matched_case_id}")
        if bundle.fallback_reason:
            details.append(f"检索回退原因：{bundle.fallback_reason}")
        if bundle.failure_detail:
            details.append(f"failure_detail：{bundle.failure_detail}")
        for line in _iter_top_results(bundle):
            details.append(f"命中结果：{_preview(line, limit=128)}")

        status = "completed"
        if bundle.failure_detail or bundle.fallback_used or not bundle.canonical_results:
            status = "warning"

        return PipelineTraceStep(
            stage_key=stage_key,
            title=title,
            status=status,
            summary=(
                f"检索 query 已生成；raw 命中 {len(bundle.raw_results)} 条，"
                f"去重后 canonical 命中 {len(bundle.canonical_results)} 条。"
            ),
            details=details,
        )

    def _build_question_resolution_step(
        self,
        *,
        normalized_event: NormalizedEvent,
        resolved_event: NormalizedEvent,
        question_resolution: QuestionResolution,
        initial_retrieval_bundle: RetrievalBundle | None,
    ) -> PipelineTraceStep:
        if normalized_event.input_type != "question_only":
            return PipelineTraceStep(
                stage_key="question_resolution",
                title="问句收束",
                status="skipped",
                summary="当前输入不是纯问句，跳过问句收束。",
                details=[],
            )

        if is_broad_trend_question(normalized_event.raw_input):
            details = [
                "系统识别到这是范围型问句，适合保留多条检索命中做整体判断，而不是强行锁到单一事件。",
            ]
            if initial_retrieval_bundle and initial_retrieval_bundle.canonical_results:
                details.append(f"当前保留 {len(initial_retrieval_bundle.canonical_results)} 条候选结果参与后续判定。")
            return PipelineTraceStep(
                stage_key="question_resolution",
                title="问句收束",
                status="completed",
                summary="识别为范围型问句，后续不会把它误收束成单一事件，而是按多条公开结果综合判断。",
                details=details,
            )

        if question_resolution.selected_result is None:
            details = []
            if initial_retrieval_bundle and initial_retrieval_bundle.canonical_results:
                details.append("虽然检索到了候选结果，但问句与候选事件的重合度或可信锚点不足，未锁定具体事件。")
            else:
                details.append("初次检索没有提供足够候选结果，无法把模糊问句收束到具体事件。")
            return PipelineTraceStep(
                stage_key="question_resolution",
                title="问句收束",
                status="warning",
                summary="未能稳定锁定具体事件，后续链路只能继续沿着模糊问句保守推进。",
                details=details,
            )

        selected = question_resolution.selected_result
        details = [
            f"锁定候选：{_preview(selected.title, limit=110)}",
            f"候选来源：{selected.source_name} @ {selected.published_at}",
            f"收束后摘要：{_preview(resolved_event.summary, limit=120)}",
        ]
        if question_resolution.follow_up_query:
            details.append(f"二次检索 query：{_preview(question_resolution.follow_up_query, limit=120)}")
        return PipelineTraceStep(
            stage_key="question_resolution",
            title="问句收束",
            status="completed",
            summary="从初次检索结果中锁定到更具体的候选事件，并生成了后续继续核查的锚点。",
            details=details,
        )

    def _build_follow_up_retrieval_step(
        self,
        *,
        normalized_event: NormalizedEvent,
        follow_up_query: Optional[str],
        follow_up_bundle: RetrievalBundle | None,
        follow_up_used: bool,
    ) -> PipelineTraceStep:
        if normalized_event.input_type != "question_only":
            return PipelineTraceStep(
                stage_key="follow_up_retrieval",
                title="二次检索",
                status="skipped",
                summary="当前输入不是纯问句，未触发二次检索。",
                details=[],
            )

        if not follow_up_query:
            return PipelineTraceStep(
                stage_key="follow_up_retrieval",
                title="二次检索",
                status="skipped",
                summary="问句没有被收束到具体事件，因此未触发二次检索。",
                details=[],
            )

        if follow_up_bundle is None:
            return PipelineTraceStep(
                stage_key="follow_up_retrieval",
                title="二次检索",
                status="warning",
                summary="已经生成二次检索 query，但没有拿到对应检索结果。",
                details=[f"query：{_preview(follow_up_query, limit=120)}"],
            )

        details = [
            f"query：{_preview(follow_up_query, limit=120)}",
            f"provider：{follow_up_bundle.provider_name}",
            f"cache：{follow_up_bundle.cache_status}",
        ]
        for line in _iter_top_results(follow_up_bundle):
            details.append(f"命中结果：{_preview(line, limit=128)}")
        if follow_up_bundle.fallback_reason:
            details.append(f"检索回退原因：{follow_up_bundle.fallback_reason}")
        details.append("二次检索结果已被采用。" if follow_up_used else "二次检索结果未优于初次检索，因此未被采用。")

        status = "completed" if follow_up_used and follow_up_bundle.canonical_results else "warning"
        return PipelineTraceStep(
            stage_key="follow_up_retrieval",
            title="二次检索",
            status=status,
            summary=(
                f"围绕收束后的候选事件再次检索；raw 命中 {len(follow_up_bundle.raw_results)} 条，"
                f"canonical 命中 {len(follow_up_bundle.canonical_results)} 条。"
            ),
            details=details,
        )

    def _build_provider_step(
        self,
        *,
        resolved_event: NormalizedEvent,
        final_event: NormalizedEvent,
        provider_claims,
    ) -> PipelineTraceStep:
        details = []
        if resolved_event.title != final_event.title:
            details.append(f"标题更新：{_preview(resolved_event.title)} -> {_preview(final_event.title)}")
        if resolved_event.summary != final_event.summary:
            details.append(f"摘要更新：{_preview(final_event.summary, limit=120)}")
        if resolved_event.keywords != final_event.keywords and final_event.keywords:
            details.append(f"关键词更新：{' / '.join(final_event.keywords[:6])}")
        if provider_claims:
            details.append(f"Provider 额外给出 {len(provider_claims)} 条结构化 claim。")
        if not details:
            details.append("Provider 没有提供比当前事件锚点更具体的结构化结果。")

        provider_used = bool(provider_claims) or final_event.event_source == "provider_enriched"
        return PipelineTraceStep(
            stage_key="provider_enrichment",
            title="Provider 增强",
            status="completed" if provider_used else "skipped",
            summary="Provider 返回了结构化补充。" if provider_used else "Provider 未补出额外结构化信息。",
            details=details,
        )

    def _build_claim_step(self, *, claim_extraction: ClaimExtraction) -> PipelineTraceStep:
        details = [f"claim 来源：{claim_extraction.source}"]
        for item in claim_extraction.claims[:4]:
            details.append(f"{item.claim_type}：{_preview(item.claim, limit=120)}")
        return PipelineTraceStep(
            stage_key="claim_extraction",
            title="Claim 抽取",
            status="completed" if claim_extraction.claims else "warning",
            summary=f"当前事件共抽取出 {len(claim_extraction.claims)} 条 claim。",
            details=details,
        )

    def _build_verdict_step(self, *, verdict: VerdictEvaluation) -> PipelineTraceStep:
        verdict_counter = Counter(item.verdict for item in verdict.claim_results)
        details = [
            f"证据来源：{verdict.evidence_source}",
            f"证据等级：{verdict.evidence_grade}",
            f"证据池：{len(verdict.evidence)} 条",
        ]
        for item in verdict.claim_results[:3]:
            details.append(f"{item.verdict}：{_preview(item.claim, limit=100)}")

        decisive_count = verdict_counter["supported"] + verdict_counter["refuted"] + verdict_counter["conflicting"]
        return PipelineTraceStep(
            stage_key="verdict_evaluation",
            title="逐条判定",
            status="completed" if decisive_count else "warning",
            summary=(
                f"支持 {verdict_counter['supported']} 条，反驳 {verdict_counter['refuted']} 条，"
                f"冲突 {verdict_counter['conflicting']} 条，证据不足 {verdict_counter['insufficient']} 条。"
            ),
            details=details,
        )

    def _build_timeline_step(self, *, timeline: TimelineBuild) -> PipelineTraceStep:
        if not timeline.nodes:
            return PipelineTraceStep(
                stage_key="timeline_building",
                title="时间线还原",
                status="warning",
                summary="当前没有足够外部锚点，未能还原出稳定时间线。",
                details=[f"timeline_source：{timeline.source}"],
            )

        details = [f"timeline_source：{timeline.source}"]
        for node in timeline.nodes[:4]:
            details.append(f"{node.node_type}：{node.published_at} | {_preview(node.title, limit=110)}")

        status = "completed" if timeline.source == "retrieval" else "warning"
        summary = (
            f"已还原出 {len(timeline.nodes)} 个时间线节点。"
            if timeline.source == "retrieval"
            else f"仅保留 {len(timeline.nodes)} 个输入种子节点，传播链仍不完整。"
        )
        return PipelineTraceStep(
            stage_key="timeline_building",
            title="时间线还原",
            status=status,
            summary=summary,
            details=details,
        )

    def _build_report_step(self, *, report: Report) -> PipelineTraceStep:
        details = [
            f"最终模式：{report.mode}",
            f"结果来源：{report.provenance.source_type}",
            (
                f"claims={report.provenance.claim_source} / "
                f"evidence={report.provenance.evidence_source} / "
                f"timeline={report.provenance.timeline_source}"
            ),
            f"总结：{_preview(report.final_summary, limit=140)}",
        ]
        if report.risks:
            details.append(f"首条风险：{_preview(report.risks[0], limit=140)}")
        return PipelineTraceStep(
            stage_key="report_output",
            title="报告输出",
            status="warning" if report.mode == "safe_mode" else "completed",
            summary="所有阶段已汇总到最终报告，页面其余模块都基于这里的结果渲染。",
            details=details,
        )
