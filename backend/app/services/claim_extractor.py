from __future__ import annotations

from typing import List, Optional

from backend.app.models.schemas import ClaimItem, NormalizedEvent
from backend.app.services.scenario_library import match_scenario


class ClaimExtractor:
    def extract(self, event: NormalizedEvent, provider_claims: Optional[List[ClaimItem]] = None) -> List[ClaimItem]:
        scenario = match_scenario(" ".join(filter(None, [event.raw_input, event.title, event.summary])))

        if provider_claims:
            fallback_claims = list(scenario.claims) if scenario.scenario_id != "generic" else None
            merged = self._merge_claims(provider_claims, fallback_claims)
            if merged:
                return merged

        if scenario.scenario_id != "generic":
            return list(scenario.claims)

        claim = event.summary if event.summary.endswith("。") else f"{event.summary}。"
        return [ClaimItem(claim=claim, claim_type=self.classify(claim))]

    def classify(self, claim: str) -> str:
        if any(token in claim for token in ["觉得", "认为", "明显", "不值得相信", "隐瞒", "混乱"]):
            return "opinion"
        if any(token in claim for token in ["将", "下周", "会继续", "肯定会"]):
            return "prediction"
        if any(token in claim for token in ["很多内部员工", "提前收到名单", "匿名", "家长已经确认"]):
            return "unverifiable"
        return "fact"

    def _merge_claims(
        self,
        provider_claims: List[ClaimItem],
        fallback_claims: Optional[List[ClaimItem]] = None,
    ) -> List[ClaimItem]:
        seen = set()
        merged: List[ClaimItem] = []
        for item in provider_claims + list(fallback_claims or []):
            claim_text = item.claim.strip()
            if not claim_text or claim_text in seen:
                continue
            seen.add(claim_text)
            merged.append(ClaimItem(claim=claim_text, claim_type=item.claim_type))
            if len(merged) >= 5:
                break
        return merged
