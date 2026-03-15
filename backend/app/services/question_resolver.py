from __future__ import annotations

from dataclasses import dataclass
import re
from typing import List, Optional, Sequence

from backend.app.models.schemas import NormalizedEvent
from backend.app.services.entity_anchor import (
    candidate_matches_subject_anchors,
    extract_subject_anchors,
    text_contains_subject_mismatch,
)
from backend.app.services.question_intent import is_broad_trend_question
from backend.app.services.question_text import clean_question_term, strip_question_tail
from backend.app.services.retrieval_models import RetrievalBundle, SearchResult

QUESTION_STOPWORDS = {
    "\u6700\u8fd1",
    "\u6709\u4e2a",
    "\u6709\u4e00\u4e2a",
    "\u662f\u4e0d\u662f",
    "\u662f\u5426",
    "\u771f\u7684\u5047\u7684",
    "\u771f\u5047\u7684",
    "\u771f\u7684\u5417",
    "\u5c5e\u5b9e\u5417",
    "\u6d88\u606f",
    "\u4f20\u95fb",
    "\u65b0\u95fb",
    "\u4e8b\u60c5",
    "\u8fd9\u4e2a",
    "\u90a3\u4e2a",
    "\u56e0\u4e3a",
}
TITLE_NOISE_MARKERS = (
    "\u56de\u5e94",
    "\u5426\u8ba4",
    "\u8f9f\u8c23",
    "\u6f84\u6e05",
    "\u901a\u62a5",
    "\u8bf4\u660e",
    "\u8868\u793a",
    "\u8bc1\u5b9e",
    "\u4f20\u95fb",
    "\u6d88\u606f",
    "\u8bf4\u6cd5",
    "\u7f51\u4f20",
    "\u7f51\u66dd",
)
GENERIC_CLAIM_MARKERS = (
    "\u5973\u7f51\u7ea2",
    "\u7f51\u7ea2",
    "\u4e3b\u64ad",
    "\u6709\u4eba",
    "\u8fd9\u4e2a\u4e8b\u60c5",
    "\u8fd9\u4ef6\u4e8b",
)
EVENT_SOURCE = "retrieval_resolved"


@dataclass(frozen=True)
class QuestionResolution:
    event: NormalizedEvent
    follow_up_query: Optional[str]
    selected_result: Optional[SearchResult]


def _collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _normalize_text(value: Optional[str]) -> str:
    if not value:
        return ""
    normalized = value.strip().lower()
    replacements = (
        ("\u662f\u4e0d\u662f", " "),
        ("\u662f\u5426", " "),
        ("\u6709\u6ca1\u6709", " "),
        ("\u6700\u8fd1", " "),
        ("\u6709\u4e00\u4e2a", " "),
        ("\u6709\u4e2a", " "),
        ("\u771f\u7684\u5047\u7684", " "),
        ("\u771f\u7684\u662f\u5047\u7684", " "),
        ("\u771f\u7684\u5417", " "),
        ("\u5c5e\u5b9e\u5417", " "),
        ("\uff1f", " "),
        ("?", " "),
        ("\u3002", " "),
        ("\uff0c", " "),
        (",", " "),
    )
    for old, new in replacements:
        normalized = normalized.replace(old, new)
    return _collapse_whitespace(strip_question_tail(normalized))


def _extract_terms(text: str) -> List[str]:
    ordered: List[str] = []
    seen = set()

    def push(term: str) -> None:
        cleaned = clean_question_term(term.strip())
        if not cleaned or cleaned in QUESTION_STOPWORDS or cleaned in seen:
            return
        seen.add(cleaned)
        ordered.append(cleaned)

    normalized = _normalize_text(text)
    for term in re.findall(r"\d+(?:\.\d+)?%?|[a-z0-9]{2,}", normalized):
        push(term)
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", normalized):
        if len(chunk) <= 4:
            push(chunk)
            continue
        for window in (4, 3, 2):
            if len(chunk) < window:
                continue
            for index in range(0, len(chunk) - window + 1):
                push(chunk[index : index + window])
                if len(ordered) >= 12:
                    return ordered
    return ordered


