from __future__ import annotations

from typing import List

from backend.app.models.schemas import EventDraft, TimelineNode
from backend.app.services.scenario_library import match_scenario


class TimelineBuilder:
    def build(self, event: EventDraft) -> List[TimelineNode]:
        scenario = match_scenario(" ".join(filter(None, [event.raw_input, event.title, event.summary])))
        if event.input_type == "question_only" and scenario.scenario_id != "beichuan_school":
            return []
        if scenario.timeline:
            return list(scenario.timeline)
        return [
            TimelineNode(
                title="输入内容进入分析队列",
                description="系统已接收输入，但尚未补齐稳定传播链。",
                node_type="placeholder",
                confidence="low",
            )
        ]
