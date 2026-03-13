from __future__ import annotations

from typing import List, Tuple

from backend.app.models.schemas import ClaimResult, Event, EvidenceItem, NormalizedEvent, Report, TimelineNode
from backend.app.services.contract_utils import default_source_name, default_source_url, ensure_datetime_string


class ReportBuilder:
    def build(
        self,
        *,
        event: NormalizedEvent,
        claim_results: List[ClaimResult],
        timeline: List[TimelineNode],
        evidence: List[EvidenceItem],
        evidence_grade: str,
    ) -> Report:
        mode = self._select_mode(
            event=event,
            claim_results=claim_results,
            timeline=timeline,
            evidence_grade=evidence_grade,
        )
        final_summary, risks = self._compose_sections(
            mode=mode,
            event=event,
            claim_results=claim_results,
            timeline=timeline,
            evidence=evidence,
        )

        public_event = Event(
            title=event.title or "待核实事件",
            summary=event.summary,
            source_url=event.source_url or default_source_url(event.input_type, event.raw_input),
            source_name=event.source_name or default_source_name(event.input_type),
            published_at=ensure_datetime_string(event.published_at),
            keywords=event.keywords or ["待核实"],
            mode=mode,
        )

        return Report(
            mode=mode,
            event=public_event,
            claim_results=claim_results,
            timeline=timeline,
            sources=evidence,
            final_summary=final_summary,
            risks=risks,
        )

    def _select_mode(
        self,
        *,
        event: NormalizedEvent,
        claim_results: List[ClaimResult],
        timeline: List[TimelineNode],
        evidence_grade: str,
    ) -> str:
        decisive_count = sum(1 for item in claim_results if item.verdict in {"supported", "refuted", "conflicting"})
        if event.input_type == "question_only" and decisive_count == 0:
            return "safe_mode"
        if decisive_count == 0 and event.fallback_used:
            return "safe_mode"
        if evidence_grade in {"A", "S"} and decisive_count >= 2 and len(timeline) >= 2 and not event.fallback_used:
            return "complete_mode"
        if decisive_count == 0:
            return "safe_mode"
        return "partial_mode"

    def _compose_sections(
        self,
        *,
        mode: str,
        event: NormalizedEvent,
        claim_results: List[ClaimResult],
        timeline: List[TimelineNode],
        evidence: List[EvidenceItem],
    ) -> Tuple[str, List[str]]:
        strong_claims = [item for item in claim_results if item.verdict in {"supported", "refuted", "conflicting"}]
        conflicting_claims = [item for item in claim_results if item.verdict == "conflicting"]

        if mode == "complete_mode":
            headline = strong_claims[0].claim if strong_claims else event.summary
            summary = f"当前高可信证据已支撑主链路，核心结论围绕“{headline}”展开。"
        elif mode == "partial_mode":
            summary = "当前已有部分可核验结论，但证据链或时间线仍不完整，需要保留边界。"
        else:
            summary = "当前信息不足以给出确定性判断，系统保持 safe mode，并优先提示待补证据。"

        risks: List[str] = []
        if conflicting_claims:
            risks.append("存在相互冲突的证据，不能把单一版本当成最终事实。")
        if event.fallback_used:
            risks.append("当前结果基于链接片段或用户输入做保守输出，正文抽取与检索链路仍未完成。")
        if not evidence:
            risks.append("尚未形成稳定证据链。")
        if mode == "safe_mode":
            risks.append("当前页面只适合提示待核查点，不应被当作定性结论。")
        if not timeline:
            risks.append("时间线未建立成功，当前结果不代表完整传播链。")

        return summary, risks