def _question_claim(question: str) -> str:
    claim = question.strip().rstrip("\uff1f?")
    replacements = (
        ("\u8bf7\u95ee", ""),
        ("\u60f3\u95ee\u4e00\u4e0b", ""),
        ("\u60f3\u95ee", ""),
        ("\u6700\u8fd1", ""),
        ("\u6709\u4e00\u4e2a", ""),
        ("\u6709\u4e2a", ""),
        ("\u662f\u4e0d\u662f", ""),
        ("\u662f\u5426", ""),
        ("\u771f\u7684\u5047\u7684", ""),
        ("\u771f\u7684\u662f\u5047\u7684", ""),
        ("\u771f\u7684\u5417", ""),
        ("\u5c5e\u5b9e\u5417", ""),
        ("\u6b7b\u6389\u4e86", "\u6b7b\u4ea1"),
        ("\u6b7b\u6389", "\u6b7b\u4ea1"),
        ("\u6b7b\u4e86", "\u6b7b\u4ea1"),
    )
    for old, new in replacements:
        claim = claim.replace(old, new)
    claim = strip_question_tail(claim)
    claim = _collapse_whitespace(claim.strip(" \uff0c,\uff1a:；;。"))
    return claim


def _clean_candidate_claim(text: str) -> str:
    cleaned = text.strip()
    for marker in TITLE_NOISE_MARKERS:
        cleaned = cleaned.replace(marker, " ")
    cleaned = re.sub(r"[\uff1a:|\u4e28/\\-]", " ", cleaned)
    cleaned = cleaned.strip(" \uff0c,\uff1a:；;。")
    return _collapse_whitespace(cleaned)


def _claim_is_generic(claim: str) -> bool:
    if not claim:
        return True
    if re.search(r"\d", claim):
        return False
    unique_terms = [term for term in _extract_terms(claim) if term not in GENERIC_CLAIM_MARKERS]
    return len(unique_terms) < 2 or any(marker in claim for marker in GENERIC_CLAIM_MARKERS)


def _merge_keywords(primary: Sequence[str], fallback: Sequence[str]) -> List[str]:
    ordered: List[str] = []
    seen = set()
    for item in list(primary) + list(fallback):
        cleaned = _collapse_whitespace(item)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)
        if len(ordered) >= 6:
            break
    return ordered


def _specificity_bonus(text: str) -> int:
    bonus = 0
    if re.search(r"\d", text):
        bonus += 2
    if any(token in text for token in ("\u56de\u5e94", "\u901a\u62a5", "\u8f9f\u8c23", "\u6f84\u6e05", "\u8b66\u65b9", "\u533b\u9662", "\u5b98\u65b9", "\u53bb\u4e16", "\u6b7b\u4ea1", "\u8111\u51fa\u8840", "\u8111\u6ea2\u8840", "\u88c1\u5458")):
        bonus += 2
    if len(text) >= 18:
        bonus += 1
    return bonus


