from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator


InternalInputType = Literal["text_news", "url_news", "url_unknown", "question_only"]
ClaimType = Literal["fact", "opinion", "prediction", "unverifiable"]
VerdictType = Literal["supported", "refuted", "insufficient", "conflicting"]
ReportMode = Literal["complete_mode", "partial_mode", "safe_mode"]
ConfidenceLevel = Literal["high", "medium", "low"]
ConfidenceValue = Union[ConfidenceLevel, float]
SourceTier = Literal["S", "A", "B", "C"]
TimelineNodeType = Literal["origin", "amplification", "peak", "turn", "clarification"]


class MockFetchResult(BaseModel):
    status: str = "ok"
    title: Optional[str] = None
    body: Optional[str] = None
    snippet: Optional[str] = None
    source_name: Optional[str] = None
    published_at: Optional[str] = None


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


class Report(BaseModel):
    mode: ReportMode
    event: Event
    timeline: List[TimelineNode] = Field(default_factory=list)
    claim_results: List[ClaimResult] = Field(default_factory=list)
    final_summary: str
    risks: List[str] = Field(default_factory=list)
    sources: List[EvidenceItem] = Field(default_factory=list)


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
