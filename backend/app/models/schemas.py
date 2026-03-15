from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator


InternalInputType = Literal["text_news", "url_news", "url_unknown", "question_only"]
ClaimType = Literal["fact", "opinion", "prediction", "unverifiable"]
VerdictType = Literal["supported", "refuted", "insufficient", "conflicting"]
ReportMode = Literal["complete_mode", "partial_mode", "safe_mode"]
ConfidenceLevel = Literal["high", "medium", "low"]
ConfidenceValue = Union[ConfidenceLevel, float]
PipelineStepStatus = Literal["completed", "warning", "skipped", "error"]
SourceTier = Literal["S", "A", "B", "C"]
TimelineNodeType = Literal["origin", "amplification", "peak", "turn", "clarification"]
UrlFetchStatus = Literal["ok", "partial", "empty", "timeout", "error", "unsupported"]
EventSourceType = Literal["input_normalized", "url_extract", "provider_enriched", "retrieval_resolved"]
ClaimSourceType = Literal["rule", "provider", "provider_plus_rule"]
EvidenceSourceType = Literal["retrieval_live", "retrieval_mock", "request_mock", "none"]
TimelineSourceType = Literal["retrieval", "input_seed", "none"]
ReportSourceType = Literal["backend_live", "backend_mock", "backend_replay", "demo_payload", "frontend_fallback"]
CredibilityLabel = Literal[
    "high_credibility",
    "medium_credibility",
    "low_credibility",
    "mixed",
    "insufficient_evidence",
]
ContributionLabel = Literal["supports", "weakens", "mixed", "neutral"]


class MockFetchResult(BaseModel):
    status: UrlFetchStatus = "ok"
    title: Optional[str] = None
    body: Optional[str] = None
    snippet: Optional[str] = None
    source_name: Optional[str] = None
    published_at: Optional[str] = None
    final_url: Optional[str] = None
    content_type: Optional[str] = None
    fallback_reason: Optional[str] = None
    error_message: Optional[str] = None


class EvidenceItem(BaseModel):
    title: str
    url: str
    source_name: str
    published_at: str
    snippet: str
    relevance_reason: str
    source_tier: SourceTier = "C"


class TimelineNode(BaseModel):
    node_type: TimelineNodeType = "origin"
    title: str
    url: str
    source_name: str
    published_at: str
    summary: str
    why_selected: str


class NormalizedEvent(BaseModel):
    title: Optional[str] = None
    summary: str
    keywords: List[str] = Field(default_factory=list)
    source_name: Optional[str] = None
    source_url: Optional[str] = None
    published_at: Optional[str] = None
    input_type: InternalInputType
    mode_hint: str = "partial"
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
    event_source: EventSourceType = "input_normalized"
    raw_input: str


class Event(BaseModel):
    title: str
    summary: str
    source_url: str
    source_name: str
    published_at: str
    keywords: List[str] = Field(default_factory=list)
    mode: ReportMode


class ClaimItem(BaseModel):
    claim: str
    claim_type: ClaimType


