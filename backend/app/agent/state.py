from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from backend.app.models.schemas import (
    AnalyzeRequest,
    ClaimItem,
    NormalizedEvent,
    Report,
)
from backend.app.services.claim_extractor import ClaimExtraction
from backend.app.services.question_resolver import QuestionResolution
from backend.app.services.retrieval_models import RetrievalBundle
from backend.app.services.timeline_builder import TimelineBuild
from backend.app.services.verdict_engine import VerdictEvaluation


@dataclass
class AgentStep:
    """One recorded step in the investigation loop (for tracing/decisions)."""

    action: str
    summary: str = ""
    details: List[str] = field(default_factory=list)


@dataclass
class AgentState:
    """Mutable blackboard threaded through the tools by the runner.

    Every tool reads what it needs from here and writes its output back, so the
    runner and planner stay small and the tools stay composable. Field names
    mirror the locals the legacy AnalyzePipeline.analyze() used, which keeps the
    RulePlanner path behaviourally identical to the old fixed pipeline.
    """

    request: AnalyzeRequest

    normalized_event: Optional[NormalizedEvent] = None
    resolved_event: Optional[NormalizedEvent] = None
    final_event: Optional[NormalizedEvent] = None

    initial_retrieval_bundle: Optional[RetrievalBundle] = None
    retrieval_bundle: Optional[RetrievalBundle] = None
    follow_up_bundle: Optional[RetrievalBundle] = None
    follow_up_used: bool = False

    question_resolution: Optional[QuestionResolution] = None

    provider_claims: Optional[List[ClaimItem]] = None
    claim_extraction: Optional[ClaimExtraction] = None
    verdict: Optional[VerdictEvaluation] = None
    timeline: Optional[TimelineBuild] = None

    agent_synthesized: bool = False
    synthesis_attempted: bool = False
    investigation_rounds: int = 0

    # Full-body pages fetched by the fetch_url tool, keyed by the canonical
    # SearchResult.result_id they enrich (grounding-safe: no new evidence ids).
    fetched_bodies: Dict[str, str] = field(default_factory=dict)
    fetched_urls: Set[str] = field(default_factory=set)
    # Upper bound on fetch_url actions; the runner sets it from settings so the
    # planner stays a pure function of state.
    max_url_fetches: int = 0

    report: Optional[Report] = None
    steps: List[AgentStep] = field(default_factory=list)
    done_actions: List[str] = field(default_factory=list)

    def record(self, action: str, summary: str = "", details: Optional[List[str]] = None) -> None:
        self.steps.append(AgentStep(action=action, summary=summary, details=details or []))

    @property
    def event(self) -> NormalizedEvent:
        """Current best event: final > resolved > normalized."""
        current = self.final_event or self.resolved_event or self.normalized_event
        if current is None:
            raise RuntimeError("AgentState.event accessed before normalize step")
        return current
