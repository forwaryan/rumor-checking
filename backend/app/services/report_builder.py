from __future__ import annotations

from typing import List, Tuple

from backend.app.models.schemas import ClaimResult, EventDraft, EvidenceItem, Report, TimelineNode


class ReportBuilder:
    def build(
        self,
        *,
        event: EventDraft,
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
        final_summary, risks, unknowns, next_steps = self._compose_sections(
            mode=mode,
            event=event,
            claim_results=claim_results,
            timeline=timeline,
            evidence=evidence,
        )

        fallback = None
        if event.fallback_used:
            fallback = {
                "used": True,
                "reason": event.fallback_reason,
                "message": "链接正文不完整，当前结果基于标题、摘要片段和规则推断。",
            }

        return Report(
            mode=mode,
            event=event,
            claim_results=claim_results,
            timeline=timeline,
            evidence=evidence,
            final_summary=final_summary,
            risks=risks,
            unknowns=unknowns,
            next_steps=next_steps,
            boundary="当前结果基于 mock 规则和最小测试集生成，尚未接入真实全网检索与 Kimi provider。",
            fallback=fallback,
        )

    def _select_mode(
        self,
        *,
        event: EventDraft,
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
        event: EventDraft,
        claim_results: List[ClaimResult],
        timeline: List[TimelineNode],
        evidence: List[EvidenceItem],
    ) -> Tuple[str, List[str], List[str], List[str]]:
        strong_claims = [item for item in claim_results if item.verdict in {"supported", "refuted", "conflicting"}]
        insufficient_claims = [item for item in claim_results if item.verdict == "insufficient" or item.status != "decidable"]
        conflicting_claims = [item for item in claim_results if item.verdict == "conflicting"]

        if mode == "complete_mode":
            headline = strong_claims[0].claim if strong_claims else event.summary
            summary = f"当前高可信证据已支撑主链路，核心结论围绕“{headline}”展开。"
        elif mode == "partial_mode":
            summary = "当前已有部分可核验结论，但证据链或时间线仍不完整，需要保留边界。"
        else:
            summary = "当前信息不足以给出确定性判断，系统保持 safe mode，并优先提示待补证据。"

        risks = []
        if conflicting_claims:
            risks.append("存在相互冲突的证据，不能把单一版本当成最终事实。")
        if event.fallback_used:
            risks.append("链接正文抽取不完整，分析结果依赖片段信息。")
        if not evidence:
            risks.append("尚未形成稳定证据链。")

        unknowns = [item.claim for item in insufficient_claims[:3]]
        if not unknowns and not timeline:
            unknowns.append("尚未建立传播链和关键时间节点。")

        next_steps = []
        if mode == "safe_mode":
            next_steps.extend(
                [
                    "补充完整正文或权威来源链接后重新分析。",
                    "若是截图传闻，请提供原始通知、机构声明或更完整上下文。",
                ]
            )
        else:
            next_steps.append("继续补充更高可信来源，确认关键节点是否存在遗漏。")
        if conflicting_claims:
            next_steps.append("针对冲突结论优先核对官方通报和一手机构回应。")

        return summary, risks, unknowns, next_steps
