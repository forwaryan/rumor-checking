from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from backend.app.models.schemas import ClaimItem, ClaimSourceType, NormalizedEvent

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
        rule_claims = self._extract_rule_claims(event)
        if provider_claims:
            supplemental_claims = rule_claims if len(provider_claims) < 2 else []
            merged, added_rule = self._merge_claims(provider_claims, supplemental_claims)
            if merged:
                source = "provider_plus_rule" if added_rule else "provider"
                return ClaimExtraction(claims=merged, source=source)

        if rule_claims:
            return ClaimExtraction(claims=rule_claims, source="rule")

        claim = event.summary if event.summary.endswith("。") else f"{event.summary}。"
        return ClaimExtraction(claims=[ClaimItem(claim=claim, claim_type=self.classify(claim))], source="rule")

    def classify(self, claim: str) -> str:
        if any(token in claim for token in ["觉得", "认为", "明显", "不值得相信", "隐瞒", "混乱"]):
            return "opinion"
        if any(token in claim for token in ["将", "下周", "会继续", "肯定会"]):
            return "prediction"
        if any(token in claim for token in ["很多内部员工", "提前收到名单", "匿名", "家长已经确认"]):
            return "unverifiable"
        return "fact"

    def _extract_rule_claims(self, event: NormalizedEvent) -> List[ClaimItem]:
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
        if event.input_type == "question_only":
            fragments.append(event.summary)
            return fragments

        for text in [event.raw_input, event.summary, event.title]:
            if not text:
                continue
            fragments.extend(part for part in SPLIT_PATTERN.split(text) if part.strip())
        return fragments

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
