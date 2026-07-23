from __future__ import annotations

import re
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
COMPLETENESS_WEIGHTS = {
    "origin": 30,
    "amplification": 15,
    "peak": 15,
    "turn": 20,
    "clarification": 20,
}


@dataclass(frozen=True)
class TimelineBuild:
    nodes: List[TimelineNode]
    source: TimelineSourceType
    completeness: int = 0
    confidence: int = 0


class TimelineBuilder:
    def build(self, event: NormalizedEvent, retrieval_bundle: RetrievalBundle | None = None) -> List[TimelineNode]:
        return self.build_with_source(event, retrieval_bundle=retrieval_bundle).nodes

    def build_with_source(self, event: NormalizedEvent, retrieval_bundle: RetrievalBundle | None = None) -> TimelineBuild:
        if retrieval_bundle and retrieval_bundle.canonical_results:
            retrieval_timeline = self._build_from_retrieval(retrieval_bundle)
            if retrieval_timeline.nodes:
                return retrieval_timeline

        if event.input_type == "question_only" or event.fallback_used:
            return TimelineBuild(nodes=[], source="none", completeness=0, confidence=0)

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
            completeness=20,
            confidence=10,
        )

    def _build_from_retrieval(self, retrieval_bundle: RetrievalBundle) -> TimelineBuild:
        results = list(sorted(retrieval_bundle.canonical_results, key=self._sort_key))
        if not results:
            return TimelineBuild(nodes=[], source="none", completeness=0, confidence=0)

        origin = self._select_origin(results, retrieval_bundle.query)
        amplification = self._select_amplification(results, origin)
        peak = self._select_peak(results, origin)
        turn = self._select_turn(results, origin)
        clarification = self._select_clarification(results, origin, turn)

        candidates: list[tuple[str, Optional[SearchResult]]] = [
            ("origin", origin),
            ("amplification", amplification),
            ("peak", peak),
            ("turn", turn),
            ("clarification", clarification),
        ]

        timeline_nodes: list[TimelineNode] = []
        selected_results: list[SearchResult] = []
        selected_ids: set[str] = set()
        for node_type, result in candidates:
            if result is None or result.result_id in selected_ids:
                continue
            selected_ids.add(result.result_id)
            selected_results.append(result)
            timeline_nodes.append(
                TimelineNode(
                    node_type=node_type,
                    title=result.title,
                    url=result.url,
                    source_name=result.source_name,
                    published_at=ensure_datetime_string(result.published_at),
                    summary=result.snippet,
                    why_selected=self._build_selection_reason(
                        node_type=node_type,
                        result=result,
                        results=results,
                        retrieval_bundle=retrieval_bundle,
                        origin=origin,
                        turn=turn,
                    ),
                )
            )

        timeline_nodes = sorted(timeline_nodes, key=lambda item: (item.published_at, item.node_type))[:10]
        completeness = self._compute_completeness(timeline_nodes)
        confidence = self._compute_confidence(retrieval_bundle, selected_results, completeness)
        return TimelineBuild(
            nodes=timeline_nodes,
            source="retrieval",
            completeness=completeness,
            confidence=confidence,
        )

    def _select_origin(self, results: Sequence[SearchResult], query: str) -> SearchResult:
        ordered = list(sorted(results, key=self._sort_key))
        first_authoritative_response = self._first_authoritative_response(ordered)
        rumor_candidates = [
            item
            for item in ordered
            if self._looks_like_rumor(item)
            and not item.is_repost_like
            and self._query_overlap(item, query) >= 1
            and (first_authoritative_response is None or item.effective_published_dt <= first_authoritative_response.effective_published_dt)
        ]
        if rumor_candidates:
            return sorted(
                rumor_candidates,
                key=lambda item: (
                    item.effective_published_at,
                    0 if not item.is_aggregator_source else 1,
                    -self._query_overlap(item, query),
                    -item.tier_weight,
                    item.result_id,
                ),
            )[0]

        authoritative_candidates = [
            item for item in ordered if (item.is_high_trust or self._looks_official(item)) and not item.is_repost_like
        ]
        if authoritative_candidates:
            return sorted(
                authoritative_candidates,
                key=lambda item: (
                    item.effective_published_at,
                    0 if item.is_official_source else 1,
                    -item.tier_weight,
                    item.result_id,
                ),
            )[0]
        return ordered[0]

    def _select_amplification(self, results: Sequence[SearchResult], origin: Optional[SearchResult]) -> Optional[SearchResult]:
        if origin is None:
            return None
        candidates = []
        for item in sorted(results, key=self._sort_key):
            if item.result_id == origin.result_id or item.effective_published_dt < origin.effective_published_dt:
                continue
            if item.has_response_signal and item.source_tier == "S":
                continue
            if (
                item.propagation_score >= 3
                or item.is_aggregator_source
                or item.is_mainstream_source
                or item.source_tier in {"A", "B"}
                or self._is_match(item, AMPLIFICATION_KEYWORDS)
            ):
                candidates.append(item)
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda item: (
                0 if item.is_aggregator_source else 1,
                0 if not item.has_response_signal else 1,
                0 if self._is_match(item, AMPLIFICATION_KEYWORDS) else 1,
                -item.propagation_score,
                item.effective_published_at,
                item.result_id,
            ),
        )[0]

    def _select_peak(self, results: Sequence[SearchResult], origin: Optional[SearchResult]) -> Optional[SearchResult]:
        if origin is None or len(results) < 3:
            return None
        post_origin = [item for item in results if item.effective_published_dt >= origin.effective_published_dt]
        if len(post_origin) < 3:
            return None
        day_scores = self._day_scores(post_origin)
        peak_day, peak_score = max(day_scores.items(), key=lambda item: (item[1], item[0]))
        if peak_score < 3:
            return None
        day_candidates = [
            item for item in post_origin if item.effective_published_at[:10] == peak_day and item.result_id != origin.result_id
        ]
        if not day_candidates:
            return None
        return sorted(
            day_candidates,
            key=lambda item: (
                0 if self._is_match(item, PEAK_KEYWORDS) else 1,
                -item.propagation_score,
                0 if item.is_mainstream_source or item.is_aggregator_source else 1,
                item.effective_published_at,
                item.result_id,
            ),
        )[0]

    def _select_turn(self, results: Sequence[SearchResult], origin: Optional[SearchResult]) -> Optional[SearchResult]:
        candidates = []
        for item in sorted(results, key=self._sort_key):
            if origin is not None and item.effective_published_dt <= origin.effective_published_dt:
                continue
            if item.has_response_signal or item.is_official_source:
                candidates.append(item)
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda item: (
                0 if item.is_official_source else 1,
                0 if item.has_response_signal else 1,
                item.effective_published_at,
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
            if boundary is not None and item.effective_published_dt <= boundary.effective_published_dt:
                continue
            if item.is_high_trust and (self._is_match(item, CLARIFICATION_KEYWORDS) or item.has_response_signal):
                candidates.append(item)
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda item: (
                0 if self._is_match(item, CLARIFICATION_KEYWORDS) else 1,
                item.effective_published_at,
                -item.tier_weight,
                item.result_id,
            ),
        )[0]

    def _first_authoritative_response(self, results: Sequence[SearchResult]) -> Optional[SearchResult]:
        for item in sorted(results, key=self._sort_key):
            if item.is_high_trust and (item.has_response_signal or self._looks_official(item)):
                return item
        return None

    def _build_selection_reason(
        self,
        *,
        node_type: str,
        result: SearchResult,
        results: Sequence[SearchResult],
        retrieval_bundle: RetrievalBundle,
        origin: Optional[SearchResult],
        turn: Optional[SearchResult],
    ) -> str:
        reasons: list[str] = []
        earliest = min(results, key=self._sort_key)
        same_day_results = [item for item in results if item.effective_published_at[:10] == result.effective_published_at[:10]]
        same_day_independent = len({item.effective_independence_key for item in same_day_results if item.effective_independence_key})

        if node_type == "origin":
            reasons.append("它是当前可检索公开来源里最早进入关键叙事的节点")
            if result.result_id == earliest.result_id:
                reasons.append("发布时间在候选结果中最靠前")
            if result.has_rumor_signal:
                reasons.append("文本带有传闻/爆料信号，且位于权威回应之前")
            elif result.is_official_source:
                reasons.append("来源属于官方或原始声明方，可作为事实起点锚点")
            if result.is_repost_like:
                reasons.append("虽然文本像转载，但它仍是当前最早可见的公开节点")
        elif node_type == "amplification":
            reasons.append("它代表信息从起点进入二次扩散阶段")
            reasons.append(f"传播强度代理信号为 {result.propagation_score}，高于普通候选结果")
            if result.is_aggregator_source:
                reasons.append("来源更像聚合/转载页，符合放大节点特征")
            if result.merged_result_ids:
                reasons.append(f"归并了 {len(result.merged_result_ids)} 条重复或转载结果")
        elif node_type == "peak":
            reasons.append("它位于当前结果最密集的传播时间窗口")
            reasons.append(f"同日覆盖 {len(same_day_results)} 条候选结果、{same_day_independent} 个独立来源")
            reasons.append(f"该节点的传播强度代理信号为 {result.propagation_score}")
            if self._is_match(result, PEAK_KEYWORDS):
                reasons.append("文本中带有热议、持续发酵或刷屏等峰值信号")
        elif node_type == "turn":
            reasons.append("它让叙事从传闻/报道推进到回应或纠偏阶段")
            if origin is not None and result.effective_published_dt > origin.effective_published_dt:
                reasons.append("发布时间晚于 origin，符合传播链转折顺序")
            if result.is_official_source:
                reasons.append("这是官方回应节点，不只是媒体转述")
            elif result.is_high_trust:
                reasons.append("这是主流媒体跟进节点，承担从传闻转向核实的角色")
            if result.has_response_signal:
                reasons.append("文本明确出现回应、否认、核查或辟谣信号")
        elif node_type == "clarification":
            reasons.append("它补充了转折之后的官方说明或后续更新")
            if turn is not None and result.effective_published_dt > turn.effective_published_dt:
                reasons.append("发布时间位于 turn 之后，承担后续澄清角色")
            if result.is_official_source:
                reasons.append("来源属于官方/当事方，适合承接最终说明")
            elif result.is_high_trust:
                reasons.append("来源可信度较高，适合承接后续说明")
            if self._is_match(result, CLARIFICATION_KEYWORDS):
                reasons.append("文本出现说明、通报、更新或恢复等澄清信号")

        if result.effective_independence_key:
            reasons.append(f"来源独立域为 {result.effective_independence_key}")
        if "rumor_vs_response" in retrieval_bundle.conflict_signals and result.has_rumor_signal:
            reasons.append("当前检索同时存在传闻与回应，适合作为传播侧节点而非最终结论")
        return "；".join(dict.fromkeys(reasons)) + "。"

    def _compute_completeness(self, nodes: Sequence[TimelineNode]) -> int:
        score = 0
        for node in nodes:
            score += COMPLETENESS_WEIGHTS.get(node.node_type, 0)
        return min(score, 100)

    def _compute_confidence(
        self,
        retrieval_bundle: RetrievalBundle,
        selected_results: Sequence[SearchResult],
        completeness: int,
    ) -> int:
        score = completeness * 0.45
        score += min(25, retrieval_bundle.independent_source_count * 7)
        score += min(20, retrieval_bundle.high_trust_result_count * 6)
        score += min(10, len(selected_results) * 2)
        if any(item.is_official_source for item in selected_results):
            score += 8
        if any(item.has_response_signal for item in selected_results):
            score += 6
        if any(item.propagation_score >= 3 for item in selected_results):
            score += 4
        if "single_source_cluster" in retrieval_bundle.conflict_signals:
            score -= 18
        if retrieval_bundle.official_result_count == 0 and retrieval_bundle.mainstream_result_count == 0:
            score -= 12
        return max(0, min(100, int(round(score))))

    def _day_scores(self, results: Sequence[SearchResult]) -> dict[str, int]:
        day_scores: dict[str, int] = {}
        for item in results:
            day = item.effective_published_at[:10]
            day_scores[day] = day_scores.get(day, 0) + item.propagation_score
        return day_scores

    def _looks_official(self, result: SearchResult) -> bool:
        haystack = f"{result.source_name} {result.title}".lower()
        return result.is_high_trust or result.is_official_source or any(marker in haystack for marker in OFFICIAL_SOURCE_MARKERS)

    def _looks_like_rumor(self, result: SearchResult) -> bool:
        return result.has_rumor_signal or self._is_match(result, RUMOR_KEYWORDS) or result.source_tier == "C"

    def _query_overlap(self, result: SearchResult, query: str) -> int:
        terms = [term for term in re.split(r"\s+", query) if len(term) >= 2]
        haystack = f"{result.title} {result.snippet} {result.source_name}".lower()
        return sum(1 for term in terms if term.lower() in haystack)

    def _is_match(self, result: SearchResult, keywords: tuple[str, ...]) -> bool:
        haystack = f"{result.title} {result.snippet} {result.source_name}".lower()
        return any(keyword.lower() in haystack for keyword in keywords)

    def _sort_key(self, result: SearchResult) -> tuple[str, int, str]:
        return (result.effective_published_at, -result.tier_weight, result.result_id)
