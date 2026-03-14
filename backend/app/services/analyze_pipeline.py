from __future__ import annotations

from backend.app.models.schemas import AnalyzeRequest, Report, ReportProvenance, RetrievalDiagnostics
from backend.app.services.claim_extractor import ClaimExtractor
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
        self.input_normalizer = InputNormalizer()
        self.provider_enricher = ProviderEnricher()
        self.retriever = RetrievalService()
        self.question_resolver = QuestionResolver()
        self.claim_extractor = ClaimExtractor()
        self.verdict_engine = VerdictEngine()
        self.timeline_builder = TimelineBuilder()
        self.report_builder = ReportBuilder()
        self.pipeline_trace_builder = PipelineTraceBuilder()

    def analyze(self, request: AnalyzeRequest) -> Report:
        if request.request_context.get("force_error"):
            raise RuntimeError("forced_error_for_testing")

        normalized_event = self.input_normalizer.normalize(request)
        initial_retrieval_bundle = self.retriever.retrieve_for_event(normalized_event, request_context=request.request_context)
        retrieval_bundle = initial_retrieval_bundle
        question_resolution = self.question_resolver.resolve(event=normalized_event, retrieval_bundle=initial_retrieval_bundle)
        resolved_event = question_resolution.event
        event, provider_claims = self.provider_enricher.enrich(resolved_event)
        follow_up_bundle = None
        follow_up_used = False
        if question_resolution.follow_up_query:
            follow_up_context = dict(request.request_context)
            follow_up_context["force_retrieval_query"] = question_resolution.follow_up_query
            follow_up_bundle = self.retriever.retrieve_for_event(event, request_context=follow_up_context)
            if follow_up_bundle.canonical_results or follow_up_bundle.matched_case_id or follow_up_bundle.fallback_used:
                retrieval_bundle = follow_up_bundle
                follow_up_used = True
        claim_extraction = self.claim_extractor.extract_with_source(event, provider_claims=provider_claims)
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
        return report.model_copy(update={"pipeline_trace": pipeline_trace})

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
        if request.request_context.get("report_origin") == "backend_replay":
            source_type = "backend_replay"
        elif request.mock_evidence or request.mock_fetch_result or (retrieval_bundle and retrieval_bundle.provider_name == "mock"):
            source_type = "backend_mock"

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
