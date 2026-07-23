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
    "最近",
    "有个",
    "有一个",
    "是不是",
    "是否",
    "真的假的",
    "真的假的",
    "真的吗",
    "属实吗",
    "消息",
    "传闻",
    "新闻",
    "事情",
    "这个",
    "那个",
    "因为",
}
TITLE_NOISE_MARKERS = (
    "回应",
    "否认",
    "辟谣",
    "澄清",
    "通报",
    "说明",
    "表示",
    "证实",
    "传闻",
    "消息",
    "说法",
    "网传",
    "网曝",
)
GENERIC_CLAIM_MARKERS = (
    "女网红",
    "网红",
    "主播",
    "有人",
    "这个事情",
    "这件事",
)
QUESTION_ACTION_MARKERS = (
    "停航",
    "停运",
    "停课",
    "裁员",
    "脑出血",
    "脑溢血",
    "去世",
    "死亡",
    "住院",
    "救治",
    "回应",
    "通报",
    "核查",
    "整改",
    "恢复",
    "辟谣",
)
TIME_TOKEN_PATTERN = re.compile(
    r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?|\d{1,2}月\d{1,2}日(?:上午|下午|凌晨|晚上|晚间|中午)?|明天|今晚|今早|今天|今日|昨天|昨日|下周|本周|近日|近期"
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
        ("是不是", " "),
        ("是否", " "),
        ("有没有", " "),
        ("最近", " "),
        ("有一个", " "),
        ("有个", " "),
        ("真的假的", " "),
        ("真的还是假的", " "),
        ("真的吗", " "),
        ("属实吗", " "),
        ("？", " "),
        ("?", " "),
        ("。", " "),
        ("，", " "),
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


def _extract_time_tokens(text: str) -> List[str]:
    ordered: List[str] = []
    seen = set()
    for match in TIME_TOKEN_PATTERN.finditer(text):
        token = _collapse_whitespace(match.group(0))
        if token and token not in seen:
            seen.add(token)
            ordered.append(token)
    return ordered


def _extract_query_focus_terms(text: str) -> List[str]:
    ordered: List[str] = []
    seen = set()

    def push(term: str) -> None:
        cleaned = _collapse_whitespace(term)
        if not cleaned or cleaned in seen or cleaned in QUESTION_STOPWORDS:
            return
        seen.add(cleaned)
        ordered.append(cleaned)

    for anchor in extract_subject_anchors(text):
        push(anchor)
    for marker in QUESTION_ACTION_MARKERS:
        if marker in text:
            push(marker)
    for token in _extract_time_tokens(text):
        push(token)
    for token in _extract_terms(text):
        if re.search(r"\d", token) or re.fullmatch(r"[a-z0-9][a-z0-9&.\-]{1,30}", token):
            push(token)
    return ordered


def _question_claim(question: str) -> str:
    claim = question.strip().rstrip("？?")
    replacements = (
        ("请问", ""),
        ("想问一下", ""),
        ("想问", ""),
        ("最近", ""),
        ("有一个", ""),
        ("有个", ""),
        ("是不是", ""),
        ("是否", ""),
        ("真的假的", ""),
        ("真的还是假的", ""),
        ("真的吗", ""),
        ("属实吗", ""),
        ("死掉了", "死亡"),
        ("死掉", "死亡"),
        ("死了", "死亡"),
    )
    for old, new in replacements:
        claim = claim.replace(old, new)
    claim = strip_question_tail(claim)
    claim = _collapse_whitespace(claim.strip(" ，,:：；;。"))
    return claim


def _clean_candidate_claim(text: str) -> str:
    cleaned = text.strip()
    for marker in TITLE_NOISE_MARKERS:
        cleaned = cleaned.replace(marker, " ")
    cleaned = re.sub(r"[：:|丨/\\-]", " ", cleaned)
    cleaned = cleaned.strip(" ，,:：；;。")
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
    if any(token in text for token in ("回应", "通报", "辟谣", "澄清", "警方", "医院", "官方", "去世", "死亡", "脑出血", "脑溢血", "裁员")):
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
            _extract_query_focus_terms(summary),
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
        scored: List[tuple[int, int, str, int, SearchResult]] = []
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
            scored.append((score, overlap, item.effective_published_at, item.tier_weight, item))

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
        for token in _extract_query_focus_terms(question):
            if token not in summary and (re.search(r"\d", token) or len(token) >= 4):
                summary = f"{summary} {token}".strip()
        for token in _extract_query_focus_terms(candidate_claim):
            if token not in summary and (re.search(r"\d", token) or len(token) >= 4 or token in QUESTION_ACTION_MARKERS):
                summary = f"{summary} {token}".strip()
        return _collapse_whitespace(summary)

    def _build_follow_up_prompt(self, question: str, selected_result: SearchResult) -> str:
        return (
            f"原始问题：{question}\n"
            "第一次检索后选中的最可能候选事件：\n"
            f"- 标题：{selected_result.title}\n"
            f"- 摘要：{selected_result.snippet}\n"
            f"- 来源：{selected_result.source_name}\n"
            f"- 时间：{selected_result.published_at}\n"
            "请围绕这个更具体的候选事件继续做结构化抽取，不要回到泛化传闻。"
        )

    def _build_follow_up_query(self, summary: str, selected_result: SearchResult) -> str:
        tokens: List[str] = []
        seen = set()

        def push(value: Optional[str]) -> None:
            if not value:
                return
            cleaned = _collapse_whitespace(value)
            if not cleaned or cleaned in seen:
                return
            seen.add(cleaned)
            tokens.append(cleaned)

        for value in _extract_query_focus_terms(summary):
            push(value)
        push(selected_result.source_name)
        for value in _extract_query_focus_terms(selected_result.title):
            push(value)
        for value in _extract_query_focus_terms(selected_result.snippet):
            push(value)

        if tokens:
            return " ".join(tokens[:8])

        parts = [summary, selected_result.source_name, selected_result.title]
        return " ".join(part.strip() for part in parts if part and part.strip())
