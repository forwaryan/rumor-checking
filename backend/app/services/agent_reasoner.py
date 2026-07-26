from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from backend.app.core.config import Settings, get_settings
from backend.app.models.schemas import (
    AnalyzeRequest,
    ClaimItem,
    ClaimResult,
    ConfidenceValue,
    EvidenceSourceType,
    NormalizedEvent,
    PossibilityItem,
    TimelineNode,
)
from backend.app.services.claim_extractor import ClaimExtraction
from backend.app.services.claim_correction import annotate_claim_corrections
from backend.app.services.contract_utils import default_source_name, default_source_url, ensure_datetime_string, loads_lenient_json
from backend.app.services.progress import emit_api_call, emit_log
from backend.app.services.question_intent import is_broad_trend_question
from backend.app.services.question_resolver import QuestionResolution
from backend.app.services.retrieval_models import RetrievalBundle, SearchResult
from backend.app.services.timeline_builder import TimelineBuild
from backend.app.services.verdict_engine import VerdictEvaluation

logger = logging.getLogger(__name__)

# Chars-per-token multiplier for the client-side stream budget. Deliberately
# generous (a token is ~1-4 chars) so the char cap only trips on genuine runaway
# output the model's own max_tokens failed to bound — never a well-formed response.
_STREAM_CHARS_PER_TOKEN = 8


def _full_text(text: str) -> str:
    """Collapse a prompt/response to a single line for a progress event's detail
    list (a flat list of strings), but never truncate — the whole LLM exchange
    rides in the trace so it is fully inspectable. The frontend re-parses and
    pretty-prints any JSON block, so structure is not lost for the reader."""
    return re.sub(r"\s+", " ", text or "").strip()

ALLOWED_CLAIM_TYPES = {"fact", "opinion", "prediction", "unverifiable"}
ALLOWED_VERDICTS = {"supported", "refuted", "insufficient", "conflicting"}
ALLOWED_CONFIDENCE = {"high", "medium", "low"}
ALLOWED_TIMELINE_TYPES = {"origin", "amplification", "peak", "turn", "clarification"}
QUESTION_RESOLUTION_SYSTEM_PROMPT = """
You are the event-resolution stage for a rumor-checking backend.
You only see a user question and a small set of retrieval hits.
Your job is to decide whether the hits can be anchored to one specific event.

Return one JSON object with this schema:
{
  "selected_result_id": "string or null",
  "resolved_summary": "string or null",
  "follow_up_query": "string or null",
  "reason": "short string"
}

Rules:
- Use only the supplied retrieval hits. Never invent people, dates, causes, or links.
- If the hits are about multiple different people or incidents, do not force a single anchor. Return null.
- If the question is broad, ambiguous, or trend-like, do not force a single anchor. Return null.
- Only choose a result when the title/snippet clearly matches the same event the user is asking about.
- `follow_up_query` should be 4 to 10 concise search terms derived from the selected hit. If no stable anchor exists, return null.
- Output a single raw JSON object ONLY: no markdown, no ```json code fences, no prose before or after. Escape every double-quote that appears inside a string value as \\".
""".strip()
# NOTE: SYNTHESIS_SYSTEM_PROMPT (original full-output version) kept as backup.
# It required claims + event + scenarios + timeline, causing V4-Flash truncation.
# Replaced by CLAIMS_ONLY_SYSTEM_PROMPT below for production use.
#
# SYNTHESIS_SYSTEM_PROMPT = """
# You are the evidence-grounded synthesis stage for a rumor-checking backend.
# You must use only the supplied retrieval hits and event context.
#
# Return one JSON object with this schema:
# {
#   "claims": [...],
#   "event": { "title": ..., "summary": ..., "source_name": ..., "published_at": ..., "anchor_result_id": ... },
#   "scenarios": [{ "label": ..., "probability": 0-100, "basis": ..., "summary": ... }],
#   "timeline": [{ "node_type": ..., "result_id": ..., "summary": ..., "why_selected": ... }]
# }
# (Full original prompt omitted for brevity — see git history for complete text.)
# """

CLAIMS_ONLY_SYSTEM_PROMPT = """
You are the evidence-grounded synthesis stage for a rumor-checking backend.
You must use only the supplied retrieval hits and event context.

Return one JSON object with this schema:
{
  "claims": [
    {
      "claim": "string",
      "claim_type": "fact|opinion|prediction|unverifiable",
      "verdict": "supported|refuted|insufficient|conflicting",
      "confidence": "high|medium|low",
      "truth_probability": 0-100,
      "probability_basis": "evidence|prior",
      "evidence_result_ids": ["result_id"],
      "notes": "string (≤60 Chinese chars)"
    }
  ]
}

Think briefly, then output the JSON. Keep notes within the char cap.

Rules:
- Use only supplied retrieval hits. Never invent result ids, evidence, or URLs.
- Claims must be atomic and directly checkable. Prefer 1 to 4 claims, up to 6 if splitting.
- CLAIM DECOMPOSITION — split a verified core from an unverified detail:
  - When the hits support the core but NOT a specific quantifier/qualifier, emit TWO claims:
    1. the CORE (supported), and 2. the DETAIL alone (insufficient).
  - Keep each split claim self-contained (name the subject; no back-references).
- PROBABILITY (independent of verdict):
  - `truth_probability` = P(this claim is literally true), 0-100.
  - `probability_basis` = "evidence" ONLY if hits bear on this claim; else "prior".
  - You MUST give a number even with zero evidence — use prior.
  - Probability does NOT change the verdict. Keep the two independent.
- CRITICAL verdict decision procedure:
  1. Find hits about the SAME subject AND action as the claim.
  2. If NONE → `insufficient`. Not finding proof ≠ disproof.
  3. `refuted` ONLY when a hit EXPLICITLY contradicts THIS claim for THIS subject.
  4. `supported` only with evidence that directly affirms the claim (respect scope).
  5. `conflicting` when reputable hits both affirm and deny the SAME claim.
- Scope discipline: absolute-scope claims need full-scope evidence for `supported`.
- Do not emit `supported`/`refuted`/`conflicting` without at least one valid evidence_result_id.
- Output a single raw JSON object ONLY: no markdown, no ```json code fences, no prose before or after. Escape every double-quote that appears inside a string value as \\".
""".strip()

