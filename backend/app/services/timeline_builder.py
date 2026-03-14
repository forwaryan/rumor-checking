from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import List, Optional, Sequence

from backend.app.models.schemas import NormalizedEvent, TimelineNode, TimelineSourceType
from backend.app.services.contract_utils import ensure_datetime_string
from backend.app.services.retrieval_models import RetrievalBundle, SearchResult

TURN_KEYWORDS = ("回应", "否认", "辟谣", "澄清", "调查", "核查", "纠正", "致歉", "responds", "denies")
CLARIFICATION_KEYWORDS = ("说明", "更新", "通报", "公告", "答复", "恢复", "补充", "statement", "update", "clarifies")
AMPLIFICATION_KEYWORDS = ("传闻", "爆料", "网传", "截图", "热议", "发酵", "转发", "转载", "刷屏", "疯传", "rumor", "viral")
PEAK_KEYWORDS = ("热议", "刷屏", "持续", "发酵", "引发关注", "冲上热搜", "widely shared", "viral")
RUMOR_KEYWORDS = ("传闻", "爆料", "网传", "截图", "谣言", "疯传", "rumor", "leak", "viral")
OFFICIAL_SOURCE_MARKERS = ("政府", "监管局", "教育局", "交通局", "公安", "法院", "学校", "医院", "委员会", "市场监管", "官方", "company", "official")


@dataclass(frozen=True)
class TimelineBuild:
    nodes: List[TimelineNode]
    source: TimelineSourceType


