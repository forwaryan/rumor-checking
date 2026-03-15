from __future__ import annotations

from fastapi import status

from backend.app.core.config import get_settings
from backend.app.core.exceptions import AppError
from backend.app.models.schemas import AnalyzeRequest, Report, ReportProvenance, RetrievalDiagnostics
from backend.app.services.claim_extractor import ClaimExtractor
from backend.app.services.content_check_builder import ContentCheckBuilder
from backend.app.services.input_normalizer import InputNormalizer
from backend.app.services.pipeline_trace_builder import PipelineTraceBuilder
from backend.app.services.provider_enricher import ProviderEnricher
from backend.app.services.question_resolver import QuestionResolver
from backend.app.services.report_builder import ReportBuilder
from backend.app.services.retrieval_service import RetrievalService
from backend.app.services.timeline_builder import TimelineBuilder
from backend.app.services.verdict_engine import VerdictEngine


class AnalyzePipeline:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.input_normalizer = InputNormalizer()
        self.provider_enricher = ProviderEnricher()
        self.retriever = RetrievalService()
        self.question_resolver = QuestionResolver()
        self.claim_extractor = ClaimExtractor()
        self.verdict_engine = VerdictEngine()
        self.timeline_builder = TimelineBuilder()
        self.report_builder = ReportBuilder()
        self.content_check_builder = ContentCheckBuilder()
        self.pipeline_trace_builder = PipelineTraceBuilder()

    def analyze(self, request: AnalyzeRequest) -> Report:
        self._ensure_kimi_only_ready()
        if request.request_context.get("force_error"):
            raise RuntimeError("forced_error_for_testing")

        normalized_event = self.input_normalizer.normalize(request)
        initial_retrieval_bundle = self.retriever.retrieve_for_event(normalized_event, request_context=request.request_context)
        retrieval_bundle = initial_retrieval_bundle
        question_resolution = self.question_resolver.resolve(event=normalized_event, retrieval_bundle=initial_retrieval_bundle)
        resolved_event = question_resolution.event
        try:
            event, provider_claims = self.provider_enricher.enrich(resolved_event)
        except Exception as exc:
            raise AppError(
                status_code=status.HTTP_502_BAD_GATEWAY,
                code="kimi_analysis_failed",
                message="Kimi structured analysis failed. The request was not downgraded to any rule-only path.",
                details={"error_type": exc.__class__.__name__},
            ) from exc
        follow_up_bundle = None
        follow_up_used = False
        if question_resolution.follow_up_query:
            follow_up_context = dict(request.request_context)
            follow_up_context["force_retrieval_query"] = question_resolution.follow_up_query
            follow_up_bundle = self.retriever.retrieve_for_event(event, request_context=follow_up_context)
            if follow_up_bundle.canonical_results or follow_up_bundle.matched_case_id:
                retrieval_bundle = follow_up_bundle
                follow_up_used = True
        try:
            claim_extraction = self.claim_extractor.extract_with_source(event, provider_claims=provider_claims)
        except Exception as exc:
            raise AppError(
                status_code=status.HTTP_502_BAD_GATEWAY,
                code="kimi_claims_missing",
                message="Kimi did not return usable claims, so the request was rejected instead of falling back to heuristics.",
                details={"error_type": exc.__class__.__name__},
            ) from exc
        verdict = self.verdict_engine.evaluate_with_source(
            request=request,
            event=event,
            claims=claim_extraction.claims,
            retrieval_bundle=retrieval_bundle,
        )
        timeline = self.timeline_builder.build_with_source(event, retrieval_bundle=retrieval_bundle)
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
        return report.model_copy(update={"content_check": content_check, "pipeline_trace": pipeline_trace})

    def _ensure_kimi_only_ready(self) -> None:
        if self.settings.kimi_ready:
            return
        raise AppError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="kimi_not_configured",
            message="Kimi-only mode is enabled, but Kimi is not configured.",
        )

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