# Keep the old constant name as an alias so any external references still resolve.
SYNTHESIS_SYSTEM_PROMPT = CLAIMS_ONLY_SYSTEM_PROMPT
INVESTIGATION_PLAN_SYSTEM_PROMPT = """
You are the investigation-planning stage for a rumor-checking backend.
You see the current event context and a compact snapshot of the evidence gathered so far.
Your only job is to decide whether one more targeted retrieval round is worth running.

Return one JSON object with this schema:
{
  "should_continue": true or false,
  "follow_up_query": "string or null",
  "reason": "short string"
}

Rules:
- Continue only when the current evidence is weak, one-sided, or missing an authoritative source,
  AND a sharper query could plausibly close that gap.
- Prefer follow-up queries that target official notices, primary sources, or authoritative media.
- `follow_up_query` should be 4 to 10 concise search terms. If you would not continue, return null.
- If the evidence is already strong and independently corroborated, set should_continue to false.
- Never invent facts. Base the decision only on the supplied snapshot.
- Output a single raw JSON object ONLY: no markdown, no ```json code fences, no prose before or after. Escape every double-quote that appears inside a string value as \\".
""".strip()
NEXT_ACTION_SYSTEM_PROMPT = """
You are the planner for a rumor-checking investigation agent.
At each step you choose the single next action from a fixed list of allowed actions.
You see what has already been done and a compact snapshot of the evidence so far.

Return one JSON object with this schema:
{
  "next_action": "one of the allowed action names",
  "reason": "short string"
}

Action meanings:
- "investigate": run one more targeted retrieval round to strengthen weak/one-sided evidence.
- "fetch_url": fetch the FULL body of the single most authoritative evidence page (retrieval only
  gives short snippets); choose this when one high-trust source likely has decisive detail its
  snippet does not show.
- "synthesize": stop gathering and produce the grounded event, claims, verdicts, and timeline.

Rules:
- Choose "next_action" ONLY from the supplied allowed_actions list. Never invent an action.
- Read evidence.top_results (title/source/snippet of the strongest hits), not just the counts:
  judge whether their SUBSTANCE actually settles the claim before deciding.
- Prefer "investigate" when evidence is weak (low grade, few independent high-trust sources,
  conflicting signals) AND another round could plausibly help.
- Prefer "fetch_url" when there is a strong source whose snippet is too thin to decide, and reading
  its full text would likely settle the claim. Use sparingly (each fetch is a live HTTP round).
- Prefer "synthesize" when evidence is already strong and independently corroborated, or when
  further searching is unlikely to help.
- Output a single raw JSON object ONLY: no markdown, no ```json code fences, no prose before or after. Escape every double-quote that appears inside a string value as \\".
""".strip()
NEXT_ACTION_SEQUENCE_SYSTEM_PROMPT = """
You are the planner for a rumor-checking investigation agent.
Instead of one step, you propose the ORDERED sequence of actions you intend to take
from here — a short plan the agent will follow while each step stays valid.
You see what has already been done and a compact snapshot of the evidence so far.

Return one JSON object with this schema:
{
  "actions": ["ordered action names, most immediate first"],
  "reason": "short string"
}

Action meanings:
- "investigate": run one more targeted retrieval round to strengthen weak/one-sided evidence.
- "fetch_url": fetch the FULL body of the single most authoritative evidence page (retrieval only
  gives short snippets); choose this when one high-trust source likely has decisive detail its
  snippet does not show.
- "synthesize": stop gathering and produce the grounded event, claims, verdicts, and timeline.

Rules:
- Use ONLY action names from the supplied allowed_actions list. Never invent an action.
- The FIRST element must be a member of allowed_actions — it is what runs next.
- Read evidence.top_results (title/source/snippet of the strongest hits), not just the counts:
  plan around whether their SUBSTANCE settles the claim.
- A good plan usually ends in "synthesize". Put evidence-gathering steps (investigate/fetch_url)
  first ONLY when the current evidence is genuinely too weak or thin to decide, then synthesize.
- When evidence is already strong and independently corroborated, propose just ["synthesize"].
- Keep the plan short (1 to 3 steps). Do not pad it.
- Output a single raw JSON object ONLY: no markdown, no ```json code fences, no prose before or after. Escape every double-quote that appears inside a string value as \\".
""".strip()
SYNTHESIS_CRITIC_SYSTEM_PROMPT = """
You are the verification critic for a rumor-checking backend.
Another stage already produced verdicts for a set of claims, each with the specific
evidence snippets it cited. Your ONLY job is to catch claims whose verdict is NOT
actually supported by its own cited evidence — an over-confident or unfaithful call.

You receive a JSON list of judged claims. Each has: index, claim, verdict
("supported"|"refuted"|"conflicting"), and evidence (the cited snippets).

Return one JSON object with this schema:
{
  "revisions": [
    { "index": <int>, "keep": true|false, "reason": "short string" }
  ]
}

Rules:
- Judge each claim ONLY against ITS OWN cited evidence. Never use outside knowledge.
- "keep": true  -> the cited evidence genuinely justifies the stated verdict.
- "keep": false -> the evidence does NOT justify the verdict (too weak, off-topic,
  says something narrower, or contradicts a "supported"/"refuted" call). The claim
  will be downgraded to "insufficient".
- You may ONLY flag claims for downgrade. You cannot upgrade or change a verdict to
  anything other than the downgrade. When in doubt, keep.
- Include an entry ONLY for claims you want to downgrade (keep:false). Omit the rest.
- Output a single raw JSON object ONLY: no markdown, no ```json code fences, no prose before or after. Escape every double-quote that appears inside a string value as \\".
""".strip()
ENRICHMENT_SYSTEM_PROMPT = """
You are the evidence-grounded enrichment stage for a rumor-checking backend.
You have already seen the claims and verdicts for this event. Now produce a
structured event summary, possible scenarios, and a timeline.

Return one JSON object with this schema:
{
  "event": {
    "title": "concise event title (≤30 Chinese chars)",
    "summary": "one-sentence grounded summary of what happened"
  },
  "scenarios": [
    {
      "label": "short scenario name",
      "probability": 0-100,
      "basis": "evidence|prior",
      "summary": "one-sentence explanation"
    }
  ],
  "timeline": [
    {
      "node_type": "origin|amplification|peak|turn|clarification",
      "result_id": "the retrieval hit's result_id",
      "summary": "what this node represents",
      "why_selected": "why this hit is a timeline milestone"
    }
  ]
}

Rules:
- scenarios: 2-4 mutually exclusive whole-message interpretations. Probabilities must sum to ~100.
  Always include a "claim is essentially true" and "claim is false/exaggerated" scenario.
  basis = "evidence" only when hits bear directly on it; else "prior".
- timeline: pick 2-5 retrieval hits that represent key propagation milestones.
  Each node_type appears at most once. Only use result_ids from the supplied hits.
  If fewer than 2 hits qualify as milestones, return an empty timeline array.
- event: refine the title and summary based on what the evidence actually shows.
  Keep it factual and grounded — do not editorialise.
- Output a single raw JSON object ONLY: no markdown, no ```json code fences, no prose before or after. Escape every double-quote that appears inside a string value as \\".
""".strip()

CRITIC_REFINE_SYSTEM_PROMPT = """
You are the targeted re-verdict stage for a rumor-checking backend.
The critic already flagged specific claims whose verdicts were NOT justified by
their cited evidence. You now re-judge ONLY those claims using the FULL evidence
pool (not just their originally cited hits).

Return one JSON object with this schema:
{
  "refined_claims": [
    {
      "index": <int>,
      "verdict": "supported|refuted|insufficient|conflicting",
      "confidence": "high|medium|low",
      "evidence_result_ids": ["result_id"],
      "notes": "string (≤60 Chinese chars)"
    }
  ]
}

Rules:
- Only re-judge the claims listed. Do not add or remove claims.
- Use the same verdict decision procedure as synthesis: evidence must directly
  affirm/contradict the claim for supported/refuted. Without clear grounding, stay insufficient.
- evidence_result_ids must come from the supplied retrieval hits. Do not invent ids.
- Output a single raw JSON object ONLY: no markdown, no ```json code fences, no prose before or after. Escape every double-quote that appears inside a string value as \\".
""".strip()

QUERY_TERMS_SYSTEM_PROMPT = """
You turn a rumor/claim into effective web-search queries for a rumor-checking backend.
The raw user text is often a colloquial assertion, not good search input.

Return one JSON object with this schema:
{
  "entities": ["core subject entities: people, companies, orgs, places, products"],
  "keywords": ["the key actions/attributes being claimed"],
  "primary_query": "the single best search query string (entities + key action, 4-12 concise terms)",
  "aliases": ["alternate names / related terms that would surface the same event, if any"]
}

Rules:
- Identify the REAL subject. If the text says "京东开始造游轮", the subject is 京东/刘强东 and the
  action is 造/布局 游轮/邮轮 — the query must center on that subject, not generic "游轮".
- primary_query must be search terms, NOT the original sentence. Drop filler like 而且/早在/就打算.
- Include obvious aliases that help retrieval (brand names, parent company, person behind it).
- Output a single raw JSON object ONLY: no markdown, no ```json code fences, no prose before or after. Escape every double-quote that appears inside a string value as \\".
""".strip()


@dataclass(frozen=True)
class QueryTerms:
    entities: list[str]
    keywords: list[str]
    primary_query: str
    aliases: list[str]


@dataclass(frozen=True)
class AgentSynthesis:
    event: NormalizedEvent
    claim_extraction: ClaimExtraction
    verdict: VerdictEvaluation
    timeline: TimelineBuild
    possibilities: list[PossibilityItem] = field(default_factory=list)


@dataclass(frozen=True)
class InvestigationPlan:
    should_continue: bool
    follow_up_query: Optional[str]
    reason: str


@dataclass(frozen=True)
class NextActionPlan:
    next_action: str
    reason: str


@dataclass(frozen=True)
class ActionSequencePlan:
    """An ordered plan of intended actions the agent proposes at a branch point.

    The planner consumes this greedily while each head stays legal; the moment a
    proposed step is not in the current legal options the plan is discarded and a
    fresh one is requested. So the sequence is a forward-looking *intent*, never
    an authority that can bypass legal_actions."""

    actions: list[str]
    reason: str


# The action names the sequence planner is allowed to name. Deliberately just the
# LLM-decidable branch actions (mirrors planner._LLM_DECIDABLE) — kept as a local
# literal so the reasoner stays decoupled from the agent package. Anything outside
# this set in a proposed plan is dropped before the caller re-validates each head.
_KNOWN_ACTION_NAMES = frozenset(
    {"investigate", "fetch_url", "synthesize", "per_claim_search", "build_timeline"}
)


