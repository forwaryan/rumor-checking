from __future__ import annotations

from typing import List, Tuple

from backend.app.models.schemas import AnalyzeRequest, ClaimItem, ClaimResult, EventDraft, EvidenceItem
from backend.app.services.scenario_library import ScenarioTemplate, match_scenario


class VerdictEngine:
    def evaluate(
        self,
        *,
        request: AnalyzeRequest,
        event: EventDraft,
        claims: List[ClaimItem],
    ) -> Tuple[List[ClaimResult], List[EvidenceItem], str]:
        scenario = match_scenario(" ".join(filter(None, [event.raw_input, event.title, event.summary])))
        evidence_pool, evidence_grade = self._resolve_evidence_pool(
            request=request,
            event=event,
            scenario=scenario,
        )

        results: List[ClaimResult] = []
        for claim in claims:
            if claim.claim_type in {"opinion", "prediction", "unverifiable"}:
                results.append(
                    ClaimResult(
                        claim=claim.claim,
                        claim_type=claim.claim_type,
                        rationale=self._non_decidable_rationale(claim.claim_type),
                        status="not_decidable",
                    )
                )
                continue

            if not evidence_pool:
                results.append(
                    ClaimResult(
                        claim=claim.claim,
                        claim_type=claim.claim_type,
                        rationale="当前输入缺少可核验的证据链，先保持保守。",
                        status="needs_evidence",
                    )
                )
                continue

            verdict, confidence, rationale, selected = self._evaluate_fact_claim(
                scenario=scenario,
                claim_text=claim.claim,
                evidence_pool=evidence_pool,
            )
            results.append(
                ClaimResult(
                    claim=claim.claim,
                    claim_type=claim.claim_type,
                    verdict=verdict,
                    confidence=confidence,
                    rationale=rationale,
                    evidence=selected,
                    status="decidable" if verdict in {"supported", "refuted", "conflicting"} else "needs_review",
                )
            )

        return results, evidence_pool, evidence_grade

    def _resolve_evidence_pool(
        self,
        *,
        request: AnalyzeRequest,
        event: EventDraft,
        scenario: ScenarioTemplate,
    ) -> Tuple[List[EvidenceItem], str]:
        if request.mock_evidence:
            return list(request.mock_evidence), "B"
        if event.input_type == "question_only":
            return [], "D"
        if event.fallback_used and event.input_type == "url_unknown":
            return [], "D"
        return list(scenario.evidence), scenario.default_evidence_grade

    def _non_decidable_rationale(self, claim_type: str) -> str:
        if claim_type == "opinion":
            return "这是立场或评价，不适合进入标准 verdict。"
        if claim_type == "prediction":
            return "这是未来判断，当前证据只能支撑风险提示。"
        return "这是公开资料通常无法直接验证的说法。"

    def _evaluate_fact_claim(
        self,
        *,
        scenario: ScenarioTemplate,
        claim_text: str,
        evidence_pool: List[EvidenceItem],
    ) -> Tuple[str, str, str, List[EvidenceItem]]:
        if scenario.scenario_id == "expired_yogurt":
            if "停业整改" in claim_text:
                return "supported", "high", "官方通报与品牌回应都指向停业整改。", evidence_pool[:2]
            if "2批次酸奶超过保质期" in claim_text or "超过保质期" in claim_text:
                return "supported", "high", "官方抽检通报直接支持该说法。", evidence_pool[:1]
            if "未发现大规模食物中毒病例" in claim_text:
                return "supported", "medium", "现有通报提到未见大规模病例，但仍需后续追踪。", evidence_pool[:1]
            return "insufficient", "low", "当前证据不足以覆盖该具体说法。", evidence_pool[:1]

        if scenario.scenario_id == "ferry_fog":
            if "原因是大雾" in claim_text:
                return "supported", "high", "交通局说明与媒体转述一致。", evidence_pool[:2]
            if "下午恢复运行" in claim_text:
                return "supported", "medium", "媒体补充了恢复运行信息。", evidence_pool[1:2] or evidence_pool[:1]
            return "insufficient", "low", "现有证据主要覆盖停航原因和恢复时间。", evidence_pool[:1]

        if scenario.scenario_id == "morningstar_layoff":
            if "宣布裁员40%" in claim_text:
                return "refuted", "high", "公司声明和财经媒体都否认该比例裁员安排。", evidence_pool[:2]
            return "insufficient", "low", "现有材料不足以支撑更细节的事实判断。", evidence_pool[:1]

        if scenario.scenario_id == "beichuan_school":
            if "缺少正式来源" in claim_text:
                return "supported", "medium", "现有传播内容只有截图和聚合页，来源链不完整。", evidence_pool[:2]
            return "insufficient", "low", "没有权威通知时，不应把传闻判成真或假。", evidence_pool[:2]

        if scenario.scenario_id == "chemical_odor":
            if "连续投诉夜间异味" in claim_text:
                return "supported", "medium", "原始描述与官方核查动作共同说明投诉确实存在。", evidence_pool[:1]
            if "进场核查" in claim_text:
                return "supported", "high", "环保部门材料直接支持该说法。", evidence_pool[:1]
            if "完全停产" in claim_text:
                return "conflicting", "medium", "媒体称停产整顿，但公司回应仅暂停一条产线。", evidence_pool[1:3]
            return "insufficient", "low", "现有证据尚不足以覆盖更多细节。", evidence_pool[:1]

        return "insufficient", "low", "当前规则库尚未覆盖该具体事件。", evidence_pool[:1]
