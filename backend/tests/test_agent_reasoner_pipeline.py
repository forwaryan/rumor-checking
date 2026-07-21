from __future__ import annotations

from dataclasses import replace

from backend.app.core.config import get_settings
from backend.app.models.schemas import AnalyzeRequest, ClaimItem, ClaimResult, TimelineNode
from backend.app.services.agent_reasoner import AgentSynthesis, LlmAgentReasoner
from backend.app.services.analyze_pipeline import AnalyzePipeline
from backend.app.services.claim_extractor import ClaimExtraction
from backend.app.services.question_resolver import QuestionResolution
from backend.app.services.retrieval_cache import RetrievalCache
from backend.app.services.retrieval_models import SearchResult
from backend.app.services.retrieval_service import RetrievalService
from backend.app.services.timeline_builder import TimelineBuild
from backend.app.services.verdict_engine import VerdictEvaluation


class FakeLlmProvider:
    name = "kimi"
    enabled = True

    def __init__(self, results):
        self._results = list(results)

    def search(self, query_text: str):
        return list(self._results)


class FakeAgentReasoner:
    enabled = True

    def resolve_question(self, *, event, retrieval_bundle):
        selected = retrieval_bundle.canonical_results[0]
        resolved_event = event.model_copy(
            update={
                "title": selected.title,
                "summary": selected.snippet,
                "source_name": selected.source_name,
                "source_url": selected.url,
                "published_at": selected.published_at,
                "event_source": "retrieval_resolved",
            }
        )
        return QuestionResolution(
            event=resolved_event,
            follow_up_query=None,
            selected_result=selected,
        )

    def synthesize(self, *, request, event, retrieval_bundle):
        primary = retrieval_bundle.canonical_results[0]
        secondary = retrieval_bundle.canonical_results[1]
        claim_results = [
            ClaimResult(
                claim="当事人发生脑出血并仍在救治。",
                claim_type="fact",
                verdict="supported",
                confidence="high",
                evidence=[primary.to_evidence(relevance_reason="Agent matched this hit as supporting evidence for the claim.")],
                notes="Agent found grounded support in the supplied retrieval hits.",
            ),
            ClaimResult(
                claim="当事人已经死亡。",
                claim_type="fact",
                verdict="refuted",
                confidence="high",
                evidence=[
                    primary.to_evidence(relevance_reason="Agent matched this hit as refuting evidence for the claim."),
                    secondary.to_evidence(relevance_reason="Agent matched this hit as refuting evidence for the claim."),
                ],
                notes="Agent found grounded refutation in the supplied retrieval hits.",
            ),
        ]
        return AgentSynthesis(
            event=event.model_copy(
                update={
                    "title": "女主播脑出血传闻与平台辟谣",
                    "summary": "医院回应称当事人仍在救治，平台同步辟谣死亡说法。",
                    "source_name": primary.source_name,
                    "source_url": primary.url,
                    "published_at": primary.published_at,
                    "event_source": "retrieval_resolved",
                }
            ),
            claim_extraction=ClaimExtraction(
                claims=[
                    ClaimItem(claim="当事人发生脑出血并仍在救治。", claim_type="fact"),
                    ClaimItem(claim="当事人已经死亡。", claim_type="fact"),
                ],
                source="provider",
                query_hints={},
            ),
            verdict=VerdictEvaluation(
                claim_results=claim_results,
                evidence=retrieval_bundle.to_evidence_items(),
                evidence_grade=retrieval_bundle.evidence_grade,
                evidence_source="retrieval_live",
            ),
            timeline=TimelineBuild(
                nodes=[
                    TimelineNode(
                        node_type="origin",
                        title=primary.title,
                        url=primary.url,
                        source_name=primary.source_name,
                        published_at=primary.published_at,
                        summary=primary.snippet,
                        why_selected="Agent selected this hit as the origin anchor.",
                    ),
                    TimelineNode(
                        node_type="turn",
                        title=secondary.title,
                        url=secondary.url,
                        source_name=secondary.source_name,
                        published_at=secondary.published_at,
                        summary=secondary.snippet,
                        why_selected="Agent selected this hit as the rebuttal turn.",
                    ),
                ],
                source="retrieval",
                completeness=50,
                confidence=82,
            ),
        )


def test_pipeline_prefers_agent_synthesis_over_rule_judgment(monkeypatch, tmp_path):
    monkeypatch.setenv("ANALYSIS_PROVIDER", "kimi")
    monkeypatch.setenv("RETRIEVAL_PROVIDER", "kimi")
    monkeypatch.setenv("LLM_API_KEY", "test-llm-key")
    get_settings.cache_clear()

    pipeline = AnalyzePipeline()
    pipeline.agent_reasoner = FakeAgentReasoner()
    pipeline.provider_enricher.enrich = lambda event: (event, None)
    pipeline.retriever = RetrievalService(
        settings=replace(get_settings(), retrieval_provider="kimi"),
        provider=FakeLlmProvider(
            results=[
                SearchResult(
                    case_id="real_search",
                    query="最近有个女网红脑出血死了真的假的",
                    result_id="web-1",
                    title="医院回应女主播脑出血：仍在救治",
                    url="https://hospital.example.com/notice-1",
                    source_name="hospital.example.com",
                    published_at="2026-03-15T08:00:00+08:00",
                    snippet="医院通报称当事人仍在救治，网传死亡信息不实。",
                    source_tier="S",
                ),
                SearchResult(
                    case_id="real_search",
                    query="最近有个女网红脑出血死了真的假的",
                    result_id="web-2",
                    title="平台发布辟谣说明",
                    url="https://platform.example.com/statement-1",
                    source_name="platform.example.com",
                    published_at="2026-03-15T09:00:00+08:00",
                    snippet="平台称网传死亡和封锁消息不实。",
                    source_tier="A",
                ),
            ]
        ),
        cache=RetrievalCache(cache_root=tmp_path, ttl_seconds=3600),
    )

    report = pipeline.analyze(
        AnalyzeRequest(
            raw_input="最近有个女网红脑出血死了真的假的？",
            input_type="question",
        )
    )

    assert report.event.title == "女主播脑出血传闻与平台辟谣"
    assert report.provenance.retrieval_provider == "kimi"
    assert report.provenance.claim_source == "provider"
    assert report.provenance.evidence_source == "retrieval_live"
    assert report.provenance.timeline_source == "retrieval"
    assert report.provenance.provider_used is True
    assert report.claim_results[0].verdict == "supported"
    assert report.claim_results[1].verdict == "refuted"
    assert len(report.timeline) == 2


def test_agent_reasoner_uses_configured_search_model_verbatim():
    reasoner = LlmAgentReasoner(
        settings=replace(
            get_settings(),
            analysis_provider="kimi",
            llm_api_key="test-llm-key",
            llm_model="demo-model",
            llm_search_model="demo-search-model",
        )
    )

    # Config decides the model; no hard-coded rewrite.
    assert reasoner._reasoning_model() == "demo-search-model"
