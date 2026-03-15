from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
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
    TimelineNode,
)
from backend.app.services.claim_extractor import ClaimExtraction
from backend.app.services.contract_utils import default_source_name, default_source_url, ensure_datetime_string
from backend.app.services.question_intent import is_broad_trend_question
from backend.app.services.question_resolver import QuestionResolution
from backend.app.services.retrieval_models import RetrievalBundle, SearchResult
from backend.app.services.timeline_builder import TimelineBuild
from backend.app.services.verdict_engine import VerdictEvaluation

logger = logging.getLogger(__name__)

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
  "event": {
    "title": "string or null",
    "summary": "string or null",
    "source_name": "string or null",
    "published_at": "ISO-8601 / YYYY-MM-DD / null",
    "anchor_result_id": "string or null"
  },
  "claims": [
    {
      "claim": "string",
      "claim_type": "fact|opinion|prediction|unverifiable",
      "verdict": "supported|refuted|insufficient|conflicting",
      "confidence": "high|medium|low",
      "evidence_result_ids": ["result_id"],
      "notes": "string"
    }
  ],
  "timeline": [
    {
      "node_type": "origin|amplification|peak|turn|clarification",
      "result_id": "string",
      "summary": "string or null",
      "why_selected": "string"
    }
  ]
}

Rules:
- Use only supplied retrieval hits. Never invent result ids, evidence, or URLs.
- Claims must be atomic and directly checkable. Prefer 1 to 4 claims.
- If the question is about a broad pattern and the hits support that pattern across multiple incidents, you may answer at the pattern level instead of forcing one person.
- If evidence is weak or mismatched, keep verdict as `insufficient`.
- Do not emit `supported`, `refuted`, or `conflicting` without at least one valid `evidence_result_id`.
- Timeline nodes must reference supplied result ids and should be chronological when possible.
- Output JSON only.
""".strip()


@dataclass(frozen=True)
class AgentSynthesis:
    event: NormalizedEvent
    claim_extraction: ClaimExtraction
    verdict: VerdictEvaluation
    timeline: TimelineBuild


class KimiAgentReasoner:
    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

    @property
    def enabled(self) -> bool:
        return self.settings.analysis_provider == "kimi" and bool(self.settings.kimi_api_key)

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
            system_prompt=QUESTION_RESOLUTION_SYSTEM_PROMPT,
            user_prompt=self._build_resolution_prompt(event=event, retrieval_bundle=retrieval_bundle),
        )
        payload = self._extract_json_payload(content)
        if payload is None:
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
    ) -> Optional[AgentSynthesis]:
        if not self.enabled:
            return None
        if retrieval_bundle is None or not retrieval_bundle.canonical_results:
            return None

        content = self._request_completion(
            system_prompt=SYNTHESIS_SYSTEM_PROMPT,
            user_prompt=self._build_synthesis_prompt(
                request=request,
                event=event,
                retrieval_bundle=retrieval_bundle,
            ),
        )
        payload = self._extract_json_payload(content)
        if payload is None:
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
        )

    def _request_completion(self, *, system_prompt: str, user_prompt: str) -> str:
        model = self._reasoning_model()
        response = httpx.post(
            f"{self.settings.kimi_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.settings.kimi_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "temperature": self._request_temperature(model),
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=self.settings.provider_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        choice = payload.get("choices", [{}])[0]
        message = choice.get("message", {})
        return self._coerce_content(message.get("content"))

    def _reasoning_model(self) -> str:
        preferred = self.settings.kimi_search_model.strip() or self.settings.kimi_model.strip()
        if preferred.lower().startswith("kimi-k2.5"):
            return "kimi-k2-turbo-preview"
        return preferred

    def _request_temperature(self, model: str) -> float:
        model = model.strip().lower()
        if model.startswith("kimi-k2.5"):
            return 1.0
        if model.startswith("kimi-k2-turbo-preview"):
            return 0.6
        return min(self.settings.kimi_temperature, 0.3)

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
        return (
            "Produce an evidence-grounded event summary, atomic claims, verdicts, and timeline nodes.\n"
            "Do not force a single person if the supplied hits only support a broader recent pattern.\n"
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

            claim_results.append(
                ClaimResult(
                    claim=claim_text,
                    claim_type=claim_type,
                    verdict=verdict,
                    confidence=confidence,
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
                    published_at=result.published_at,
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
        stripped = content.strip()
        candidates = [stripped]

        fenced_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", stripped, flags=re.DOTALL)
        if fenced_match:
            candidates.insert(0, fenced_match.group(1).strip())

        brace_start = stripped.find("{")
        brace_end = stripped.rfind("}")
        if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
            candidates.append(stripped[brace_start : brace_end + 1])

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        return None

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
        raise ValueError("Unsupported Kimi agent content format")

    def _clean_optional_string(self, value: Any) -> Optional[str]:
        if not isinstance(value, str):
            return None
        compact = re.sub(r"\s+", " ", value).strip()
        return compact or None
