from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from backend.app.models.schemas import (
    AnalyzeRequest,
    ClaimItem,
    NormalizedEvent,
    PossibilityItem,
    Report,
)
from backend.app.services.claim_extractor import ClaimExtraction
from backend.app.services.question_resolver import QuestionResolution
from backend.app.services.retrieval_models import RetrievalBundle
from backend.app.services.timeline_builder import TimelineBuild
from backend.app.services.verdict_engine import VerdictEvaluation


@dataclass(frozen=True)
class StepOutcome:
    """Result of a single dispatch step — success or failure with context."""

    action: str
    success: bool
    summary: str = ""
    error_type: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class TokenUsage:
    """Accumulated token usage across all LLM calls in one analysis run."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    call_count: int = 0
    # Parallel source agents can fire LLM calls concurrently, so the read-modify-
    # write of these counters must be serialized or totals get lost to races.
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def add(self, prompt: int = 0, completion: int = 0, total: int = 0) -> None:
        with self._lock:
            self.prompt_tokens += prompt
            self.completion_tokens += completion
            self.total_tokens += total or (prompt + completion)
            self.call_count += 1


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
    # Parallel-DAG scratch: each source agent writes its own bundle under a
    # source key ("baidu"/"xiaohongshu"/...); the merge agent recombines them
    # into retrieval_bundle. Empty on the sequential DAG.
    source_bundles: Dict[str, RetrievalBundle] = field(default_factory=dict)
    # Primary search query computed once by the normalize agent so parallel
    # source agents reuse it (via force_retrieval_query) instead of each
    # re-running the query planner (which can cost an LLM round-trip).
    primary_query: Optional[str] = None

    question_resolution: Optional[QuestionResolution] = None

    provider_claims: Optional[List[ClaimItem]] = None
    claim_extraction: Optional[ClaimExtraction] = None
    verdict: Optional[VerdictEvaluation] = None
    timeline: Optional[TimelineBuild] = None
    # LLM-produced mutually-exclusive whole-message scenarios. When synthesis
    # succeeds these override the rule-based possibilities in the final report;
    # empty when synthesis fell back to the rule chain.
    possibilities: List[PossibilityItem] = field(default_factory=list)

    agent_synthesized: bool = False
    synthesis_attempted: bool = False
    investigation_rounds: int = 0
    # Per-claim search iterations: counts completed search→re-judge cycles
    # (incremented after each re_judge) so the planner can decide when to stop.
    per_claim_iterations: int = 0
    # Counts per-claim searches that have fired. It leads per_claim_iterations by
    # exactly 1 while a round's search has run but its re-judge has not; that gap
    # is how legal_actions re-enters the loop without ever mutating done_actions.
    per_claim_searches: int = 0
    max_per_claim_iterations: int = 3

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

    # --- New harness fields ---

    # Outcome of the most recent dispatch step. The planner reads this to make
    # informed decisions after a failure (retry, skip, or re-plan).
    last_step_outcome: Optional[StepOutcome] = None

    # Accumulated token usage from all LLM calls this run.
    token_usage: TokenUsage = field(default_factory=TokenUsage)

    # Hard ceiling on total tokens for this run. 0 means unlimited.
    # When exceeded, legal_actions forces early synthesis/finalize.
    max_token_budget: int = 0

    # Set by the runner when the overall wall-clock deadline passes. Like
    # max_token_budget exhaustion, it makes legal_actions force the shortest path
    # to a report — a soft landing instead of accumulating per-step timeouts.
    time_exhausted: bool = False

    # Cooperative cancellation flag. The runner checks this before each step;
    # external code (e.g. SSE disconnect handler) sets it to abort the loop.
    cancelled: bool = False

    def record(self, action: str, summary: str = "", details: Optional[List[str]] = None) -> None:
        self.steps.append(AgentStep(action=action, summary=summary, details=details or []))

    @property
    def event(self) -> NormalizedEvent:
        """Current best event: final > resolved > normalized."""
        current = self.final_event or self.resolved_event or self.normalized_event
        if current is None:
            raise RuntimeError("AgentState.event accessed before normalize step")
        return current
