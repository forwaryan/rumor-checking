from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from backend.app.models.schemas import ClaimItem, ClaimSourceType, NormalizedEvent
from backend.app.services.question_intent import rewrite_broad_trend_question_as_claim

SCAFFOLDING_MARKERS = (
    "系统已",
    "当前只能",
    "建议",
    "稍后重试",
    "保守提示",
    "保守模式",
    "只拿到用户提供的链接",
    "待核实",
)
QUESTION_TRAILING_MARKERS = ("是真的吗", "属实吗", "是真是假", "真还是假的")
SPLIT_PATTERN = re.compile(r"[。！？?!；;]")
CLAUSE_SPLIT_PATTERN = re.compile(r"[，,、]")
CONNECTOR_SPLIT_PATTERN = re.compile(r"(并且|而且|还说|还称|还传|并称|又说|又称|但是|不过|同时)")
LEADING_CONNECTORS = ("并且", "而且", "还说", "还称", "还传", "并称", "又说", "又称", "但是", "但", "不过", "同时")


@dataclass(frozen=True)
class ClaimExtraction:
    claims: List[ClaimItem]
    source: ClaimSourceType


class ClaimExtractor:
    def extract(self, event: NormalizedEvent, provider_claims: Optional[List[ClaimItem]] = None) -> List[ClaimItem]:
        return self.extract_with_source(event, provider_claims=provider_claims).claims

    def extract_with_source(
        self,
        event: NormalizedEvent,
        provider_claims: Optional[List[ClaimItem]] = None,
    ) -> ClaimExtraction:
        if not provider_claims:
            raise ValueError("Kimi-only mode requires provider claims.")

        merged, _ = self._merge_claims(provider_claims, None)
        if not merged:
            raise ValueError("Kimi returned no usable claims.")
        return ClaimExtraction(claims=merged, source="provider")

    def classify(self, claim: str) -> str:
        if any(token in claim for token in ["觉得", "认为", "明显", "不值得相信", "隐瞒", "混乱"]):
            return "opinion"
        if any(token in claim for token in ["将", "下周", "会继续", "肯定会"]):
            return "prediction"
        if any(token in claim for token in ["很多内部员工", "提前收到名单", "匿名", "家长已经确认"]):
            return "unverifiable"
        return "fact"

    def _extract_rule_claims(self, event: NormalizedEvent) -> List[ClaimItem]:
        broad_trend_claim = rewrite_broad_trend_question_as_claim(event.raw_input)
        if event.input_type == "question_only" and broad_trend_claim:
            return [ClaimItem(claim=broad_trend_claim, claim_type="fact")]

        fragments = self._candidate_fragments(event)
        claims: List[ClaimItem] = []
        seen: set[str] = set()

        if event.fallback_used and event.input_type in {"url_news", "url_unknown"}:
            self._push_claim("当前链接页面缺少完整正文或正式来源。", claims, seen)

        for fragment in fragments:
            cleaned = self._clean_fragment(fragment)
            if not cleaned or len(cleaned) < 6 or self._looks_like_scaffolding(cleaned):
                continue
            self._push_claim(cleaned, claims, seen)
            if len(claims) >= 5:
                break
        return claims[:5]

    def _candidate_fragments(self, event: NormalizedEvent) -> List[str]:
        fragments: List[str] = []
        source_texts = [event.raw_input, event.summary]
        if event.input_type != "question_only":
            source_texts.append(event.title)

        for text in source_texts:
            if not text:
                continue
            for sentence in SPLIT_PATTERN.split(text):
                if not sentence.strip():
                    continue
                fragments.extend(self._split_compound_fragment(sentence))
        return fragments

    def _split_compound_fragment(self, fragment: str) -> List[str]:
        clauses: List[str] = []
        comma_parts = [part.strip() for part in CLAUSE_SPLIT_PATTERN.split(fragment) if part.strip()]
        if not comma_parts:
            return []

        for part in comma_parts:
            pieces = CONNECTOR_SPLIT_PATTERN.split(part)
            if len(pieces) == 1:
                clauses.append(part)
                continue

            current = pieces[0].strip()
            if current:
                clauses.append(current)
            for index in range(1, len(pieces), 2):
                connector = pieces[index].strip()
                tail = pieces[index + 1].strip() if index + 1 < len(pieces) else ""
                merged = f"{connector}{tail}".strip()
                if merged:
                    clauses.append(merged)

        return clauses or [fragment]

    def _push_claim(self, raw_text: str, claims: List[ClaimItem], seen: set[str]) -> None:
        normalized = re.sub(r"[。！？?!]+$", "", raw_text).strip()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        claim_text = normalized if normalized.endswith("。") else f"{normalized}。"
        claims.append(ClaimItem(claim=claim_text, claim_type=self.classify(claim_text)))

    def _clean_fragment(self, fragment: str) -> str:
        cleaned = re.sub(r"^【[^】]+】", "", fragment).strip(" ，,：:；;")
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        for marker in LEADING_CONNECTORS:
            if cleaned.startswith(marker):
                cleaned = cleaned[len(marker) :].strip()
        for marker in QUESTION_TRAILING_MARKERS:
            if cleaned.endswith(marker):
                cleaned = cleaned[: -len(marker)].strip()
        if cleaned.startswith(("http://", "https://")):
            return ""
        return cleaned

    def _looks_like_scaffolding(self, text: str) -> bool:
        return any(marker in text for marker in SCAFFOLDING_MARKERS)

    def _merge_claims(
        self,
        provider_claims: List[ClaimItem],
        fallback_claims: Optional[List[ClaimItem]] = None,
    ) -> tuple[List[ClaimItem], bool]:
        seen = set()
        merged: List[ClaimItem] = []
        added_rule = False
        for item in provider_claims:
            claim_text = item.claim.strip()
            if not claim_text or claim_text in seen:
                continue
            seen.add(claim_text)
            merged.append(ClaimItem(claim=claim_text, claim_type=item.claim_type))
            if len(merged) >= 5:
                return merged, added_rule

        for item in list(fallback_claims or []):
            claim_text = item.claim.strip()
            if not claim_text or claim_text in seen:
                continue
            seen.add(claim_text)
            merged.append(ClaimItem(claim=claim_text, claim_type=item.claim_type))
            added_rule = True
            if len(merged) >= 5:
                break
        return merged, added_rule
