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
- Output JSON only.
""".strip()
SYNTHESIS_SYSTEM_PROMPT = """
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
  ],
  "event": {
    "title": "string or null (≤30 chars)",
    "summary": "string or null (≤60 chars)",
    "source_name": "string or null",
    "published_at": "ISO-8601 / YYYY-MM-DD / null",
    "anchor_result_id": "string or null"
  },
  "scenarios": [
    {
      "label": "string — a distinct way the whole message could be true/false",
      "probability": 0-100,
      "basis": "evidence|prior",
      "summary": "string (≤50 chars)"
    }
  ],
  "timeline": [
    {
      "node_type": "origin|amplification|peak|turn|clarification",
      "result_id": "string",
      "summary": "string or null (≤50 chars)",
      "why_selected": "string (≤40 chars)"
    }
  ]
}

Output the keys in EXACTLY this order: claims first, then event, scenarios, timeline.
The claims are the most important output — emit them first so they are complete even
if the response is long. Keep every free-text field within its char cap; do not write
long paragraphs. Think briefly, then output the JSON — a very long chain-of-thought
risks the answer being cut off before the JSON is complete.

Rules:
- Use only supplied retrieval hits. Never invent result ids, evidence, or URLs.
- Claims must be atomic and directly checkable. Prefer 1 to 4 claims, but splitting a
  core+detail pair (see CLAIM DECOMPOSITION) may take you up to 6 — that is fine.
- CLAIM DECOMPOSITION — split a verified core from an unverified detail (read carefully):
  - A rumor often glues a checkable CORE fact to a specific QUANTIFIER or QUALIFIER
    (an exact count, an exact headcount, a role/scope restriction, a precise date).
    When the hits support the core but NOT the specific detail, DO NOT emit one bundled
    claim and mark the whole thing insufficient — that buries a real supported fact under
    one unproven modifier. Instead emit TWO atomic claims:
      1. the CORE (evidence supports it → `supported`), and
      2. the DETAIL alone (no evidence for the exact number/scope → `insufficient`).
  - Example: input "买了三栋楼、招了5000研发". If hits confirm 购置办公楼 and 5000招聘名额
    but not "三栋" or "研发岗", emit: (a) "购置了办公楼" supported, (b) "办公楼数量为三栋"
    insufficient, (c) "招聘名额约5000" supported, (d) "招聘岗位均为研发" insufficient.
  - Keep each split claim self-contained (name the subject in every claim; never rely on
    "它/该数量" back-references). The core claim carries its own evidence_result_ids.
- PROBABILITY (independent of verdict — read carefully):
  - `truth_probability` = your best estimate of P(this claim is literally true), 0-100.
  - `probability_basis` = "evidence" ONLY if the supplied hits actually bear on this claim;
    otherwise "prior" (you are using world knowledge / common sense, not the hits).
  - You MUST still give a number even with zero relevant evidence — use your prior and mark
    basis="prior". Example: a well-known company plausibly owns buildings (high prior), but a
    very specific unverified combo (a named city + an exact count + an exact headcount) is
    individually unlikely and unsupported → low probability, basis="prior".
  - Probability does NOT change the verdict. A claim can be `insufficient` (no evidence) yet
    still carry, say, truth_probability 15 with basis="prior". Keep the two independent.
- `scenarios`: 2 to 4 MUTUALLY EXCLUSIVE ways the WHOLE input could turn out (e.g. 基本属实 /
  部分属实但细节被夸大失真 / 暂无法证实 / 纯属虚构). Their `probability` values MUST sum to ~100.
  Set basis="evidence" for a scenario grounded in the hits, else "prior".
- CRITICAL — how to pick each verdict (follow this decision procedure exactly):
  1. Find hits that are about the SAME subject AND the SAME action/topic as the claim.
  2. If there are NONE (the hits are about other topics, other companies, or you find yourself
     writing "没提到/未找到/没有相关信息/not mentioned" in notes) → verdict = `insufficient`.
     Never write `refuted` to mean "I could not find supporting evidence". Not finding proof is
     NOT the same as finding disproof.
  3. Use `refuted` ONLY when a hit EXPLICITLY denies/debunks/contradicts THIS claim's action for
     THIS subject (e.g. an official statement "我们没有造游轮" / a debunk of this exact event).
     A denial about a different topic by the same entity (e.g. "京东辟谣稳定币传闻" for a claim
     about 京东造游轮) is NOT a refutation → `insufficient`.
  4. Use `supported` only with evidence that directly affirms the claim (respect scope, see below).
  5. Use `conflicting` when reputable hits both affirm and deny the SAME claim.