class TimelineBuilder:
    def build(self, event: NormalizedEvent, retrieval_bundle: RetrievalBundle | None = None) -> List[TimelineNode]:
        return self.build_with_source(event, retrieval_bundle=retrieval_bundle).nodes

    def build_with_source(self, event: NormalizedEvent, retrieval_bundle: RetrievalBundle | None = None) -> TimelineBuild:
        if retrieval_bundle and retrieval_bundle.canonical_results:
            retrieval_timeline = self._build_from_retrieval(retrieval_bundle)
            if retrieval_timeline:
                return TimelineBuild(nodes=retrieval_timeline, source="retrieval")

        if event.input_type == "question_only" or event.fallback_used:
            return TimelineBuild(nodes=[], source="none")

        return TimelineBuild(
            nodes=[
                TimelineNode(
                    node_type="origin",
                    title=event.title or "输入内容进入分析队列",
                    url=event.source_url or "https://example.org/input/manual-input",
                    source_name=event.source_name or "用户提供输入",
                    published_at=ensure_datetime_string(event.published_at),
                    summary=event.summary,
                    why_selected="这是当前唯一稳定的输入锚点，尚未扩展到外部检索节点。",
                )
            ],
            source="input_seed",
        )

    def _build_from_retrieval(self, retrieval_bundle: RetrievalBundle) -> List[TimelineNode]:
        results = list(sorted(retrieval_bundle.canonical_results, key=self._sort_key))
        if not results:
            return []

        origin = self._select_origin(results, retrieval_bundle.query)
        turn = self._select_turn(results, origin)
        clarification = self._select_clarification(results, origin, turn)
        amplification = self._select_amplification(results, origin)
        peak = self._select_peak(results, origin)

        candidates: list[tuple[str, Optional[SearchResult]]] = [
            ("origin", origin),
            ("amplification", amplification),
            ("turn", turn),
            ("clarification", clarification),
            ("peak", peak),
        ]

        timeline_nodes: list[TimelineNode] = []
        selected_ids: set[str] = set()
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
                    why_selected=self._build_selection_reason(
                        node_type=node_type,
                        result=result,
                        results=results,
                        query=retrieval_bundle.query,
                        origin=origin,
                        turn=turn,
                    ),
                )
            )

        return sorted(timeline_nodes, key=lambda item: (item.published_at, item.node_type))[:10]

    def _select_origin(self, results: Sequence[SearchResult], query: str) -> SearchResult:
        ordered = list(sorted(results, key=self._sort_key))
        first_authoritative_response = self._first_authoritative_response(ordered)
        rumor_candidates = [
            item
            for item in ordered
            if self._looks_like_rumor(item)
            and self._query_overlap(item, query) >= 1
            and (first_authoritative_response is None or item.published_dt <= first_authoritative_response.published_dt)
        ]
        if rumor_candidates:
            return sorted(rumor_candidates, key=lambda item: (item.published_at, -self._query_overlap(item, query), item.result_id))[0]

        authoritative_candidates = [item for item in ordered if item.is_high_trust or self._looks_official(item)]
        if authoritative_candidates:
            earliest_day = authoritative_candidates[0].published_at[:10]
            same_day = [item for item in authoritative_candidates if item.published_at[:10] == earliest_day]
            return sorted(same_day, key=lambda item: (-item.tier_weight, item.published_at, item.result_id))[0]
        return ordered[0]

    def _select_amplification(self, results: Sequence[SearchResult], origin: Optional[SearchResult]) -> Optional[SearchResult]:
        if origin is None:
            return None
        candidates = []
        for item in sorted(results, key=self._sort_key):
            if item.result_id == origin.result_id or item.published_dt < origin.published_dt:
                continue
            if item.is_high_trust and not item.merged_result_ids:
                continue
            if self._is_match(item, AMPLIFICATION_KEYWORDS) or item.merged_result_ids or item.source_tier in {"B", "C"}:
                candidates.append(item)
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda item: (
                0 if self._is_match(item, AMPLIFICATION_KEYWORDS) else 1,
                0 if item.merged_result_ids else 1,
                item.published_at,
                item.result_id,
            ),
        )[0]

    def _select_peak(self, results: Sequence[SearchResult], origin: Optional[SearchResult]) -> Optional[SearchResult]:
        if origin is None or len(results) < 4:
            return None
        post_origin = [item for item in results if item.published_dt >= origin.published_dt]
        if len(post_origin) < 3:
            return None
        counts = Counter(item.published_at[:10] for item in post_origin)
        peak_day, peak_count = max(counts.items(), key=lambda item: (item[1], item[0]))
        if peak_count < 2:
            return None
        day_candidates = [item for item in post_origin if item.published_at[:10] == peak_day and item.result_id != origin.result_id]
        if not day_candidates:
            return None
        return sorted(
            day_candidates,
            key=lambda item: (
                0 if self._is_match(item, PEAK_KEYWORDS) else 1,
                -len(item.merged_result_ids),
                -item.tier_weight,
                item.published_at,
            ),
        )[0]

    def _select_turn(self, results: Sequence[SearchResult], origin: Optional[SearchResult]) -> Optional[SearchResult]:
        candidates = []
        for item in sorted(results, key=self._sort_key):
            if origin is not None and item.published_dt <= origin.published_dt:
                continue
            if item.is_high_trust and (self._is_match(item, TURN_KEYWORDS) or self._looks_official(item)):
                candidates.append(item)
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda item: (
                0 if self._is_match(item, TURN_KEYWORDS) else 1,
                item.published_at,
                -item.tier_weight,
                item.result_id,
            ),
        )[0]

    def _select_clarification(
        self,
        results: Sequence[SearchResult],
        origin: Optional[SearchResult],
        turn: Optional[SearchResult],
    ) -> Optional[SearchResult]:
        boundary = turn or origin
        candidates = []
        for item in sorted(results, key=self._sort_key):
            if boundary is not None and item.published_dt <= boundary.published_dt:
                continue
            if item.is_high_trust and (self._is_match(item, CLARIFICATION_KEYWORDS) or self._looks_official(item)):
                candidates.append(item)
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda item: (
                0 if self._is_match(item, CLARIFICATION_KEYWORDS) else 1,
                item.published_at,
                -item.tier_weight,
                item.result_id,
            ),
        )[0]

    def _first_authoritative_response(self, results: Sequence[SearchResult]) -> Optional[SearchResult]:
        for item in sorted(results, key=self._sort_key):
            if item.is_high_trust and (self._is_match(item, TURN_KEYWORDS) or self._is_match(item, CLARIFICATION_KEYWORDS) or self._looks_official(item)):
                return item
        return None

    def _build_selection_reason(
        self,
        *,
        node_type: str,
        result: SearchResult,
        results: Sequence[SearchResult],
        query: str,
        origin: Optional[SearchResult],
        turn: Optional[SearchResult],
    ) -> str:
        reasons: list[str] = []
        earliest = min(results, key=self._sort_key)

        if node_type == "origin":
            reasons.append("它是当前可检索公开来源中最早进入关键叙事的节点")
            if result.result_id == earliest.result_id:
                reasons.append("发布时间在候选结果里最靠前")
            if self._looks_like_rumor(result):
                reasons.append("出现在权威回应前，并带有传闻/爆料信号")
            elif result.is_high_trust or self._looks_official(result):
                reasons.append(f"来源可信度较高（{result.source_tier} 级），可作为起点锚点")
            if self._query_overlap(result, query) >= 2:
                reasons.append("标题与查询核心实体高度重合")
        elif node_type == "amplification":
            reasons.append("它代表信息从起点进入二次扩散阶段")
            if result.source_tier in {"B", "C"}:
                reasons.append("来源可信度较低，更接近传播放大节点而非事实锚点")
            if self._is_match(result, AMPLIFICATION_KEYWORDS):
                reasons.append("标题或摘要出现了发酵、转发、传闻等扩散信号")
            if result.merged_result_ids:
                reasons.append(f"归并了 {len(result.merged_result_ids)} 条转载或近重复结果")
        elif node_type == "peak":
            reasons.append("它位于当前结果最密集的报道时间窗口")
            if self._is_match(result, PEAK_KEYWORDS):
                reasons.append("文本中带有热议或持续发酵信号")
            if result.merged_result_ids:
                reasons.append("同一窗口内还有多条相似报道被归并到这一节点")
        elif node_type == "turn":
            reasons.append("它让叙事从传闻/报道推进到回应或纠偏阶段")
            if origin is not None and result.published_dt > origin.published_dt:
                reasons.append("发布时间晚于 origin，符合传播链转折顺序")
            if result.is_high_trust:
                reasons.append(f"由高可信来源发出（{result.source_tier} 级）")
            if self._is_match(result, TURN_KEYWORDS):
                reasons.append("文本明确出现回应、否认、核查或致歉信号")
        elif node_type == "clarification":
            reasons.append("它补充了转折之后的官方说明或后续更新")
            if turn is not None and result.published_dt > turn.published_dt:
                reasons.append("发布时间位于 turn 之后，承担后续澄清角色")
            if result.is_high_trust:
                reasons.append(f"来源可信度较高（{result.source_tier} 级）")
            if self._is_match(result, CLARIFICATION_KEYWORDS):
                reasons.append("文本出现说明、通报、更新或恢复等澄清信号")

        if result.merged_result_ids and node_type not in {"amplification", "peak"}:
            reasons.append(f"该节点还归并了 {len(result.merged_result_ids)} 条相似结果")
        return "；".join(dict.fromkeys(reasons)) + "。"

    def _looks_official(self, result: SearchResult) -> bool:
        haystack = f"{result.source_name} {result.title}".lower()
        return result.is_high_trust or any(marker in haystack for marker in OFFICIAL_SOURCE_MARKERS)

    def _looks_like_rumor(self, result: SearchResult) -> bool:
        return self._is_match(result, RUMOR_KEYWORDS) or result.source_tier == "C"

    def _query_overlap(self, result: SearchResult, query: str) -> int:
        terms = [term for term in re.split(r"\s+", query) if len(term) >= 2]
        haystack = f"{result.title} {result.snippet} {result.source_name}".lower()
        return sum(1 for term in terms if term.lower() in haystack)

    def _is_match(self, result: SearchResult, keywords: tuple[str, ...]) -> bool:
        haystack = f"{result.title} {result.snippet} {result.source_name}".lower()
        return any(keyword.lower() in haystack for keyword in keywords)

    def _sort_key(self, result: SearchResult) -> tuple[str, int, str]:
        return (result.published_at, -result.tier_weight, result.result_id)
