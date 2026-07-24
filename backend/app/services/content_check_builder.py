from __future__ import annotations

import json
import logging
from typing import Iterable, List, Optional

import httpx

from backend.app.core.config import get_settings
from backend.app.models.schemas import AnswerSuggestion, ClaimResult, ContentCheck, ContentCheckItem, EvidenceItem, Report
from backend.app.services.question_intent import (
    is_broad_trend_question,
    safe_trend_summary,
    supported_trend_summary,
    trend_follow_up_hint,
)

logger = logging.getLogger(__name__)


def _trim_claim(text: str) -> str:
    return text.strip().rstrip("。")


def _confidence_score(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if value == "high":
        return 0.95
    if value == "medium":
        return 0.7
    return 0.35


class ContentCheckBuilder:
    def build(self, *, report: Report, original_input: str) -> ContentCheck:
        likely_true = self._to_items(
            item
            for item in report.claim_results
            if item.claim_type == "fact" and item.verdict == "supported"
        )
        likely_false = self._to_items(
            item
            for item in report.claim_results
            if item.claim_type == "fact" and item.verdict == "refuted"
        )
        controversial = self._to_items(
            item
            for item in report.claim_results
            if item.verdict == "conflicting"
        )
        opinions = self._to_items(
            item
            for item in report.claim_results
            if item.claim_type == "opinion"
        )
        uncertain = self._to_items(
            item
            for item in report.claim_results
            if item.claim_type != "opinion" and item.verdict == "insufficient"
        )

        possible_answers = self._build_possible_answers(
            original_input=original_input,
            report=report,
            likely_true=likely_true,
            likely_false=likely_false,
            controversial=controversial,
            opinions=opinions,
            uncertain=uncertain,
        )

        return ContentCheck(
            likely_true=likely_true,
            likely_false=likely_false,
            controversial=controversial,
            opinions=opinions,
            uncertain=uncertain,
            possible_answers=possible_answers,
        )

    def _to_items(self, claim_results: Iterable[ClaimResult]) -> List[ContentCheckItem]:
        ordered = sorted(
            claim_results,
            key=lambda item: (_confidence_score(item.confidence), len(item.evidence)),
            reverse=True,
        )
        return [
            ContentCheckItem(
                claim=item.claim,
                claim_type=item.claim_type,
                verdict=item.verdict,
                confidence=item.confidence,
                truth_probability=item.truth_probability,
                probability_basis=item.probability_basis,
                reason=item.notes,
            )
            for item in ordered[:4]
        ]

    def _build_possible_answers(
        self,
        *,
        original_input: str,
        report: Report,
        likely_true: List[ContentCheckItem],
        likely_false: List[ContentCheckItem],
        controversial: List[ContentCheckItem],
        opinions: List[ContentCheckItem],
        uncertain: List[ContentCheckItem],
    ) -> List[AnswerSuggestion]:
        suggestions: List[AnswerSuggestion] = []
        seen: set[str] = set()
        trend_question = is_broad_trend_question(original_input)

        def push(angle: str, answer: str) -> None:
            normalized = answer.strip()
            if not normalized or normalized in seen or len(suggestions) >= 4:
                return
            seen.add(normalized)
            suggestions.append(AnswerSuggestion(angle=angle, answer=normalized))

        top_true = likely_true[0] if likely_true else None
        top_false = likely_false[0] if likely_false else None
        top_controversial = controversial[0] if controversial else None
        top_uncertain = uncertain[0] if uncertain else None
        top_opinion = opinions[0] if opinions else None

        if trend_question and top_true:
            push(
                "直接回答",
                supported_trend_summary(original_input) or "当前公开来源更倾向于：最近确实有相关消息，但它不是单一事件。",
            )
        elif trend_question and report.mode == "safe_mode":
            push(
                "直接回答",
                safe_trend_summary(original_input) or "这更像一个范围问题，当前还不能直接下确定性结论。",
            )
        elif top_true and top_false:
            push(
                "直接回答",
                (
                    "这句话不能整句算真，更像是半真半假。"
                    f"更像真的部分是“{_trim_claim(top_true.claim)}”，"
                    f"更像后来加上的或不成立的部分是“{_trim_claim(top_false.claim)}”。"
                ),
            )
        elif top_true and top_uncertain:
            push(
                "直接回答",
                (
                    f"核心事件更像成立，比如“{_trim_claim(top_true.claim)}”；"
                    f"但像“{_trim_claim(top_uncertain.claim)}”这样的追加细节还不能跟着一起下结论。"
                ),
            )
        elif top_false and top_uncertain:
            push(
                "直接回答",
                (
                    f"这句话里至少有一部分站不住，比如“{_trim_claim(top_false.claim)}”；"
                    "剩下的细节也还缺证据，不能整句当真。"
                ),
            )
        elif top_controversial:
            push(
                "直接回答",
                f"这句话里的“{_trim_claim(top_controversial.claim)}”目前仍有公开来源冲突，暂时不能强判真或假。",
            )
        elif top_true:
            push("直接回答", f"目前更像真的部分是“{_trim_claim(top_true.claim)}”。")
        elif top_false:
            push("直接回答", f"目前更像不成立的部分是“{_trim_claim(top_false.claim)}”。")
        else:
            push(
                "直接回答",
                "目前还不能把这句话整体判真或判假，只能继续拆成更细的说法逐项核查。",
            )

        if top_opinion:
            push(
                "区分观点",
                f"像“{_trim_claim(top_opinion.claim)}”这种表述更偏观点或判断，不能直接按真假强判。",
            )

        if trend_question:
            push(
                "继续较真",
                trend_follow_up_hint(original_input) or "如果要继续较真，最好把公司名、行业或时间范围再说具体一点。",
            )
        elif report.mode == "safe_mode" or not report.sources:
            push(
                "继续较真",
                "如果要继续较真，最好补姓名、原帖链接、平台账号、截图原文或明确时间点。",
            )
        elif report.provenance.timeline_source != "retrieval":
            push(
                "传播链提醒",
                "当前传播链还没有完全闭环，讲结论时最好明确哪些是核实到的、哪些只是传播中的附加说法。",
            )

        if not likely_true and not likely_false and not controversial and original_input.strip():
            push(
                "更稳妥说法",
                f"更稳妥的说法是：目前只能把“{original_input.strip()}”当待核查线索，不能直接当成既成事实。",
            )

        # When all claims are insufficient but we have retrieval hits, ask LLM
        # to produce a short evidence-based correction from the snippets.
        if (
            not likely_true
            and not likely_false
            and not controversial
            and len(suggestions) < 4
        ):
            all_hits = list(report.sources) + list(report.retrieval_hits)
            correction = self._evidence_based_correction(original_input, all_hits)
            if correction:
                push("根据已有线索", correction)

        return suggestions

    def _evidence_based_correction(
        self, original_input: str, hits: List[EvidenceItem]
    ) -> Optional[str]:
        """Call LLM with a short prompt to produce a factual correction based on
        retrieval snippets. Returns None on any failure so the caller silently
        falls back to the generic answer."""
        if not hits:
            return None
        settings = get_settings()
        if not settings.llm_api_key:
            return None

        snippets_text = "\n".join(
            f"- {h.title}" for h in hits[:8] if h.title.strip()
        )
        if not snippets_text.strip():
            return None

        system = (
            "你是一个事实核查助手。根据检索到的新闻标题，对比用户的原始说法，"
            "用一句话指出原文哪里不准确、实际情况更接近什么。"
            "只纠正有依据的部分，没有依据的不要猜。不超过80字。只输出纠正文本本身。"
        )
        user = f"用户原文：{original_input}\n\n检索到的新闻标题：\n{snippets_text}"

        # Use the first non-reasoning model for this lightweight call; reasoning
        # models waste their token budget on CoT before producing any content.
        model = "DeepSeek-V4-Flash"
        for m in settings.available_models:
            if not settings.is_reasoning_model(m):
                model = m
                break
        base_url = settings.base_url_for_model(model)
        try:
            resp = httpx.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json={
                    "model": model,
                    "temperature": 0.3,
                    "max_tokens": 512,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
                timeout=30.0,
            )
            if resp.status_code != 200:
                logger.debug("correction LLM returned %d", resp.status_code)
                return None
            data = resp.json()
            msg = data["choices"][0]["message"]
            content = (msg.get("content") or "").strip()
            if not content:
                content = (msg.get("reasoning_content") or "").strip()
                if content:
                    # Reasoning models dump CoT; take only the last sentence.
                    last = content.rsplit("\n", 1)[-1].strip()
                    content = last if len(last) <= 150 else ""
            if not content or len(content) > 150:
                return None
            return content
        except Exception as exc:
            logger.debug("correction LLM call failed: %s", exc)
            return None