- Scope/quantifier discipline: if a claim uses an absolute scope ("all / only / every / none / 都是/全部/仅/无一例外/清一色"), it is `supported` ONLY when the evidence explicitly covers the ENTIRE scope. If the evidence supports just part of it (e.g. the claim says "all roles are R&D" but the evidence lists R&D AND non-R&D roles such as management/operations/QA), you MUST NOT mark it `supported` — use `insufficient` (or `refuted` if the evidence directly contradicts the absolute), and state in `notes` that the evidence only covers part of the claimed scope.
- If the question is about a broad pattern and the hits support that pattern across multiple incidents, you may answer at the pattern level instead of forcing one person.
- Do not emit `supported`, `refuted`, or `conflicting` without at least one valid `evidence_result_id`.
- Timeline nodes must reference supplied result ids and should be chronological when possible.
- Output JSON only.
""".strip()
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
- Output JSON only.
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
- Prefer "investigate" when evidence is weak (low grade, few independent high-trust sources,
  conflicting signals) AND another round could plausibly help.
- Prefer "fetch_url" when there is a strong source whose snippet is too thin to decide, and reading
  its full text would likely settle the claim. Use sparingly (each fetch is a live HTTP round).
- Prefer "synthesize" when evidence is already strong and independently corroborated, or when
  further searching is unlikely to help.
- Output JSON only.
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
- Output JSON only.
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


class LlmAgentReasoner:
    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        # Optional per-request model override (validated against the whitelist by
        # the caller). None means use the configured default.
        self.model_override: Optional[str] = None

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
            system_prompt=SYNTHESIS_SYSTEM_PROMPT,
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

        evidence_source: EvidenceSourceType = "retrieval_mock" if retrieval_bundle.provider_name == "mock" else "retrieval_live"
        evidence_pool = retrieval_bundle.to_evidence_items()
        timeline_nodes = self._build_timeline_nodes(
            result_map=result_map,
            timeline_payload=payload.get("timeline"),
        )
        claim_items = [ClaimItem(claim=item.claim, claim_type=item.claim_type) for item in claim_results]
        timeline_source = "retrieval" if timeline_nodes else "none"
        possibilities = self._build_scenarios(payload.get("scenarios"))
        return AgentSynthesis(
            event=synthesized_event,
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
    ) -> str:
        model = self._reasoning_model()
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

        - **Fast models**: pin response_format=json_object, a modest token budget,
          and the short provider timeout. They answer immediately.
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
        # json_object stalls reasoning models; they still return a fenced ```json
        # block that loads_lenient_json recovers, so only pin it for fast models.
        if not is_reasoning:
            body["response_format"] = {"type": "json_object"}

        parts: list[str] = []
        char_budget = max_tokens * _STREAM_CHARS_PER_TOKEN
        deadline = time.monotonic() + timeout_seconds
        collected = 0
        reasoning_chars = 0
        truncated = False
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
            # A stalled/runaway stream: keep whatever arrived; the caller's lenient
            # JSON parser may still recover a usable object from the partial content.
            truncated = True
            logger.warning(
                "llm_stream_read_timeout model=%s content_chars=%s reasoning_chars=%s",
                model,
                len("".join(parts)),
                reasoning_chars,
            )
        if truncated:
            logger.warning(
                "llm_stream_truncated model=%s reasoning=%s content_chars=%s reasoning_chars=%s char_budget=%s",
                model,
                is_reasoning,
                len("".join(parts)),
                reasoning_chars,
                char_budget,
            )
        return "".join(parts).strip()

    def _reasoning_model(self) -> str:
        if self.model_override:
            return self.model_override
        return self.settings.llm_search_model.strip() or self.settings.llm_model.strip()

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
            # Full-body text for some hits, keyed by the SAME result_id the model
            # must cite in evidence_result_ids — richer grounding, same ids.
            context["fetched_full_text"] = [
                {"result_id": rid, "full_text": body}
                for rid, body in fetched_bodies.items()
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

    def _guard_overbroad_claim_verdict(
        self,
        *,
        claim_text: str,        verdict: str,
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
