from __future__ import annotations

import re
from typing import List, Tuple

from backend.app.models.schemas import AnalyzeRequest, ClaimItem, ClaimResult, EvidenceItem, NormalizedEvent
from backend.app.services.retrieval_models import RetrievalBundle
from backend.app.services.scenario_library import ScenarioTemplate, match_scenario

NEGATION_MARKERS = ("辟谣", "不实", "否认", "系谣言", "假消息", "并未", "未去世", "仍在救治", "谣言")


class VerdictEngine:
    def evaluate(
        self,
        *,
        request: AnalyzeRequest,
        event: NormalizedEvent,
        claims: List[ClaimItem],
        retrieval_bundle: RetrievalBundle | None = None,
    ) -> Tuple[List[ClaimResult], List[EvidenceItem], str]:
        scenario = match_scenario(" ".join(filter(None, [event.raw_input, event.title, event.summary])))
        evidence_pool, evidence_grade = self._resolve_evidence_pool(
            request=request,
            event=event,
            scenario=scenario,
            retrieval_bundle=retrieval_bundle,
        )

        results: List[ClaimResult] = []
        for claim in claims:
            if claim.claim_type in {"opinion", "prediction", "unverifiable"}:
                results.append(
                    ClaimResult(
                        claim=claim.claim,
                        claim_type=claim.claim_type,
                        verdict="insufficient",
                        confidence="low",
                        evidence=[],
                        notes=self._non_decidable_note(claim.claim_type),
                    )
                )
                continue

            if not evidence_pool:
                results.append(
                    ClaimResult(
                        claim=claim.claim,
                        claim_type=claim.claim_type,
                        verdict="insufficient",
                        confidence="low",
                        evidence=[],
                        notes="当前输入缺少可核验的证据链，先保持保守。",
                    )
                )
                continue

            verdict, confidence, notes, selected = self._evaluate_fact_claim(
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
                    evidence=selected,
                    notes=notes,
                )
            )

        return results, evidence_pool, evidence_grade

    def _resolve_evidence_pool(
        self,
        *,
        request: AnalyzeRequest,
        event: NormalizedEvent,
        scenario: ScenarioTemplate,
        retrieval_bundle: RetrievalBundle | None = None,
    ) -> Tuple[List[EvidenceItem], str]:
        if request.mock_evidence:
            return list(request.mock_evidence), "B"
        if retrieval_bundle and retrieval_bundle.canonical_results:
            return retrieval_bundle.to_evidence_items(), retrieval_bundle.evidence_grade
        if event.input_type == "question_only":
            return [], "D"
        if event.fallback_used and event.input_type in {"url_news", "url_unknown"}:
            return [], "D"
        return list(scenario.evidence), scenario.default_evidence_grade

    def _non_decidable_note(self, claim_type: str) -> str:
        if claim_type == "opinion":
            return "这是评价性说法，当前不做真假强判。"
        if claim_type == "prediction":
            return "这是未来判断，当前证据不足。"
        return "这是公开资料难以直接核验的说法。"

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

        return self._evaluate_generic_claim(claim_text, evidence_pool)

    def _evaluate_generic_claim(
        self,
        claim_text: str,
        evidence_pool: List[EvidenceItem],
    ) -> Tuple[str, str, str, List[EvidenceItem]]:
        claim_terms = self._extract_terms(self._normalize_claim(claim_text))
        if not claim_terms:
            return "insufficient", "low", "当前 claim 过于模糊，无法与公开来源稳定对齐。", evidence_pool[:1]

        supporting: List[EvidenceItem] = []
        refuting: List[EvidenceItem] = []
        for item in evidence_pool:
            haystack = self._normalize_claim(f"{item.title} {item.snippet} {item.relevance_reason}")
            overlap = [term for term in claim_terms if term in haystack]
            if len(overlap) < 2 and not (len(claim_terms) == 1 and overlap):
                continue
            if any(marker in haystack for marker in NEGATION_MARKERS):
                refuting.append(item)
            else:
                supporting.append(item)

        if supporting and refuting:
            return "conflicting", "medium", "公开来源中同时出现了支持和否定线索，当前应保持冲突态。", (refuting + supporting)[:2]
        if refuting:
            confidence = "high" if any(item.source_tier in {"S", "A"} for item in refuting) else "medium"
            return "refuted", confidence, "检索到与该说法高度相关的辟谣或否认来源，当前更倾向于判定为不成立。", refuting[:2]
        if supporting:
            high_trust_hits = sum(1 for item in supporting if item.source_tier in {"S", "A"})
            confidence = "high" if high_trust_hits >= 2 else "medium" if high_trust_hits >= 1 else "low"
            return "supported", confidence, "检索到与该说法高度相关的公开来源，当前更倾向于判定为成立。", supporting[:2]
        return "insufficient", "low", "检索结果与该说法的语义重合仍不足，先保持保守。", evidence_pool[:1]

    def _normalize_claim(self, text: str) -> str:
        normalized = text.strip().lower()
        replacements = (
            ("是不是", ""),
            ("有没有", ""),
            ("最近", ""),
            ("有一个", ""),
            ("死掉了", "死亡"),
            ("死掉", "死亡"),
            ("？", ""),
            ("?", ""),
            ("。", ""),
        )
        for old, new in replacements:
            normalized = normalized.replace(old, new)
        return normalized

    def _extract_terms(self, text: str) -> List[str]:
        ordered: List[str] = []
        seen = set()

        def push(term: str) -> None:
            if len(ordered) >= 24:
                return
            if term and term not in seen:
                seen.add(term)
                ordered.append(term)

        for term in re.findall(r"[a-z0-9]{2,}", text):
            push(term)

        for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", text):
            if len(chunk) <= 4:
                push(chunk)
                continue
            for window in (4, 3, 2):
                if len(chunk) < window:
                    continue
                for index in range(0, len(chunk) - window + 1):
                    push(chunk[index : index + window])
                    if len(ordered) >= 24:
                        return ordered

        return ordered