class ProviderEventDraft(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    keywords: List[str] = Field(default_factory=list)
    source_name: Optional[str] = None
    published_at: Optional[str] = None


class ProviderAnalysis(BaseModel):
    event: ProviderEventDraft = Field(default_factory=ProviderEventDraft)
    claims: List[ClaimItem] = Field(default_factory=list)


class ClaimResult(BaseModel):
    claim: str
    claim_type: ClaimType
    verdict: VerdictType
    confidence: ConfidenceValue
    evidence: List[EvidenceItem] = Field(default_factory=list)
    notes: str


class ReportProvenance(BaseModel):
    source_type: ReportSourceType = Field(
        ...,
        description=(
            "Backend currently emits backend_live/backend_mock/backend_replay. "
            "Frontend may additionally use demo_payload/frontend_fallback for local-only states."
        ),
    )
    event_source: EventSourceType
    claim_source: ClaimSourceType
    evidence_source: EvidenceSourceType
    timeline_source: TimelineSourceType
    retrieval_provider: Optional[str] = None
    retrieval_cache_status: Optional[str] = None
    provider_used: bool = False
    fallback_used: bool = False
    fallback_reasons: List[str] = Field(default_factory=list)


class RetrievalDiagnostics(BaseModel):
    query: str = ""
    provider_name: Optional[str] = None
    cache_status: Optional[str] = None
    retrieved_at: Optional[str] = None
    raw_result_count: int = 0
    canonical_result_count: int = 0
    failure_detail: Optional[str] = None


class InvestigationStep(BaseModel):
    title: str
    detail: str


class PossibilityItem(BaseModel):
    scenario: str
    likelihood: ConfidenceLevel
    summary: str


class Investigation(BaseModel):
    question: str
    reframed_question: str
    thinking_process: List[InvestigationStep] = Field(default_factory=list)
    possibilities: List[PossibilityItem] = Field(default_factory=list)
    final_conclusion: str


class ContentCheckItem(BaseModel):
    claim: str
    claim_type: ClaimType
    verdict: VerdictType
    confidence: ConfidenceValue
    reason: str


class AnswerSuggestion(BaseModel):
    angle: str
    answer: str


class ContentCheck(BaseModel):
    likely_true: List[ContentCheckItem] = Field(default_factory=list)
    likely_false: List[ContentCheckItem] = Field(default_factory=list)
    controversial: List[ContentCheckItem] = Field(default_factory=list)
    opinions: List[ContentCheckItem] = Field(default_factory=list)
    uncertain: List[ContentCheckItem] = Field(default_factory=list)
    possible_answers: List[AnswerSuggestion] = Field(default_factory=list)


class PipelineTraceStep(BaseModel):
    stage_key: str
    title: str
    status: PipelineStepStatus = "completed"
    summary: str
    details: List[str] = Field(default_factory=list)


class PipelineTrace(BaseModel):
    steps: List[PipelineTraceStep] = Field(default_factory=list)


class ScoreWeights(BaseModel):
    claim: Literal[0.5] = 0.5
    source_quality: Literal[0.2] = 0.2
    cross_source_agreement: Literal[0.2] = 0.2
    timeline: Literal[0.1] = 0.1


class ScoreBreakdown(BaseModel):
    claim_score: float = Field(..., ge=0, le=100)
    source_quality_score: float = Field(..., ge=0, le=100)
    cross_source_agreement_score: float = Field(..., ge=0, le=100)
    timeline_score: float = Field(..., ge=0, le=100)
    weights: ScoreWeights = Field(default_factory=ScoreWeights)
    summary: str
    limiting_factors: List[str] = Field(default_factory=list)


class ClaimContribution(BaseModel):
    claim: str
    claim_type: ClaimType
    verdict: VerdictType
    contribution_label: ContributionLabel
    contribution_score: float = Field(..., ge=-100, le=100)
    reason: str


class Report(BaseModel):
    mode: ReportMode
    event: Event
    timeline: List[TimelineNode] = Field(default_factory=list)
    claim_results: List[ClaimResult] = Field(default_factory=list)
    final_summary: str
    risks: List[str] = Field(default_factory=list)
    sources: List[EvidenceItem] = Field(default_factory=list)
    retrieval_hits: List[EvidenceItem] = Field(default_factory=list)
    retrieval_diagnostics: Optional[RetrievalDiagnostics] = None
    overall_credibility_score: Optional[float] = Field(default=None, ge=0, le=100)
    overall_credibility_label: Optional[CredibilityLabel] = None
    score_breakdown: Optional[ScoreBreakdown] = None
    claim_contributions: Optional[List[ClaimContribution]] = None
    timeline_confidence: Optional[float] = Field(default=None, ge=0, le=100)
    independent_source_count: Optional[int] = Field(default=None, ge=0)
    investigation: Optional[Investigation] = None
    content_check: Optional[ContentCheck] = None
    pipeline_trace: Optional[PipelineTrace] = None
    provenance: ReportProvenance


class AnalyzeRequest(BaseModel):
    raw_input: str = Field(..., min_length=1)
    input_type: Optional[str] = None
    mock_fetch_result: Optional[MockFetchResult] = None
    mock_evidence: List[EvidenceItem] = Field(default_factory=list)
    request_context: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def remap_legacy_fields(cls, value: Any) -> Any:
        if isinstance(value, dict):
            payload = dict(value)
            if not payload.get("raw_input") and payload.get("input"):
                payload["raw_input"] = payload["input"]
            return payload
        return value
