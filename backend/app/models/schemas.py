from __future__ import annotations

from typing import Any, Literal, Union

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
ProbabilityBasis = Literal["evidence", "prior"]
EvidenceSourceType = Literal["retrieval_live", "retrieval_mock", "request_mock", "none"]
TimelineSourceType = Literal["retrieval", "input_seed", "none"]
ReportSourceType = Literal["backend_live", "backend_mock"]
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
    title: str | None = None
    body: str | None = None
    snippet: str | None = None
    source_name: str | None = None
    published_at: str | None = None
    final_url: str | None = None
    content_type: str | None = None
    fallback_reason: str | None = None
    error_message: str | None = None


class EvidenceItem(BaseModel):
    title: str
    url: str
    source_name: str
    published_at: str
    snippet: str
    relevance_reason: str
    source_tier: SourceTier = "C"
    stance: str | None = None
    stance_quote: str | None = None


class TimelineNode(BaseModel):
    node_type: TimelineNodeType = "origin"
    title: str
    url: str
    source_name: str
    published_at: str
    summary: str
    why_selected: str


class NormalizedEvent(BaseModel):
    title: str | None = None
    summary: str
    keywords: list[str] = Field(default_factory=list)
    source_name: str | None = None
    source_url: str | None = None
    published_at: str | None = None
    input_type: InternalInputType
    mode_hint: str = "partial"
    fallback_used: bool = False
    fallback_reason: str | None = None
    event_source: EventSourceType = "input_normalized"
    raw_input: str


class Event(BaseModel):
    title: str
    summary: str
    source_url: str
    source_name: str
    published_at: str
    keywords: list[str] = Field(default_factory=list)
    mode: ReportMode


class ClaimItem(BaseModel):
    claim: str
    claim_type: ClaimType


class ProviderEventDraft(BaseModel):
    title: str | None = None
    summary: str | None = None
    keywords: list[str] = Field(default_factory=list)
    source_name: str | None = None
    published_at: str | None = None


class ProviderAnalysis(BaseModel):
    event: ProviderEventDraft = Field(default_factory=ProviderEventDraft)
    claims: list[ClaimItem] = Field(default_factory=list)


class ClaimResult(BaseModel):
    claim: str
    claim_type: ClaimType
    verdict: VerdictType
    confidence: ConfidenceValue
    truth_probability: float | None = Field(default=None, ge=0, le=100)
    probability_basis: ProbabilityBasis | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)
    notes: str
    correction: dict[str, str] | None = None


class ReportProvenance(BaseModel):
    source_type: ReportSourceType = Field(
        ...,
        description="Backend currently emits backend_live/backend_mock.",
    )
    event_source: EventSourceType
    claim_source: ClaimSourceType
    evidence_source: EvidenceSourceType
    timeline_source: TimelineSourceType
    retrieval_provider: str | None = None
    retrieval_cache_status: str | None = None
    provider_used: bool = False
    fallback_used: bool = False
    fallback_reasons: list[str] = Field(default_factory=list)


class RetrievalDiagnostics(BaseModel):
    query: str = ""
    provider_name: str | None = None
    cache_status: str | None = None
    retrieved_at: str | None = None
    raw_result_count: int = 0
    canonical_result_count: int = 0
    failure_detail: str | None = None


class InvestigationStep(BaseModel):
    title: str
    detail: str


class PossibilityItem(BaseModel):
    scenario: str
    likelihood: ConfidenceLevel
    probability: float | None = Field(default=None, ge=0, le=100)
    basis: ProbabilityBasis | None = None
    summary: str


class Investigation(BaseModel):
    question: str
    reframed_question: str
    thinking_process: list[InvestigationStep] = Field(default_factory=list)
    possibilities: list[PossibilityItem] = Field(default_factory=list)
    final_conclusion: str


class ContentCheckItem(BaseModel):
    claim: str
    claim_type: ClaimType
    verdict: VerdictType
    confidence: ConfidenceValue
    truth_probability: float | None = Field(default=None, ge=0, le=100)
    probability_basis: ProbabilityBasis | None = None
    reason: str


class AnswerSuggestion(BaseModel):
    angle: str
    answer: str


class ContentCheck(BaseModel):
    likely_true: list[ContentCheckItem] = Field(default_factory=list)
    likely_false: list[ContentCheckItem] = Field(default_factory=list)
    controversial: list[ContentCheckItem] = Field(default_factory=list)
    opinions: list[ContentCheckItem] = Field(default_factory=list)
    uncertain: list[ContentCheckItem] = Field(default_factory=list)
    possible_answers: list[AnswerSuggestion] = Field(default_factory=list)


class PipelineTraceStep(BaseModel):
    stage_key: str
    title: str
    status: PipelineStepStatus = "completed"
    summary: str
    details: list[str] = Field(default_factory=list)
    # Timing lives on the trace step itself so the frontend renders straight
    # from the backend record instead of re-deriving offsets from the stream.
    # All four fields are optional to keep replay corpora and mock traces
    # backwards-compatible.
    started_at: str | None = None
    ended_at: str | None = None
    duration_ms: int | None = None
    offset_ms: int | None = None
    is_parallel_group: bool = False
    parent_stage_key: str | None = None


class PipelineTrace(BaseModel):
    steps: list[PipelineTraceStep] = Field(default_factory=list)


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
    limiting_factors: list[str] = Field(default_factory=list)


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
    timeline: list[TimelineNode] = Field(default_factory=list)
    claim_results: list[ClaimResult] = Field(default_factory=list)
    final_summary: str
    risks: list[str] = Field(default_factory=list)
    sources: list[EvidenceItem] = Field(default_factory=list)
    retrieval_hits: list[EvidenceItem] = Field(default_factory=list)
    retrieval_diagnostics: RetrievalDiagnostics | None = None
    overall_credibility_score: float | None = Field(default=None, ge=0, le=100)
    overall_credibility_label: CredibilityLabel | None = None
    score_breakdown: ScoreBreakdown | None = None
    claim_contributions: list[ClaimContribution] | None = None
    timeline_confidence: float | None = Field(default=None, ge=0, le=100)
    independent_source_count: int | None = Field(default=None, ge=0)
    investigation: Investigation | None = None
    content_check: ContentCheck | None = None
    pipeline_trace: PipelineTrace | None = None
    provenance: ReportProvenance


class AnalyzeRequest(BaseModel):
    raw_input: str = Field(..., min_length=1)
    input_type: str | None = None
    mock_fetch_result: MockFetchResult | None = None
    mock_evidence: list[EvidenceItem] = Field(default_factory=list)
    request_context: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def remap_legacy_fields(cls, value: Any) -> Any:
        if isinstance(value, dict):
            payload = dict(value)
            if not payload.get("raw_input") and payload.get("input"):
                payload["raw_input"] = payload["input"]
            return payload
        return value