class LlmAgentReasoner:
    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        # Optional per-request model override (validated against the whitelist by
        # the caller). None means use the configured default.
        self.model_override: Optional[str] = None
        # Token usage callback: set by the runner to accumulate usage stats.
        # Called with (prompt_tokens, completion_tokens, total_tokens) after each
        # streamed completion. None means no tracking (standalone/test usage).
        self._on_token_usage: Optional[Any] = None

    @property
    def enabled(self) -> bool:
        return self.settings.analysis_provider == "kimi" and bool(self.settings.llm_api_key)

    def resolve_question(
        self,
        *,
        event: NormalizedEvent,
        retrieval_bundle: RetrievalBundle | None,
    ) -> Optional[QuestionResolution]:
        if not self.enabled:
            return None
        if event.input_type != "question_only" or retrieval_bundle is None or not retrieval_bundle.canonical_results:
            return None
        if is_broad_trend_question(event.raw_input):
            return None

        content = self._request_completion(
            stage_key="question_resolution",
            title="调用 Agent question resolution",
            system_prompt=QUESTION_RESOLUTION_SYSTEM_PROMPT,
            user_prompt=self._build_resolution_prompt(event=event, retrieval_bundle=retrieval_bundle),
        )
        payload = self._extract_json_payload(content)
        if payload is None:
            emit_log(
                stage_key="question_resolution",
                level="warning",
                title="Agent question resolution 无法解析",
                summary="LLM 返回内容不是可解析的 JSON。",
                details=[],
            )
            return None

        selected_result = self._result_by_id(
            retrieval_bundle=retrieval_bundle,
            result_id=self._clean_optional_string(payload.get("selected_result_id")),
        )
        if selected_result is None:
            return QuestionResolution(event=event, follow_up_query=None, selected_result=None)

        resolved_summary = self._clean_optional_string(payload.get("resolved_summary")) or selected_result.snippet or selected_result.title
        follow_up_query = self._normalize_follow_up_query(payload.get("follow_up_query"))
        resolved_event = event.model_copy(
            update={
                "title": selected_result.title,
                "summary": resolved_summary,
                "source_name": selected_result.source_name or event.source_name,
                "source_url": selected_result.url,
                "published_at": selected_result.published_at or event.published_at,
                "event_source": "retrieval_resolved",
            }
        )
        return QuestionResolution(
            event=resolved_event,
            follow_up_query=follow_up_query,
            selected_result=selected_result,
        )

    def synthesize(
        self,
        *,
        request: AnalyzeRequest,
        event: NormalizedEvent,
        retrieval_bundle: RetrievalBundle | None,
        fetched_bodies: Optional[dict[str, str]] = None,
    ) -> Optional[AgentSynthesis]:
        if not self.enabled:
            return None
        if retrieval_bundle is None or not retrieval_bundle.canonical_results:
            return None

        content = self._request_completion(
            stage_key="agent_synthesis",
            title="调用 Agent synthesis",
            system_prompt=CLAIMS_ONLY_SYSTEM_PROMPT,
            user_prompt=self._build_synthesis_prompt(
                request=request,
                event=event,
                retrieval_bundle=retrieval_bundle,
                fetched_bodies=fetched_bodies,
            ),
            # Retry a truncated/garbage completion instead of dropping the whole run
            # to the rule fallback: "usable" here means the same parser the code path
            # below relies on recovers an object carrying at least one claim.
            is_valid=self._synthesis_content_usable,
            # Synthesis emits the largest JSON and reasoning models spend a long CoT
            # before it (observed: 11k CoT chars + a partial body hitting the 200s
            # deadline). Give this one call more wall-clock so the body completes.
            timeout_multiplier=self.settings.llm_synthesis_timeout_multiplier,
            # Opt-in: route only synthesis to LLM_SYNTHESIS_MODEL (e.g. a reasoning
            # model that produces correct claim splits) while the short planner /
            # investigation calls stay on the fast default.
            model=self._synthesis_model(),
        )
        payload = self._extract_json_payload(content)
        if payload is None:
            emit_log(
                stage_key="agent_synthesis",
                level="warning",
                title="Agent synthesis 无法解析",
                summary="LLM 返回内容不是可解析的 JSON。",
                details=[],
            )
            return None

        result_map = {item.result_id: item for item in retrieval_bundle.canonical_results}
        synthesized_event = self._build_event(
            event=event,
            retrieval_bundle=retrieval_bundle,
            result_map=result_map,
            payload=payload.get("event"),
        )
        claim_results = self._build_claim_results(
            event=synthesized_event,
            result_map=result_map,
            claims_payload=payload.get("claims"),
        )
        if not claim_results:
            return None

        # Verify pass: a second LLM read checks each decisive verdict against its
        # OWN cited evidence and can only downgrade unfaithful calls to insufficient.
        # Purely subtractive, so it can never manufacture a stronger conclusion.
        claim_results, critic_downgraded_indices = self._critique_claim_results(claim_results)

        # Critic-triggered refinement: if the critic downgraded any claims, give
        # them one chance to re-verdict against the full evidence pool. This closes
        # the gap where the agent path had no recovery after a critic downgrade.
        claim_results = self._refine_after_critic(
            claim_results,
            downgraded_indices=critic_downgraded_indices,
            retrieval_bundle=retrieval_bundle,
            fetched_bodies=fetched_bodies,
        )

        # Structured number correction: for claims whose specific numbers/details
        # the evidence contradicts or refines, attach a {original, actual, source}
        # correction so the user sees the real figure, not just a bare "refuted".
        # Number-grounded (actual must appear in evidence) and degrades to no-op.
        claim_results = self._annotate_corrections(claim_results, retrieval_bundle, fetched_bodies)

        # Second-phase enrichment: produce timeline, scenarios, and refined event
        # in a SEPARATE lighter call to avoid the truncation the old all-in-one
        # prompt caused on V4-Flash. Degrades to empty timeline/scenarios on failure.
        try:
            enrichment = self._enrich_synthesis(
                request=request,
                event=synthesized_event,
                claim_results=claim_results,
                retrieval_bundle=retrieval_bundle,
                fetched_bodies=fetched_bodies,
                result_map=result_map,
            )
        except Exception as exc:
            logger.warning(
                "enrich_synthesis_failed error_type=%s error=%s",
                exc.__class__.__name__, str(exc)[:200],
            )
            enrichment = {"timeline_nodes": [], "possibilities": [], "event": None}

        evidence_source: EvidenceSourceType = "retrieval_mock" if retrieval_bundle.provider_name == "mock" else "retrieval_live"
        evidence_pool = retrieval_bundle.to_evidence_items()
        timeline_nodes = enrichment["timeline_nodes"]
        claim_items = [ClaimItem(claim=item.claim, claim_type=item.claim_type) for item in claim_results]
        timeline_source = "retrieval" if timeline_nodes else "none"
        possibilities = enrichment["possibilities"]
        final_event = enrichment["event"] or synthesized_event
        return AgentSynthesis(
            event=final_event,
            claim_extraction=ClaimExtraction(
                claims=claim_items,
                source="provider",
                query_hints={},
            ),
            verdict=VerdictEvaluation(
                claim_results=claim_results,
                evidence=evidence_pool,
                evidence_grade=retrieval_bundle.evidence_grade,
                evidence_source=evidence_source,
            ),
            timeline=TimelineBuild(
                nodes=timeline_nodes,
                source=timeline_source,
                completeness=self._timeline_completeness(timeline_nodes),
                confidence=self._timeline_confidence(retrieval_bundle, timeline_nodes),
            ),
            possibilities=possibilities,
        )

    def plan_investigation(
        self,
        *,
        event: NormalizedEvent,
        retrieval_bundle: RetrievalBundle | None,
        round_index: int,
    ) -> Optional[InvestigationPlan]:
        if not self.enabled or retrieval_bundle is None:
            return None

        content = self._request_completion(
            stage_key="investigation_plan",
            title="调用 Agent investigation planner",
            system_prompt=INVESTIGATION_PLAN_SYSTEM_PROMPT,
            user_prompt=self._build_investigation_prompt(
                event=event,
                retrieval_bundle=retrieval_bundle,
                round_index=round_index,
            ),
            is_valid=self._json_with_key_usable("should_continue"),
        )
        payload = self._extract_json_payload(content)
        if payload is None:
            emit_log(
                stage_key="investigation_plan",
                level="warning",
                title="Agent investigation planner 无法解析",
                summary="LLM 返回内容不是可解析的 JSON。",
                details=[],
            )
            return None

        follow_up_query = self._normalize_follow_up_query(payload.get("follow_up_query"))
        should_continue = bool(payload.get("should_continue")) and follow_up_query is not None
        reason = self._clean_optional_string(payload.get("reason")) or "planner 未给出理由。"
        return InvestigationPlan(
            should_continue=should_continue,
            follow_up_query=follow_up_query if should_continue else None,
            reason=reason,
        )

    def plan_next_action(
        self,
        *,
        evidence_snapshot: dict[str, Any],
        allowed_actions: list[str],
    ) -> Optional[NextActionPlan]:
        if not self.enabled or not allowed_actions:
            return None

        content = self._request_completion(
            stage_key="agent_planner",
            title="调用 Agent action planner",
            system_prompt=NEXT_ACTION_SYSTEM_PROMPT,
            user_prompt=(
                "Choose the single best next action from allowed_actions.\n"
                "Context JSON:\n"
                f"{json.dumps({'allowed_actions': allowed_actions, 'evidence_snapshot': evidence_snapshot}, ensure_ascii=False, indent=2)}"
            ),
            is_valid=self._json_with_key_usable("next_action"),
        )
        payload = self._extract_json_payload(content)
        if payload is None:
            emit_log(
                stage_key="agent_planner",
                level="warning",
                title="Agent action planner 无法解析",
                summary="LLM 返回内容不是可解析的 JSON。",
                details=[],
            )
            return None

        next_action = self._clean_optional_string(payload.get("next_action"))
        if next_action not in allowed_actions:
            emit_log(
                stage_key="agent_planner",
                level="warning",
                title="Agent action planner 返回非法动作",
                summary="planner 选择的动作不在允许列表内，退回规则 planner。",
                details=[f"next_action={next_action}", f"allowed={','.join(allowed_actions)}"],
            )
            return None
        reason = self._clean_optional_string(payload.get("reason")) or "planner 未给出理由。"
        return NextActionPlan(next_action=next_action, reason=reason)

    def plan_action_sequence(
        self,
        *,
        evidence_snapshot: dict[str, Any],
        allowed_actions: list[str],
    ) -> Optional[ActionSequencePlan]:
        """Propose an ordered plan of intended actions at a branch point.

        Returns None when disabled/unparseable or when the proposed head is not a
        legal action, so the caller falls back to its single-step / rule path. Only
        keeps proposed steps drawn from allowed_actions (the planner may name later
        steps that aren't legal yet — e.g. synthesize after investigate — so we keep
        the whole known-action prefix and let the caller re-validate each head)."""
        if not self.enabled or not allowed_actions:
            return None

        content = self._request_completion(
            stage_key="agent_planner",
            title="调用 Agent action sequence planner",
            system_prompt=NEXT_ACTION_SEQUENCE_SYSTEM_PROMPT,
            user_prompt=(
                "Propose the ordered sequence of actions you intend to take next.\n"
                "Context JSON:\n"
                f"{json.dumps({'allowed_actions': allowed_actions, 'evidence_snapshot': evidence_snapshot}, ensure_ascii=False, indent=2)}"
            ),
            is_valid=self._json_with_key_usable("actions"),
        )
        payload = self._extract_json_payload(content)
        if payload is None:
            emit_log(
                stage_key="agent_planner",
                level="warning",
                title="Agent sequence planner 无法解析",
                summary="LLM 返回内容不是可解析的 JSON。",
                details=[],
            )
            return None

        raw_actions = payload.get("actions")
        if not isinstance(raw_actions, list):
            return None
        # Keep only recognized action names, in order, de-duplicated. The full
        # dispatch vocabulary is valid to plan (a later step like synthesize is not
        # in allowed_actions *yet* but becomes legal after the earlier steps run);
        # the caller re-checks each head against legal_actions before running it.
        known = _KNOWN_ACTION_NAMES
        actions: list[str] = []
        for item in raw_actions:
            name = self._clean_optional_string(item)
            if name in known and name not in actions:
                actions.append(name)
        if not actions or actions[0] not in allowed_actions:
            emit_log(
                stage_key="agent_planner",
                level="warning",
                title="Agent sequence planner 首步非法",
                summary="计划首步不在允许列表内，退回单步/规则 planner。",
                details=[f"actions={','.join(actions) or 'none'}", f"allowed={','.join(allowed_actions)}"],
            )
            return None
        reason = self._clean_optional_string(payload.get("reason")) or "planner 未给出理由。"
        return ActionSequencePlan(actions=actions, reason=reason)

    def extract_query_terms(self, *, event: NormalizedEvent) -> Optional[QueryTerms]:
        """Turn a colloquial claim into entity-focused search terms.

        Returns None when disabled or unparseable, so callers fall back to the
        rule-based query builder (off+mock path is unaffected).
        """
        if not self.enabled:
            return None

        raw = " ".join(filter(None, [event.title, event.summary, event.raw_input])).strip()
        if not raw:
            return None

        content = self._request_completion(
            stage_key="retrieval_initial",
            title="调用 Agent query 抽取",
            system_prompt=QUERY_TERMS_SYSTEM_PROMPT,
            user_prompt=(
                "Extract search entities/keywords and the best query for this claim.\n"
                "Context JSON:\n"
                f"{json.dumps({'raw_input': event.raw_input, 'title': event.title, 'summary': event.summary}, ensure_ascii=False, indent=2)}"
            ),
        )
        payload = self._extract_json_payload(content)
        if payload is None:
            return None

        entities = self._normalize_string_list(payload.get("entities"))
        keywords = self._normalize_string_list(payload.get("keywords"))
        aliases = self._normalize_string_list(payload.get("aliases"))
        primary_query = self._clean_optional_string(payload.get("primary_query")) or " ".join(
            [*entities, *keywords][:8]
        )
        if not primary_query:
            return None
        return QueryTerms(entities=entities, keywords=keywords, primary_query=primary_query, aliases=aliases)

    def _request_completion(
        self,
        *,
        stage_key: str,
        title: str,
        system_prompt: str,
        user_prompt: str,
        is_valid: Optional[Any] = None,
        timeout_multiplier: float = 1.0,
        model: Optional[str] = None,
    ) -> str:
        model = model or self._reasoning_model()
        endpoint = f"{self.settings.base_url_for_model(model)}/chat/completions"
        # An empty completion is always retryable — the caller can't parse it either
        # way — and empties happen to BOTH families on this gateway: reasoning models
        # stall when the chain-of-thought never terminates, and even fast models time
        # out mid-answer on the heavy synthesis prompt (observed: 249 chars then a
        # read-timeout, then 0 chars). So retry regardless of model type; a run that
        # returns content on the first try still costs exactly one call.
        #
        # `is_valid` lets a caller also retry a NON-empty but unusable completion —
        # e.g. synthesis returning a truncated JSON fragment (`{"event":{..."summary":"拼`)
        # that the parser then rejects. Without this, the truthy fragment breaks the
        # loop, fails to parse, and drops the whole run to the rule fallback. When no
        # validator is supplied we keep the original "retry only when empty" behavior.
        attempts = self.settings.llm_reasoning_retries + 1
        content = ""
        for attempt in range(1, attempts + 1):
            attempt_title = title if attempt == 1 else f"{title}（重试 {attempt - 1}）"
            emit_api_call(
                stage_key=stage_key,
                call_type="llm",
                status="running",
                title=attempt_title,
                summary="正在调用 LLM chat/completions（streaming）。",
                details=[
                    f"model={model}",
                    f"attempt={attempt}/{attempts}",
                    f"system={_full_text(system_prompt)}",
                    f"prompt={_full_text(user_prompt)}",
                ],
            )
            content = self._stream_completion(
                endpoint=endpoint,
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                timeout_multiplier=timeout_multiplier,
            )
            # Two distinct notions, kept separate so the trace never overclaims:
            #  - `retry`: does the loop try again? (only empties, or a failed
            #    validator, are retried.)
            #  - `outcome`: what actually happened, truthfully. Without a validator
            #    the loop can't judge usability, so it reports "unchecked", NOT
            #    "accepted" — the caller's own parser is the real judge downstream.
            if not content:
                outcome, retry = "empty", True
            elif is_valid is None:
                outcome, retry = "unchecked", False
            elif is_valid(content):
                outcome, retry = "accepted", False
            else:
                outcome, retry = "unparseable", True
            outcome_label = {
                "empty": "空返回",
                "unchecked": "原样采用（未做解析校验）",
                "accepted": "校验通过",
                "unparseable": "无法解析",
            }[outcome]
            emit_api_call(
                stage_key=stage_key,
                call_type="llm",
                status="warning" if retry else "completed",
                title=f"{attempt_title} 返回",
                summary=(
                    f"本次返回不可用（{outcome_label}），{'将重试。' if attempt < attempts else '已达重试上限。'}"
                    if retry
                    else "LLM 已返回流式响应。"
                ),
                details=[
                    f"model={model}",
                    f"content_chars={len(content)}",
                    f"outcome={outcome_label}",
                    f"response={_full_text(content)}",
                ],
            )
            if not retry:
                break
            logger.warning(
                "llm_bad_completion model=%s attempt=%s/%s stage=%s reason=%s chars=%s",
                model, attempt, attempts, stage_key, outcome, len(content),
            )
        return content

    def _stream_completion(
        self, *, endpoint: str, model: str, system_prompt: str, user_prompt: str, timeout_multiplier: float = 1.0
    ) -> str:
        """Read an OpenAI-compatible SSE stream and return the concatenated answer.

        Streaming (not one-shot) because some gateway models only behave correctly
        under stream=true; others stream fine too, so we always stream.

        Two model families need different handling:

        - **Fast models**: a modest token budget and the short provider timeout.
          They answer immediately. We do NOT pin response_format=json_object:
          measured on this gateway, json_object pushes V4-Flash's first token from
          ~1s to ~21s and makes it slow-trickle until the wall-clock deadline cuts
          it off mid-JSON (the truncated-synthesis + truncated-planner failure).
          Prompts already instruct "output JSON only" and the lenient parser
          recovers a fenced/sliced block, so the constraint bought nothing but the
          stall.
        - **Reasoning models**: emit a long chain-of-thought in `reasoning_content`
          BEFORE any `content` (observed: 124s of CoT, then a clean ```json answer,
          finish=stop). They need a large token budget (else the CoT eats it and no
          answer is ever produced) and a long timeout, and must NOT be pinned to
          json_object — that makes them stall indefinitely with zero output.

        Regardless of family we keep a client-side character budget + wall-clock
        deadline (httpx's timeout is only an inter-chunk gap, so it can't bound a
        stream that keeps trickling) and, on ReadTimeout, return whatever content
        arrived so the caller's lenient parser can still try to recover it.
        """
        is_reasoning = self.settings.is_reasoning_model(model)
        max_tokens = self.settings.llm_reasoning_max_tokens if is_reasoning else self.settings.llm_max_tokens
        base_timeout = (
            self.settings.llm_reasoning_timeout_seconds if is_reasoning else self.settings.provider_timeout_seconds
        )
        # Synthesis is the one heavy call — a long chain-of-thought (observed 11k+
        # chars) can eat the base deadline before the JSON body is complete — so its
        # caller passes a >1 multiplier to give it more wall-clock without slowing the
        # short planner/investigation calls (which keep multiplier 1.0).
        timeout_seconds = base_timeout * (timeout_multiplier if timeout_multiplier > 0 else 1.0)
        body: dict[str, Any] = {
            "model": model,
            "temperature": self._request_temperature(model),
            "stream": True,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        # No response_format=json_object for EITHER family: it stalls reasoning
        # models into zero output, and on this gateway it also makes fast models
        # slow-trickle to the deadline and truncate. Both are prompted to "output
        # JSON only" and the caller's lenient parser recovers a fenced/sliced block.

        parts: list[str] = []
        char_budget = max_tokens * _STREAM_CHARS_PER_TOKEN
        deadline = time.monotonic() + timeout_seconds
        collected = 0
        reasoning_chars = 0
        truncated = False
        usage_data: Optional[dict] = None
        try:
            with httpx.stream(
                "POST",
                endpoint,
                headers={
                    "Authorization": f"Bearer {self.settings.llm_api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=timeout_seconds,
            ) as response:
                response.raise_for_status()
                for raw_line in response.iter_lines():
                    if collected >= char_budget or time.monotonic() >= deadline:
                        truncated = True
                        break
                    if not raw_line:
                        continue
                    line = raw_line.strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if not data or data == "[DONE]":
                        if data == "[DONE]":
                            break
                        continue
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    # Capture usage from the final chunk (OpenAI SSE format).
                    chunk_usage = chunk.get("usage")
                    if isinstance(chunk_usage, dict):
                        usage_data = chunk_usage
                    choices = chunk.get("choices") or [{}]
                    delta = choices[0].get("delta") or {}
                    piece = delta.get("content")
                    if isinstance(piece, str):
                        parts.append(piece)
                        collected += len(piece)
                    # Reasoning tokens don't count toward the answer, but they do
                    # count toward the runaway budget so a CoT that never terminates
                    # still gets cut off.
                    thought = delta.get("reasoning_content")
                    if isinstance(thought, str):
                        reasoning_chars += len(thought)
                        collected += len(thought)
        except httpx.ReadTimeout:
            truncated = True
            logger.warning(
                "llm_stream_read_timeout model=%s content_chars=%s reasoning_chars=%s",
                model,
                len("".join(parts)),
                reasoning_chars,
            )
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            logger.warning(
                "llm_stream_network_error model=%s error_type=%s error=%s",
                model, type(exc).__name__, str(exc)[:200],
            )
            return ""
        if truncated:
            logger.warning(
                "llm_stream_truncated model=%s reasoning=%s content_chars=%s reasoning_chars=%s char_budget=%s",
                model,
                is_reasoning,
                len("".join(parts)),
                reasoning_chars,
                char_budget,
            )
        # Report token usage to the runner (if callback is set).
        if usage_data and self._on_token_usage:
            try:
                self._on_token_usage(
                    usage_data.get("prompt_tokens", 0),
                    usage_data.get("completion_tokens", 0),
                    usage_data.get("total_tokens", 0),
                )
            except Exception:
                pass
        return "".join(parts).strip()

    def _reasoning_model(self) -> str:
        if self.model_override:
            return self.model_override
        return self.settings.llm_search_model.strip() or self.settings.llm_model.strip()

    def _synthesis_model(self) -> str:
        """Model for the one heavy synthesis call. A per-request picker override
        always wins. Otherwise, if LLM_SYNTHESIS_MODEL is set, synthesis routes
        there (opt-in — typically a slower reasoning model that produces correct
        claim splits) while planner/investigation stay on the fast default. Unset
        keeps synthesis on the same model as everything else."""
        if self.model_override:
            return self.model_override
        return self.settings.llm_synthesis_model.strip() or self._reasoning_model()

    def _request_temperature(self, model: str) -> float:
        return self.settings.llm_temperature

    def _build_resolution_prompt(self, *, event: NormalizedEvent, retrieval_bundle: RetrievalBundle) -> str:
        context = {
            "question": event.raw_input,
            "input_type": event.input_type,
            "current_summary": event.summary,
            "retrieval_query": retrieval_bundle.query,
            "retrieval_hits": [self._serialize_result(item) for item in retrieval_bundle.canonical_results[:6]],
        }
        return (
            "Choose a stable single-event anchor only if one retrieval hit clearly matches the same incident.\n"
            "If the hits are mixed, keep selected_result_id null.\n"
            "Context JSON:\n"
            f"{json.dumps(context, ensure_ascii=False, indent=2)}"
        )

    def _build_synthesis_prompt(
        self,
        *,
        request: AnalyzeRequest,
        event: NormalizedEvent,
        retrieval_bundle: RetrievalBundle,
        fetched_bodies: Optional[dict[str, str]] = None,
    ) -> str:
        context = {
            "raw_input": request.raw_input,
            "input_type": event.input_type,
            "event_hint": {
                "title": event.title,
                "summary": event.summary,
                "source_name": event.source_name,
                "source_url": event.source_url,
                "published_at": event.published_at,
                "event_source": event.event_source,
            },
            "retrieval_query": retrieval_bundle.query,
            "retrieval_provider": retrieval_bundle.provider_name,
            "evidence_grade_hint": retrieval_bundle.evidence_grade,
            "retrieval_hits": [self._serialize_result(item) for item in retrieval_bundle.canonical_results[:8]],
        }
        if fetched_bodies:
            _html_tag = re.compile(r"<[^>]+>")
            _ws = re.compile(r"\s+")

            def _clean_body(body: str) -> str:
                text = _html_tag.sub(" ", body)
                text = _ws.sub(" ", text).strip()
                return text[:2000]

            context["fetched_full_text"] = [
                {"result_id": rid, "full_text": _clean_body(body)}
                for rid, body in fetched_bodies.items()
                if body.strip()
            ]
        note = (
            "Some hits include fetched_full_text (full page body). Use it as stronger grounding, "
            "but still cite that hit by its existing result_id in evidence_result_ids.\n"
            if fetched_bodies
            else ""
        )
        return (
            "Produce an evidence-grounded event summary, atomic claims, verdicts, and timeline nodes.\n"
            "Do not force a single person if the supplied hits only support a broader recent pattern.\n"
            f"{note}"
            "Context JSON:\n"
            f"{json.dumps(context, ensure_ascii=False, indent=2)}"
        )

    def _serialize_result(self, result: SearchResult) -> dict[str, Any]:
        return {
            "result_id": result.result_id,
            "title": result.title,
            "url": result.url,
            "source_name": result.source_name,
            "published_at": result.published_at,
            "snippet": result.snippet,
            "source_tier": result.source_tier,
            "source_category": result.effective_source_category,
            "query_label": result.query_label,
        }

    def _build_investigation_prompt(
        self,
        *,
        event: NormalizedEvent,
        retrieval_bundle: RetrievalBundle,
        round_index: int,
    ) -> str:
        context = {
            "round_index": round_index,
            "event_hint": {
                "title": event.title,
                "summary": event.summary,
                "input_type": event.input_type,
            },
            "current_query": retrieval_bundle.query,
            "evidence_snapshot": {
                "evidence_grade": retrieval_bundle.evidence_grade,
                "canonical_result_count": len(retrieval_bundle.canonical_results),
                "high_trust_result_count": retrieval_bundle.high_trust_result_count,
                "independent_source_count": retrieval_bundle.independent_source_count,
                "independent_high_trust_source_count": retrieval_bundle.independent_high_trust_source_count,
                "official_result_count": retrieval_bundle.official_result_count,
                "conflict_signals": list(retrieval_bundle.conflict_signals),
            },
            "top_hits": [self._serialize_result(item) for item in retrieval_bundle.canonical_results[:5]],
        }
        return (
            "Decide whether one more targeted retrieval round is worth running to strengthen this evidence base.\n"
            "Only continue when a sharper query could plausibly close a real gap.\n"
            "Context JSON:\n"
            f"{json.dumps(context, ensure_ascii=False, indent=2)}"
        )

    def _build_event(
        self,
        *,
        event: NormalizedEvent,
        retrieval_bundle: RetrievalBundle,
        result_map: dict[str, SearchResult],
        payload: Any,
    ) -> NormalizedEvent:
        raw_event = payload if isinstance(payload, dict) else {}
        anchor_result = self._result_by_id(
            retrieval_bundle=retrieval_bundle,
            result_id=self._clean_optional_string(raw_event.get("anchor_result_id")),
        )
        title = self._clean_optional_string(raw_event.get("title")) or event.title or self._fallback_title(anchor_result)
        summary = self._clean_optional_string(raw_event.get("summary")) or event.summary
        source_name = self._clean_optional_string(raw_event.get("source_name"))
        published_at = self._clean_optional_string(raw_event.get("published_at"))

        if anchor_result is not None:
            source_name = source_name or anchor_result.source_name
            published_at = published_at or anchor_result.published_at
            source_url = anchor_result.url
        else:
            source_name = source_name or event.source_name or default_source_name(event.input_type)
            source_url = event.source_url or default_source_url(event.input_type, event.raw_input)
            published_at = published_at or event.published_at

        return event.model_copy(
            update={
                "title": title,
                "summary": summary,
                "source_name": source_name,
                "source_url": source_url,
                "published_at": ensure_datetime_string(published_at),
                "event_source": "retrieval_resolved",
            }
        )

    def _build_claim_results(
        self,
        *,
        event: NormalizedEvent,
        result_map: dict[str, SearchResult],
        claims_payload: Any,
    ) -> list[ClaimResult]:
        if not isinstance(claims_payload, list):
            return []

        claim_results: list[ClaimResult] = []
        seen_claims: set[str] = set()
        for item in claims_payload:
            if not isinstance(item, dict):
                continue
            claim_text = self._normalize_claim_text(item.get("claim"))
            if not claim_text:
                continue
            claim_key = re.sub(r"[\s，。！？?!；;:：]", "", claim_text).lower()
            if claim_key in seen_claims:
                continue

            claim_type = self._normalize_claim_type(item.get("claim_type"))
            verdict = self._normalize_verdict(item.get("verdict"))
            confidence = self._normalize_confidence(item.get("confidence"))
            notes = self._clean_optional_string(item.get("notes")) or self._default_note(verdict=verdict, claim_type=claim_type)
            evidence_ids = self._normalize_string_list(item.get("evidence_result_ids"))
            selected_evidence = self._evidence_from_ids(
                result_map=result_map,
                evidence_ids=evidence_ids,
                verdict=verdict,
            )
            if verdict != "insufficient" and not selected_evidence:
                verdict = "insufficient"
                confidence = "low"
                notes = "Agent did not provide grounded evidence ids for a decisive verdict."
            verdict, confidence, notes = self._guard_overbroad_claim_verdict(
                claim_text=claim_text,
                verdict=verdict,
                confidence=confidence,
                notes=notes,
                evidence=selected_evidence,
            )
            truth_probability, probability_basis = self._normalize_probability(
                item.get("truth_probability"),
                item.get("probability_basis"),
                has_evidence=bool(selected_evidence),
            )

            claim_results.append(
                ClaimResult(
                    claim=claim_text,
                    claim_type=claim_type,
                    verdict=verdict,
                    confidence=confidence,
                    truth_probability=truth_probability,
                    probability_basis=probability_basis,
                    evidence=selected_evidence,
                    notes=notes,
                )
            )
            seen_claims.add(claim_key)
            if len(claim_results) >= 6:
                break

        if not claim_results:
            claim_results.append(
                ClaimResult(
                    claim=self._normalize_claim_text(event.summary) or f"{event.summary.rstrip('。')}。",
                    claim_type="fact",
                    verdict="insufficient",
                    confidence="low",
                    evidence=[],
                    notes="Agent could not produce grounded atomic claims from the supplied retrieval hits.",
                )
            )
        return claim_results

    def _critique_claim_results(self, claim_results: list[ClaimResult]) -> tuple[list[ClaimResult], set[int]]:
        """Second-pass verify: re-check each decisive verdict against its own cited
        evidence and downgrade any the critic finds unfaithful to "insufficient".

        Monotonic by construction — the critic can ONLY downgrade, never upgrade —
        so a critic failure or garbage response can never strengthen a verdict.
        Returns (input unchanged, empty set) when disabled, when there is nothing
        decisive to check, or when the critic is unavailable/unparseable."""
        if not self.enabled or not self.settings.agent_synthesis_critic_enabled:
            return claim_results, set()

        # Only claims that make a decisive, evidence-backed assertion are worth
        # checking; insufficient/unsupported claims are already cautious.
        checkable = [
            (index, cr)
            for index, cr in enumerate(claim_results)
            if cr.verdict in {"supported", "refuted", "conflicting"} and cr.evidence
        ]
        if not checkable:
            return claim_results, set()

        payload_claims = [
            {
                "index": index,
                "claim": cr.claim,
                "verdict": cr.verdict,
                "evidence": [
                    {"title": ev.title, "snippet": ev.snippet, "source_name": ev.source_name}
                    for ev in cr.evidence
                ],
            }
            for index, cr in checkable
        ]

        content = self._request_completion(
            stage_key="agent_synthesis",
            title="调用 Agent synthesis critic",
            system_prompt=SYNTHESIS_CRITIC_SYSTEM_PROMPT,
            user_prompt=(
                "Verify each judged claim against its OWN cited evidence. "
                "Flag only the ones whose verdict the evidence does not justify.\n"
                "Judged claims JSON:\n"
                f"{json.dumps(payload_claims, ensure_ascii=False, indent=2)}"
            ),
            is_valid=self._json_with_key_usable("revisions"),
        )
        payload = self._extract_json_payload(content)
        if payload is None:
            emit_log(
                stage_key="agent_synthesis",
                level="warning",
                title="Synthesis critic 无法解析",
                summary="critic 返回不可解析，保留原判定。",
                details=[],
            )
            return claim_results, set()

        revisions = payload.get("revisions")
        if not isinstance(revisions, list):
            return claim_results, set()
        downgrade_indices = {
            int(item.get("index"))
            for item in revisions
            if isinstance(item, dict)
            and item.get("keep") is False
            and isinstance(item.get("index"), (int, float))
        }

        revised = list(claim_results)
        downgraded = 0
        for index, cr in checkable:
            if index not in downgrade_indices:
                continue
            reason = next(
                (
                    self._clean_optional_string(item.get("reason"))
                    for item in revisions
                    if isinstance(item, dict) and item.get("index") == index and item.get("keep") is False
                ),
                None,
            )
            note = cr.notes.rstrip("。")
            note = f"{note}。核查复检：cited 证据不足以支撑原判定，已下调为存疑。" if note else "核查复检：cited 证据不足以支撑原判定，已下调为存疑。"
            if reason:
                note = f"{note}（{reason}）"
            revised[index] = cr.model_copy(
                update={
                    "verdict": "insufficient",
                    "confidence": "low",
                    "notes": note,
                }
            )
            downgraded += 1

        emit_log(
            stage_key="agent_synthesis",
            title="Synthesis critic 完成",
            summary=(
                f"复检 {len(checkable)} 条决定性判定，下调 {downgraded} 条为存疑。"
                if downgraded
                else f"复检 {len(checkable)} 条决定性判定，全部与所引证据一致，无需下调。"
            ),
            details=[f"downgraded_indices={sorted(i for i in downgrade_indices if any(idx == i for idx, _ in checkable))}"],
        )
        return revised, downgrade_indices

    def _refine_after_critic(
        self,
        claim_results: list[ClaimResult],
        *,
        downgraded_indices: set[int],
        retrieval_bundle: RetrievalBundle,
        fetched_bodies: Optional[dict[str, str]],
    ) -> list[ClaimResult]:
        """Re-verdict claims that the critic downgraded, using the full evidence pool.

        The critic can only downgrade (monotonic); this gives downgraded claims ONE
        chance to find proper grounding in the full hit set rather than just their
        originally cited evidence. Returns input unchanged when nothing was downgraded
        or when the LLM call fails."""
        if not self.enabled:
            return claim_results
        downgraded = [
            (i, cr) for i, cr in enumerate(claim_results)
            if i in downgraded_indices
        ]
        if not downgraded:
            return claim_results

        result_map = {r.result_id: r for r in retrieval_bundle.canonical_results}
        hits_context = [self._serialize_result(r) for r in retrieval_bundle.canonical_results[:8]]
        claims_block = json.dumps(
            [{"index": i, "claim": cr.claim} for i, cr in downgraded],
            ensure_ascii=False, indent=2,
        )
        user_prompt = (
            "Re-judge ONLY the following claims that the critic flagged as lacking grounding.\n"
            "Use the full evidence pool below.\n\n"
            f"Flagged claims:\n{claims_block}\n\n"
            f"Full evidence pool:\n{json.dumps(hits_context, ensure_ascii=False, indent=2)}"
        )

        content = self._request_completion(
            stage_key="agent_synthesis",
            title="调用 Agent critic refinement",
            system_prompt=CRITIC_REFINE_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            is_valid=self._json_with_key_usable("refined_claims"),
        )
        payload = self._extract_json_payload(content)
        if payload is None:
            return claim_results

        refined_list = payload.get("refined_claims")
        if not isinstance(refined_list, list):
            return claim_results

        valid_indices = {i for i, _ in downgraded}
        revised = list(claim_results)
        refined_count = 0
        for item in refined_list:
            if not isinstance(item, dict):
                continue
            idx = item.get("index")
            if not isinstance(idx, (int, float)) or int(idx) not in valid_indices:
                continue
            idx = int(idx)
            verdict = self._normalize_verdict(item.get("verdict"))
            confidence = self._normalize_confidence(item.get("confidence"))
            evidence_ids = self._normalize_string_list(item.get("evidence_result_ids"))
            selected_evidence = self._evidence_from_ids(
                result_map=result_map, evidence_ids=evidence_ids, verdict=verdict,
            )
            if verdict != "insufficient" and not selected_evidence:
                continue
            notes = self._clean_optional_string(item.get("notes")) or revised[idx].notes
            revised[idx] = revised[idx].model_copy(
                update={
                    "verdict": verdict,
                    "confidence": confidence,
                    "evidence": selected_evidence or revised[idx].evidence,
                    "notes": notes,
                }
            )
            refined_count += 1

        if refined_count:
            emit_log(
                stage_key="agent_synthesis",
                title="Critic refinement 完成",
                summary=f"对 {len(downgraded)} 条被下调的 claim 重新判定，{refined_count} 条获得新 verdict。",
                details=[f"{revised[i].claim[:20]}→{revised[i].verdict}" for i, _ in downgraded],
            )
        return revised

    def _enrich_synthesis(
        self,
        *,
        request: AnalyzeRequest,
        event: NormalizedEvent,
        claim_results: list[ClaimResult],
        retrieval_bundle: RetrievalBundle,
        fetched_bodies: Optional[dict[str, str]],
        result_map: dict[str, SearchResult],
    ) -> dict[str, Any]:
        """Second-phase enrichment: timeline, scenarios, and event refinement.

        Run as a separate lighter LLM call AFTER claims are decided, so it cannot
        truncate and lose the claims. Degrades to empty timeline/scenarios on failure,
        which is acceptable (the verdict is the core product)."""
        empty: dict[str, Any] = {"timeline_nodes": [], "possibilities": [], "event": None}

        claims_summary = json.dumps(
            [{"claim": cr.claim, "verdict": cr.verdict} for cr in claim_results],
            ensure_ascii=False,
        )
        hits_context = [self._serialize_result(r) for r in retrieval_bundle.canonical_results[:8]]
        context = {
            "raw_input": request.raw_input,
            "event_title": event.title,
            "event_summary": event.summary,
            "claims_and_verdicts": claims_summary,
            "retrieval_hits": hits_context,
        }
        user_prompt = (
            "Produce timeline, scenarios, and a refined event title/summary.\n"
            "Context JSON:\n"
            f"{json.dumps(context, ensure_ascii=False, indent=2)}"
        )

        content = self._request_completion(
            stage_key="agent_synthesis",
            title="调用 Agent enrichment (timeline/scenarios)",
            system_prompt=ENRICHMENT_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
        payload = self._extract_json_payload(content)
        if payload is None:
            emit_log(
                stage_key="agent_synthesis",
                level="warning",
                title="Agent enrichment 无法解析",
                summary="enrichment 返回不可解析，跳过 timeline/scenarios。",
                details=[],
            )
            return empty

        timeline_nodes = self._build_timeline_nodes(
            result_map=result_map,
            timeline_payload=payload.get("timeline"),
        )
        possibilities = self._build_scenarios(payload.get("scenarios"))

        refined_event = None
        raw_event = payload.get("event")
        if isinstance(raw_event, dict):
            title = self._clean_optional_string(raw_event.get("title"))
            summary = self._clean_optional_string(raw_event.get("summary"))
            if title or summary:
                refined_event = event.model_copy(
                    update={
                        k: v for k, v in [("title", title), ("summary", summary)] if v
                    }
                )

        enriched = {
            "timeline_nodes": timeline_nodes,
            "possibilities": possibilities,
            "event": refined_event,
        }
        if timeline_nodes or possibilities:
            emit_log(
                stage_key="agent_synthesis",
                title="Agent enrichment 完成",
                summary=(
                    f"timeline={len(timeline_nodes)} nodes, scenarios={len(possibilities)} items"
                    + (", event title refined" if refined_event else "")
                ),
                details=[],
            )
        return enriched

    def _annotate_corrections(
        self,
        claim_results: list[ClaimResult],
        retrieval_bundle: RetrievalBundle | None,
        fetched_bodies: Optional[dict[str, str]],
    ) -> list[ClaimResult]:
        """Attach structured number corrections to synthesized claims.

        The fixed pipeline already runs this on its rule verdicts (verdict_engine);
        the agent path builds verdicts inside synthesize and would otherwise skip it,
        leaving `refuted`/`insufficient` numeric claims with no real figure attached.
        Number-grounded and degrades to a no-op on any failure, so it is safe to run
        unconditionally. Returns the input unchanged when there is nothing to ground."""
        if not self.enabled or retrieval_bundle is None:
            return claim_results
        all_titles = [
            r.title for r in retrieval_bundle.canonical_results if r.title.strip()
        ]

        def _complete(system_prompt: str, user_prompt: str) -> str:
            # Route correction through the same retry/streaming layer synthesis uses,
            # instead of claim_correction's bare one-shot POST. The default fast model
            # (DeepSeek-V4-Flash) read-times-out on this gateway; the reasoning default
            # completes reliably. Returns "" on failure so annotate degrades to no-op.
            return self._request_completion(
                stage_key="agent_synthesis",
                title="调用数字纠正",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )

        try:
            annotated = annotate_claim_corrections(
                claim_results,
                page_bodies=fetched_bodies,
                all_evidence_titles=all_titles,
                completion_fn=_complete,
            )
        except Exception as exc:  # pragma: no cover - defensive; annotate already guards
            logger.debug("agent-path claim correction failed: %s", exc)
            return claim_results
        corrected = sum(1 for cr in annotated if cr.correction)
        if corrected:
            emit_log(
                stage_key="agent_synthesis",
                title="数字纠正完成",
                summary=f"为 {corrected} 条 claim 附上了证据支持的正确数字/细节。",
                details=[
                    f"{cr.correction.get('original', '')}→{cr.correction.get('actual', '')}"
                    for cr in annotated
                    if cr.correction
                ][:6],
            )
        return annotated

    def _guard_overbroad_claim_verdict(
        self,
        *,
        claim_text: str,
        verdict: str,
        confidence: str,
        notes: str,
        evidence: list[SearchResult],
    ) -> tuple[str, str, str]:
        # Backstop only. The SYNTHESIS prompt's scope/quantifier rule is the
        # primary defense (the LLM has the semantics to judge "all X are Y");
        # this catches the case where the model ignores that rule and marks an
        # absolute-scope claim `supported` without full-scope evidence.
        if verdict != "supported" or not self._looks_absolute_claim(claim_text):
            return verdict, confidence, notes
        evidence_text = " ".join(
            item for item in [*(result.title for result in evidence), *(result.snippet for result in evidence)] if item
        )
        if self._evidence_covers_absolute_scope(evidence_text):
            return verdict, confidence, notes
        guarded_note = (
            notes.rstrip("。")
            + "。但该 claim 使用了‘都是/全部/仅’等绝对化范围，当前证据只支持部分相关岗位或事实，不能支持绝对化表述。"
        )
        return "insufficient", "low", guarded_note

    def _looks_absolute_claim(self, claim_text: str) -> bool:
        return any(token in claim_text for token in ("都是", "全是", "全部", "全都", "仅", "只招", "清一色"))

    def _evidence_covers_absolute_scope(self, evidence_text: str) -> bool:
        if not evidence_text:
            return False
        return any(token in evidence_text for token in ("均为", "全部为", "全为", "都是", "仅招聘", "只招聘"))

    def _build_timeline_nodes(
        self,
        *,
        result_map: dict[str, SearchResult],
        timeline_payload: Any,
    ) -> list[TimelineNode]:
        if not isinstance(timeline_payload, list):
            return []

        nodes: list[TimelineNode] = []
        used_result_ids: set[str] = set()
        for item in timeline_payload:
            if not isinstance(item, dict):
                continue
            node_type = self._normalize_timeline_type(item.get("node_type"))
            result_id = self._clean_optional_string(item.get("result_id"))
            if not result_id or result_id in used_result_ids:
                continue
            result = result_map.get(result_id)
            if result is None:
                continue
            used_result_ids.add(result_id)
            nodes.append(
                TimelineNode(
                    node_type=node_type,
                    title=result.title,
                    url=result.url,
                    source_name=result.source_name,
                    published_at=ensure_datetime_string(result.published_at),
                    summary=self._clean_optional_string(item.get("summary")) or result.snippet,
                    why_selected=self._clean_optional_string(item.get("why_selected")) or "Agent selected this retrieval hit as a timeline node.",
                )
            )
            if len(nodes) >= 5:
                break
        nodes.sort(key=lambda item: (item.published_at, item.node_type))
        return nodes

    def _timeline_completeness(self, nodes: list[TimelineNode]) -> int:
        weights = {
            "origin": 30,
            "amplification": 15,
            "peak": 15,
            "turn": 20,
            "clarification": 20,
        }
        return min(sum(weights.get(item.node_type, 0) for item in nodes), 100)

    def _timeline_confidence(self, retrieval_bundle: RetrievalBundle, nodes: list[TimelineNode]) -> int:
        if not nodes:
            return 0
        confidence = 30
        confidence += min(len(nodes) * 10, 30)
        confidence += min(retrieval_bundle.high_trust_result_count * 8, 24)
        confidence += min(retrieval_bundle.independent_source_count * 4, 16)
        return min(confidence, 100)

    def _evidence_from_ids(
        self,
        *,
        result_map: dict[str, SearchResult],
        evidence_ids: list[str],
        verdict: str,
    ) -> list:
        items = []
        for result_id in evidence_ids:
            result = result_map.get(result_id)
            if result is None:
                continue
            items.append(
                result.to_evidence(
                    relevance_reason=self._evidence_reason(verdict),
                )
            )
            if len(items) >= 2:
                break
        return items

    def _evidence_reason(self, verdict: str) -> str:
        if verdict == "supported":
            return "Agent matched this hit as supporting evidence for the claim."
        if verdict == "refuted":
            return "Agent matched this hit as refuting evidence for the claim."
        if verdict == "conflicting":
            return "Agent matched this hit as part of a conflicting evidence set."
        return "Agent considered this hit relevant but not decisive."

    def _default_note(self, *, verdict: str, claim_type: str) -> str:
        if claim_type == "opinion":
            return "This is an opinion-like statement and remains non-decidable."
        if claim_type == "prediction":
            return "This is a forward-looking statement and remains non-decidable."
        if claim_type == "unverifiable":
            return "This statement is not directly verifiable from public sources."
        if verdict == "supported":
            return "Agent found grounded support in the supplied retrieval hits."
        if verdict == "refuted":
            return "Agent found grounded refutation in the supplied retrieval hits."
        if verdict == "conflicting":
            return "Agent found conflicting grounded evidence across the supplied hits."
        return "Agent could not reach a grounded decisive verdict from the supplied hits."

    def _fallback_title(self, anchor_result: SearchResult | None) -> Optional[str]:
        if anchor_result is None:
            return None
        return anchor_result.title

    def _normalize_follow_up_query(self, value: Any) -> Optional[str]:
        cleaned = self._clean_optional_string(value)
        if not cleaned:
            return None
        tokens = re.findall(r"[A-Za-z0-9%._-]{2,}|[\u4e00-\u9fff]{2,16}", cleaned)
        if not tokens:
            return None
        return " ".join(tokens[:10])

    def _normalize_claim_type(self, value: Any) -> str:
        cleaned = self._clean_optional_string(value)
        if cleaned in ALLOWED_CLAIM_TYPES:
            return cleaned
        return "fact"

    def _normalize_verdict(self, value: Any) -> str:
        cleaned = self._clean_optional_string(value)
        if cleaned in ALLOWED_VERDICTS:
            return cleaned
        return "insufficient"

    def _normalize_confidence(self, value: Any) -> ConfidenceValue:
        cleaned = self._clean_optional_string(value)
        if cleaned in ALLOWED_CONFIDENCE:
            return cleaned
        return "low"

    def _clamp_probability(self, value: Any) -> Optional[float]:
        if isinstance(value, bool):
            return None
        if not isinstance(value, (int, float)):
            cleaned = self._clean_optional_string(value)
            if cleaned is None:
                return None
            try:
                value = float(cleaned.rstrip("%"))
            except ValueError:
                return None
        return max(0.0, min(100.0, float(value)))

    def _normalize_probability_basis(self, value: Any, *, has_evidence: bool) -> str:
        cleaned = self._clean_optional_string(value)
        if cleaned in {"evidence", "prior"}:
            # Never let the model claim "evidence" basis when nothing grounded it —
            # keeps the probability honest about where the number came from.
            if cleaned == "evidence" and not has_evidence:
                return "prior"
            return cleaned
        return "evidence" if has_evidence else "prior"

    def _normalize_probability(
        self, raw_probability: Any, raw_basis: Any, *, has_evidence: bool
    ) -> tuple[Optional[float], Optional[str]]:
        probability = self._clamp_probability(raw_probability)
        if probability is None:
            return None, None
        basis = self._normalize_probability_basis(raw_basis, has_evidence=has_evidence)
        return probability, basis

    def _build_scenarios(self, scenarios_payload: Any) -> list[PossibilityItem]:
        """Parse the LLM's mutually-exclusive whole-message scenarios into
        PossibilityItem, clamping probabilities and renormalizing to ~100 when the
        model's numbers drift. Returns [] when nothing parseable, so the caller
        falls back to the rule-based possibilities."""
        if not isinstance(scenarios_payload, list):
            return []
        parsed: list[dict[str, Any]] = []
        for item in scenarios_payload:
            if not isinstance(item, dict):
                continue
            label = self._clean_optional_string(item.get("label")) or self._clean_optional_string(item.get("scenario"))
            if not label:
                continue
            probability = self._clamp_probability(item.get("probability"))
            basis_value = self._clean_optional_string(item.get("basis"))
            basis = basis_value if basis_value in {"evidence", "prior"} else None
            summary = self._clean_optional_string(item.get("summary")) or label
            parsed.append(
                {"scenario": label, "probability": probability, "basis": basis, "summary": summary}
            )
            if len(parsed) >= 4:
                break
        if not parsed:
            return []

        total = sum(entry["probability"] for entry in parsed if entry["probability"] is not None)
        counted = [entry for entry in parsed if entry["probability"] is not None]
        if counted and (total <= 0 or abs(total - 100.0) > 1.0):
            emit_log(
                stage_key="agent_synthesis",
                level="info",
                title="情形分布已归一化",
                summary=f"scenarios 概率合计为 {round(total, 1)}，已按比例缩放到 100。",
                details=[],
            )
            if total > 0:
                for entry in counted:
                    entry["probability"] = round(entry["probability"] / total * 100.0, 1)

        return [
            PossibilityItem(
                scenario=entry["scenario"],
                likelihood=self._likelihood_from_probability(entry["probability"]),
                probability=entry["probability"],
                basis=entry["basis"],
                summary=entry["summary"],
            )
            for entry in parsed
        ]

    @staticmethod
    def _likelihood_from_probability(probability: Optional[float]) -> str:
        if probability is None:
            return "low"
        if probability >= 66:
            return "high"
        if probability >= 33:
            return "medium"
        return "low"

    def _normalize_timeline_type(self, value: Any) -> str:
        cleaned = self._clean_optional_string(value)
        if cleaned in ALLOWED_TIMELINE_TYPES:
            return cleaned
        return "origin"

    def _normalize_claim_text(self, value: Any) -> Optional[str]:
        cleaned = self._clean_optional_string(value)
        if not cleaned:
            return None
        compact = re.sub(r"\s+", " ", cleaned).strip().rstrip("。！？?!；; ")
        if not compact:
            return None
        return f"{compact}。"

    def _normalize_string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        ordered: list[str] = []
        seen: set[str] = set()
        for item in value:
            cleaned = self._clean_optional_string(item)
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            ordered.append(cleaned)
        return ordered

    def _result_by_id(self, *, retrieval_bundle: RetrievalBundle, result_id: Optional[str]) -> Optional[SearchResult]:
        if not result_id:
            return None
        for item in retrieval_bundle.canonical_results:
            if item.result_id == result_id:
                return item
        return None

    def _extract_json_payload(self, content: str) -> Optional[dict[str, Any]]:
        return loads_lenient_json(content)

    def _json_with_key_usable(self, key: str):
        """Build an is_valid callback that accepts a completion only when the lenient
        parser recovers a dict containing `key`. A truncated planner response (stream
        cut before the decision field) fails this and triggers a retry instead of
        silently giving up — which, for a planner, means prematurely ending the
        investigation loop."""
        def _check(content: str) -> bool:
            payload = self._extract_json_payload(content)
            return isinstance(payload, dict) and key in payload
        return _check

    def _synthesis_content_usable(self, content: str) -> bool:
        """A synthesis completion is worth keeping only if the lenient parser can
        recover an object with at least one claim. A truncated fragment (stream cut
        mid-JSON) or a claim-less object fails this, triggering a retry rather than a
        silent drop to the rule fallback."""
        payload = self._extract_json_payload(content)
        if not isinstance(payload, dict):
            return False
        claims = payload.get("claims")
        return isinstance(claims, list) and len(claims) > 0

    def _coerce_content(self, content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip())
            return "\n".join(parts)
        raise ValueError("Unsupported LLM agent content format")

    def _clean_optional_string(self, value: Any) -> Optional[str]:
        if not isinstance(value, str):
            return None
        compact = re.sub(r"\s+", " ", value).strip()
        return compact or None
