from __future__ import annotations

import threading
from dataclasses import dataclass, field

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
    error_type: str | None = None
    error_message: str | None = None


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
    details: list[str] = field(default_factory=list)


@dataclass
class AgentState:
    """Mutable blackboard threaded through the tools by the runner.

    Every tool reads what it needs from here and writes its output back, so the
    runner and planner stay small and the tools stay composable. Field names
    mirror the locals the legacy AnalyzePipeline.analyze() used, which keeps the
    RulePlanner path behaviourally identical to the old fixed pipeline.
    """

    request: AnalyzeRequest

    normalized_event: NormalizedEvent | None = None
    resolved_event: NormalizedEvent | None = None
    final_event: NormalizedEvent | None = None

    initial_retrieval_bundle: RetrievalBundle | None = None
    retrieval_bundle: RetrievalBundle | None = None
    follow_up_bundle: RetrievalBundle | None = None
    follow_up_used: bool = False
    # Parallel-DAG scratch: each source agent writes its own bundle under a
    # source key ("baidu"/"xiaohongshu"/...); the merge agent recombines them
    # into retrieval_bundle. Empty on the sequential DAG.
    source_bundles: dict[str, RetrievalBundle] = field(default_factory=dict)
    # Primary search query computed once by the normalize agent so parallel
    # source agents reuse it (via force_retrieval_query) instead of each
    # re-running the query planner (which can cost an LLM round-trip).
    primary_query: str | None = None

    question_resolution: QuestionResolution | None = None

    provider_claims: list[ClaimItem] | None = None
    claim_extraction: ClaimExtraction | None = None
    verdict: VerdictEvaluation | None = None
    timeline: TimelineBuild | None = None
    # LLM-produced mutually-exclusive whole-message scenarios. When synthesis
    # succeeds these override the rule-based possibilities in the final report;
    # empty when synthesis fell back to the rule chain.
    possibilities: list[PossibilityItem] = field(default_factory=list)

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
    # Supervisor loop-back reuses the existing retrieval bundle and asks the
    # AnalysisAgent to begin directly with per-claim enrichment + re-judging.
    loop_back_enrichment: bool = False

    # Full-body pages fetched by the fetch_url tool, keyed by the canonical
    # SearchResult.result_id they enrich (grounding-safe: no new evidence ids).
    fetched_bodies: dict[str, str] = field(default_factory=dict)
    fetched_urls: set[str] = field(default_factory=set)
    # Upper bound on fetch_url actions; the runner sets it from settings so the
    # planner stays a pure function of state.
    max_url_fetches: int = 0

    report: Report | None = None
    steps: list[AgentStep] = field(default_factory=list)
    done_actions: list[str] = field(default_factory=list)

    # --- New harness fields ---

    # Outcome of the most recent dispatch step. The planner reads this to make
    # informed decisions after a failure (retry, skip, or re-plan).
    last_step_outcome: StepOutcome | None = None

    # Accumulated token usage from all LLM calls this run.
    token_usage: TokenUsage = field(default_factory=TokenUsage)

    # Hard ceiling on total tokens for this run. 0 means unlimited.
    # When exceeded, legal_actions forces early synthesis/finalize.
    max_token_budget: int = 0

    # Set by the runner when the overall wall-clock deadline passes. Like
    # max_token_budget exhaustion, it makes legal_actions force the shortest path
    # to a report — a soft landing instead of accumulating per-step timeouts.
    time_exhausted: bool = False

    # Debate loop: how many Analysis ↔ Critic debate rounds have completed.
    # The supervisor increments this each time it re-runs Analysis after a critic
    # downgrade. Max rounds is controlled by MULTI_AGENT_DEBATE_ROUNDS.
    debate_rounds: int = 0
    # Indices of claims the critic just downgraded — tells the AnalysisAgent to
    # focus its per-claim search loop only on these (not all insufficient claims).
    debate_focus_indices: set[int] | None = None
    # Post-critic verdict fingerprint from the previous debate round. If the next
    # round produces the same fingerprint, the debate has converged.
    debate_verdict_fingerprint: str | None = None

    # Cooperative cancellation flag. The runner checks this before each step;
    # external code (e.g. SSE disconnect handler) sets it to abort the loop.
    cancelled: bool = False

    def record(self, action: str, summary: str = "", details: list[str] | None = None) -> None:
        self.steps.append(AgentStep(action=action, summary=summary, details=details or []))

    @property
    def event(self) -> NormalizedEvent:
        """Current best event: final > resolved > normalized."""
        current = self.final_event or self.resolved_event or self.normalized_event
        if current is None:
            raise RuntimeError("AgentState.event accessed before normalize step")
        return current
