from __future__ import annotations

from typing import List

from backend.app.models.schemas import NormalizedEvent, TimelineNode
from backend.app.services.contract_utils import ensure_datetime_string
from backend.app.services.scenario_library import match_scenario


class TimelineBuilder:
    def build(self, event: NormalizedEvent) -> List[TimelineNode]:
        scenario = match_scenario(" ".join(filter(None, [event.raw_input, event.title, event.summary])))
        if event.input_type == "question_only" and scenario.scenario_id != "beichuan_school":
            return []
        if scenario.timeline:
            return list(scenario.timeline)
        return [
            TimelineNode(
                node_type="origin",
                title="输入内容进入分析队列",
                url=event.source_url or "https://example.org/input/manual-input",
                source_name=event.source_name or "用户提供输入",
                published_at=ensure_datetime_string(event.published_at),
                summary="系统已接收输入，但尚未补齐稳定传播链。",
                why_selected="当前只有输入本身，没有足够外部节点可构成时间线。",
            )
        ]
