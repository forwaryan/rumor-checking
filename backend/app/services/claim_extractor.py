from __future__ import annotations

from typing import List

from backend.app.models.schemas import ClaimItem, NormalizedEvent
from backend.app.services.scenario_library import match_scenario


class ClaimExtractor:
    def extract(self, event: NormalizedEvent) -> List[ClaimItem]:
        scenario = match_scenario(" ".join(filter(None, [event.raw_input, event.title, event.summary])))
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
