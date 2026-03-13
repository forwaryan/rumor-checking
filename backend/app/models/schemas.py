from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


InputType = Literal["text_news", "url_news", "url_unknown", "question_only"]
ClaimType = Literal["fact", "opinion", "prediction", "unverifiable"]
VerdictType = Literal["supported", "refuted", "insufficient", "conflicting"]
ReportMode = Literal["complete_mode", "partial_mode", "safe_mode"]


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
    source_name: Optional[str] = None
    published_at: Optional[str] = None
    snippet: str = ""
    relevance_reason: Optional[str] = None
    source_tier: str = "C"


class TimelineNode(BaseModel):
    title: str
    date: Optional[str] = None
    description: str
    node_type: str = "event"
    source_name: Optional[str] = None
    source_url: Optional[str] = None
    confidence: str = "medium"


class EventDraft(BaseModel):
    title: Optional[str] = None
    summary: str
    keywords: List[str] = Field(default_factory=list)
    source_name: Optional[str] = None
    published_at: Optional[str] = None
    input_type: InputType
    mode_hint: str = "partial"
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
    raw_input: str


class ClaimItem(BaseModel):
    claim: str
    claim_type: ClaimType


class ClaimResult(BaseModel):
    claim: str
    claim_type: ClaimType
    verdict: Optional[VerdictType] = None
    confidence: Optional[str] = None
    rationale: str
    evidence: List[EvidenceItem] = Field(default_factory=list)
    status: str = "needs_review"


class Report(BaseModel):
    mode: ReportMode
    event: EventDraft
    claim_results: List[ClaimResult] = Field(default_factory=list)
    timeline: List[TimelineNode] = Field(default_factory=list)
    evidence: List[EvidenceItem] = Field(default_factory=list)
    final_summary: str
    risks: List[str] = Field(default_factory=list)
    unknowns: List[str] = Field(default_factory=list)
    next_steps: List[str] = Field(default_factory=list)
    boundary: str
    fallback: Optional[Dict[str, Any]] = None


class AnalyzeRequest(BaseModel):
    raw_input: str = Field(..., min_length=1)
    input_type: Optional[InputType] = None
    mock_fetch_result: Optional[MockFetchResult] = None
    mock_evidence: List[EvidenceItem] = Field(default_factory=list)
    request_context: Dict[str, Any] = Field(default_factory=dict)


class AnalyzeResponse(BaseModel):
    request_id: str
    report: Report
