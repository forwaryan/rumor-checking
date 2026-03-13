from __future__ import annotations

import re
from typing import List, Optional

from backend.app.models.schemas import NormalizedEvent, TimelineNode
from backend.app.services.contract_utils import ensure_datetime_string
from backend.app.services.retrieval_models import RetrievalBundle, SearchResult
from backend.app.services.scenario_library import match_scenario

TURN_KEYWORDS = ("回应", "否认", "辟谣", "澄清", "致歉")
CLARIFICATION_KEYWORDS = ("恢复", "说明", "更新", "通报")
AMPLIFICATION_KEYWORDS = ("传闻", "爆料", "截图", "转发", "转载", "发酵", "热议", "聚合")
PEAK_KEYWORDS = ("发酵", "热议", "刷屏", "持续")


class TimelineBuilder:
    def build(self, event: NormalizedEvent, retrieval_bundle: RetrievalBundle | None = None) -> List[TimelineNode]:
        if retrieval_bundle and retrieval_bundle.canonical_results:
            retrieval_timeline = self._build_from_retrieval(retrieval_bundle)
            if retrieval_timeline:
                return retrieval_timeline

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

    def _build_from_retrieval(self, retrieval_bundle: RetrievalBundle) -> List[TimelineNode]:
        results = list(retrieval_bundle.canonical_results)
        if not results:
            return []

        origin = self._select_origin(results, retrieval_bundle.query)
        selected_ids = set()
        candidates: list[tuple[str, Optional[SearchResult]]] = [
            ("origin", origin),
            ("amplification", self._select_amplification(results, origin)),
            ("peak", self._select_peak(results, origin)),
            ("turn", self._select_turn(results, origin)),
            ("clarification", self._select_clarification(results, origin)),
        ]

        timeline_nodes: list[TimelineNode] = []
        for node_type, result in candidates:
            if result is None or result.result_id in selected_ids:
                continue
            selected_ids.add(result.result_id)
            timeline_nodes.append(
                TimelineNode(
                    node_type=node_type,
                    title=result.title,
                    url=result.url,
                    source_name=result.source_name,
                    published_at=result.published_at,
                    summary=result.snippet,
                    why_selected=self._build_selection_reason(node_type, result),
                )
            )

        return sorted(timeline_nodes, key=lambda item: (item.published_at, item.node_type))[:10]

    def _select_origin(self, results: List[SearchResult], query: str) -> SearchResult:
        ordered = sorted(results, key=self._sort_key)
        first_turn = self._select_turn(ordered, None)
        if first_turn is not None:
            rumor_candidates = [
                item
                for item in ordered
                if item.published_dt <= first_turn.published_dt
                and not item.is_high_trust
                and self._looks_like_rumor(item)
                and self._query_overlap(item, query) >= 2
            ]
            if rumor_candidates:
                return rumor_candidates[0]

        high_trust = [item for item in ordered if item.is_high_trust]
        if high_trust:
            earliest_date = high_trust[0].published_at[:10]
            same_day = [item for item in high_trust if item.published_at[:10] == earliest_date]
            return sorted(same_day, key=lambda item: (-item.tier_weight, item.published_at, item.result_id))[0]
        return ordered[0]

    def _select_amplification(self, results: List[SearchResult], origin: Optional[SearchResult]) -> Optional[SearchResult]:
        if origin is None:
            return None
        for item in sorted(results, key=self._sort_key):
            if item.result_id == origin.result_id or item.published_dt < origin.published_dt:
                continue
            if item.is_high_trust:
                continue
            if self._is_match(item, AMPLIFICATION_KEYWORDS) or item.source_tier in {"B", "C"}:
                return item
        return None

    def _select_peak(self, results: List[SearchResult], origin: Optional[SearchResult]) -> Optional[SearchResult]:
        if origin is None or len(results) < 4:
            return None
        for item in reversed(sorted(results, key=self._sort_key)):
            if item.result_id == origin.result_id:
                continue
            if self._is_match(item, PEAK_KEYWORDS):
                return item
        return None

    def _select_turn(self, results: List[SearchResult], origin: Optional[SearchResult]) -> Optional[SearchResult]:
        for item in sorted(results, key=self._sort_key):
            if origin is not None and item.published_dt <= origin.published_dt:
                continue
            if item.is_high_trust and self._is_match(item, TURN_KEYWORDS):
                return item
        return None

    def _select_clarification(self, results: List[SearchResult], origin: Optional[SearchResult]) -> Optional[SearchResult]:
        for item in sorted(results, key=self._sort_key):
            if origin is not None and item.published_dt <= origin.published_dt:
                continue
            if item.is_high_trust and self._is_match(item, CLARIFICATION_KEYWORDS):
                return item
        return None

    def _build_selection_reason(self, node_type: str, result: SearchResult) -> str:
        reasons = {
            "origin": "这是当前检索结果里最早能稳定锚定事件的关键节点。",
            "amplification": "该节点说明信息已开始被二次转载或放大传播。",
            "peak": "该节点代表传播热度进入更大范围的放大阶段。",
            "turn": "该节点把传播链从传闻或报道推进到回应/纠偏阶段。",
            "clarification": "该节点补充了事件后续说明或恢复信息。",
        }
        reason = reasons[node_type]
        if result.merged_result_ids:
            reason += f" 同时归并了 {len(result.merged_result_ids)} 条转载或近重复结果。"
        return reason

    def _looks_like_rumor(self, result: SearchResult) -> bool:
        return self._is_match(result, ("传闻", "爆料", "截图", "称", "网传")) or result.source_tier in {"B", "C"}

    def _query_overlap(self, result: SearchResult, query: str) -> int:
        terms = [term for term in re.split(r"\s+", query) if len(term) >= 2]
        haystack = f"{result.title} {result.snippet} {result.source_name}"
        return sum(1 for term in terms if term in haystack)

    def _is_match(self, result: SearchResult, keywords: tuple[str, ...]) -> bool:
        haystack = f"{result.title} {result.snippet}"
        return any(keyword in haystack for keyword in keywords)

    def _sort_key(self, result: SearchResult) -> tuple[str, int, str]:
        return (result.published_at, -result.tier_weight, result.result_id)