class QuestionResolver:
    def resolve(
        self,
        *,
        event: NormalizedEvent,
        retrieval_bundle: RetrievalBundle | None,
    ) -> QuestionResolution:
        if event.input_type != "question_only" or retrieval_bundle is None or not retrieval_bundle.canonical_results:
            return QuestionResolution(event=event, follow_up_query=None, selected_result=None)
        if is_broad_trend_question(event.raw_input):
            return QuestionResolution(event=event, follow_up_query=None, selected_result=None)

        selected_result = self._select_result(event.raw_input, retrieval_bundle.canonical_results)
        if selected_result is None:
            return QuestionResolution(event=event, follow_up_query=None, selected_result=None)

        summary = self._build_resolved_summary(event.raw_input, selected_result)
        keywords = _merge_keywords(
            _extract_terms(summary),
            [selected_result.source_name, *event.keywords, *_extract_terms(event.raw_input)],
        )
        resolved_event = event.model_copy(
            update={
                "title": selected_result.title,
                "summary": summary or selected_result.snippet or selected_result.title,
                "keywords": keywords or event.keywords,
                "source_name": selected_result.source_name or event.source_name,
                "source_url": selected_result.url,
                "published_at": selected_result.published_at or event.published_at,
                "event_source": EVENT_SOURCE,
                "raw_input": self._build_follow_up_prompt(event.raw_input, selected_result),
            }
        )
        return QuestionResolution(
            event=resolved_event,
            follow_up_query=self._build_follow_up_query(summary, selected_result),
            selected_result=selected_result,
        )

    def _select_result(
        self,
        question: str,
        candidates: Sequence[SearchResult],
    ) -> Optional[SearchResult]:
        question_terms = _extract_terms(question)
        subject_anchors = extract_subject_anchors(question)
        scored: list[tuple[int, int, str, int, SearchResult]] = []
        for item in candidates:
            if subject_anchors and not candidate_matches_subject_anchors(
                subject_anchors,
                item.title,
                item.snippet,
                item.source_name,
            ):
                continue
            if subject_anchors and text_contains_subject_mismatch(item.title, item.snippet, item.source_name):
                continue
            haystack = _normalize_text(f"{item.title} {item.snippet} {item.source_name}")
            overlap = sum(1 for term in question_terms if term and term in haystack)
            if overlap < 2:
                continue
            score = overlap * 6
            score += item.tier_weight * 4
            score += _specificity_bonus(item.title)
            score += _specificity_bonus(item.snippet)
            if item.is_high_trust:
                score += 4
            if subject_anchors:
                score += 8
            if any(token in haystack for token in ("去世", "死亡", "脑出血", "脑溢血")):
                score += 3
            scored.append((score, overlap, item.published_at, item.tier_weight, item))

        if not scored:
            return None
        has_high_trust = any(item.is_high_trust for item in candidates)
        if not has_high_trust:
            return None
        score, overlap, _, _, selected = max(scored, key=lambda item: (item[0], item[1], item[2], item[3]))
        if score < 10:
            return None
        if overlap < 2:
            return None
        return selected

    def _build_resolved_summary(self, question: str, selected_result: SearchResult) -> str:
        base_claim = _question_claim(question)
        candidate_claim = _clean_candidate_claim(selected_result.title) or _clean_candidate_claim(selected_result.snippet)
        if not candidate_claim:
            return base_claim or selected_result.snippet or selected_result.title
        if _claim_is_generic(base_claim):
            return candidate_claim

        summary = base_claim
        for token in re.findall(r"\d+(?:\.\d+)?%?", question):
            if token and token not in summary:
                summary = f"{summary} {token}".strip()
        for token in _extract_terms(candidate_claim):
            if token not in summary and (re.search(r"\d", token) or len(token) >= 4):
                summary = f"{summary} {token}".strip()
        return _collapse_whitespace(summary)

    def _build_follow_up_prompt(self, question: str, selected_result: SearchResult) -> str:
        return (
            f"\u539f\u59cb\u95ee\u9898\uff1a{question}\n"
            "\u7b2c\u4e00\u6b21\u68c0\u7d22\u540e\u9009\u4e2d\u7684\u6700\u53ef\u80fd\u5019\u9009\u4e8b\u4ef6\uff1a\n"
            f"- \u6807\u9898\uff1a{selected_result.title}\n"
            f"- \u6458\u8981\uff1a{selected_result.snippet}\n"
            f"- \u6765\u6e90\uff1a{selected_result.source_name}\n"
            f"- \u65f6\u95f4\uff1a{selected_result.published_at}\n"
            "\u8bf7\u56f4\u7ed5\u8fd9\u4e2a\u66f4\u5177\u4f53\u7684\u5019\u9009\u4e8b\u4ef6\u7ee7\u7eed\u505a\u7ed3\u6784\u5316\u62bd\u53d6\uff0c\u4e0d\u8981\u56de\u5230\u6cdb\u5316\u4f20\u95fb\u3002"
        )

    def _build_follow_up_query(self, summary: str, selected_result: SearchResult) -> str:
        parts = [summary, selected_result.source_name, selected_result.title]
        return " ".join(part.strip() for part in parts if part and part.strip())
