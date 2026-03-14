from __future__ import annotations

from backend.app.models.schemas import AnalyzeRequest, Report
from backend.app.services.claim_extractor import ClaimExtractor
from backend.app.services.input_normalizer import InputNormalizer
from backend.app.services.provider_enricher import ProviderEnricher
from backend.app.services.report_builder import ReportBuilder
from backend.app.services.retrieval_service import RetrievalService
from backend.app.services.timeline_builder import TimelineBuilder
from backend.app.services.verdict_engine import VerdictEngine


class AnalyzePipeline:
    def __init__(self) -> None:
        self.input_normalizer = InputNormalizer()
        self.provider_enricher = ProviderEnricher()
        self.retriever = RetrievalService()
        self.claim_extractor = ClaimExtractor()
        self.verdict_engine = VerdictEngine()
        self.timeline_builder = TimelineBuilder()
        self.report_builder = ReportBuilder()

    def analyze(self, request: AnalyzeRequest) -> Report:
        if request.request_context.get("force_error"):
            raise RuntimeError("forced_error_for_testing")

        event = self.input_normalizer.normalize(request)
        event, provider_claims = self.provider_enricher.enrich(event)
        retrieval_bundle = self.retriever.retrieve_for_event(event, request_context=request.request_context)
        claims = self.claim_extractor.extract(event, provider_claims=provider_claims)
        claim_results, evidence, evidence_grade = self.verdict_engine.evaluate(
            request=request,
            event=event,
            claims=claims,
            retrieval_bundle=retrieval_bundle,
        )
        timeline = self.timeline_builder.build(event, retrieval_bundle=retrieval_bundle)
        return self.report_builder.build(
            event=event,
            claim_results=claim_results,
            timeline=timeline,
            evidence=evidence,
            evidence_grade=evidence_grade,
        )

