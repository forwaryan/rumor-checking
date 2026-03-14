from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple

from backend.app.models.schemas import (
    AnalyzeRequest,
    ClaimItem,
    ClaimResult,
    EvidenceItem,
    EvidenceSourceType,
    NormalizedEvent,
)
from backend.app.services.retrieval_models import RetrievalBundle

CLAIM_NEGATION_MARKERS = (
    "辟谣",
    "不实",
    "否认",
    "系谣言",
    "假消息",
    "并未",
    "未发现",
    "未发布",
    "未安排",
    "没有",
    "不存在",
    "仍在救治",
    "缺少正式来源",
    "无正式来源",
    "来源缺失",
    "来源不完整",
    "无完整正文",
)
EVIDENCE_REFUTING_MARKERS = CLAIM_NEGATION_MARKERS + (
    "仅",
    "只有",
    "只暂停",
    "一条产线",
    "部分",
    "正常运行",
    "其余产线正常",
)
SOURCE_GAP_CLAIM_MARKERS = (
    "缺少正式来源",
    "无正式来源",
    "来源缺失",
    "来源不完整",
    "无完整正文",
    "缺少完整正文",
)
SOURCE_GAP_EVIDENCE_MARKERS = SOURCE_GAP_CLAIM_MARKERS + ("截图", "转发", "聚合页", "无落款", "无来源")


@dataclass(frozen=True)
class VerdictEvaluation:
    claim_results: List[ClaimResult]
    evidence: List[EvidenceItem]
    evidence_grade: str
    evidence_source: EvidenceSourceType


class VerdictEngine:
    def evaluate(
        self,
        *,
        request: AnalyzeRequest,
        event: NormalizedEvent,
        claims: List[ClaimItem],
        retrieval_bundle: RetrievalBundle | None = None,
    ) -> Tuple[List[ClaimResult], List[EvidenceItem], str]:
        result = self.evaluate_with_source(
            request=request,
            event=event,
            claims=claims,
            retrieval_bundle=retrieval_bundle,
        )
        return result.claim_results, result.evidence, result.evidence_grade

    def evaluate_with_source(
        self,
        *,
        request: AnalyzeRequest,
        event: NormalizedEvent,
        claims: List[ClaimItem],
        retrieval_bundle: RetrievalBundle | None = None,
    ) -> VerdictEvaluation:
        evidence_pool, evidence_grade, evidence_source = self._resolve_evidence_pool(
            request=request,
            event=event,
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

        return VerdictEvaluation(
            claim_results=results,
            evidence=evidence_pool,
            evidence_grade=evidence_grade,
            evidence_source=evidence_source,
        )

    def _resolve_evidence_pool(
        self,
        *,
        request: AnalyzeRequest,
        event: NormalizedEvent,
        retrieval_bundle: RetrievalBundle | None = None,
    ) -> Tuple[List[EvidenceItem], str, EvidenceSourceType]:
        if request.mock_evidence:
            items = list(request.mock_evidence)
            return items, self._grade_evidence_items(items), "request_mock"
        if retrieval_bundle and retrieval_bundle.canonical_results:
            source: EvidenceSourceType = "retrieval_mock" if retrieval_bundle.provider_name == "mock" else "retrieval_live"
            return retrieval_bundle.to_evidence_items(), retrieval_bundle.evidence_grade, source
        if event.input_type == "question_only":
            return [], "D", "none"
        if event.fallback_used and event.input_type in {"url_news", "url_unknown"}:
            return [], "D", "none"
        return [], "D", "none"

    def _grade_evidence_items(self, evidence_items: List[EvidenceItem]) -> str:
        high_trust_count = sum(1 for item in evidence_items if item.source_tier in {"S", "A"})
        if high_trust_count >= 2:
            return "A"
        if high_trust_count == 1:
            return "B"
        if evidence_items:
            return "C"
        return "D"

    def _non_decidable_note(self, claim_type: str) -> str:
        if claim_type == "opinion":
            return "这是评价性说法，当前不做真假强判。"
        if claim_type == "prediction":
            return "这是未来判断，当前证据不足。"
        return "这是公开资料难以直接核验的说法。"

    def _evaluate_fact_claim(
        self,
        *,
        claim_text: str,
        evidence_pool: List[EvidenceItem],
    ) -> Tuple[str, str, str, List[EvidenceItem]]:
        normalized_claim = self._normalize_claim(claim_text)
        if self._is_source_gap_claim(normalized_claim):
            source_gap_result = self._evaluate_source_gap_claim(evidence_pool)
            if source_gap_result is not None:
                return source_gap_result

        claim_terms = self._extract_terms(normalized_claim)
        if not claim_terms:
            return "insufficient", "low", "当前 claim 过于模糊，无法与公开来源稳定对齐。", evidence_pool[:1]

        claim_is_negative = self._contains_claim_negation(normalized_claim)
        supporting: List[EvidenceItem] = []
        refuting: List[EvidenceItem] = []
        relevant: List[EvidenceItem] = []
        for item in evidence_pool:
            haystack = self._normalize_claim(f"{item.title} {item.snippet} {item.relevance_reason}")
            overlap = [term for term in claim_terms if term in haystack]
            if len(overlap) < 2 and not (len(claim_terms) <= 2 and overlap):
                continue
            relevant.append(item)
            evidence_is_negative = self._contains_evidence_refutation(haystack)
            if claim_is_negative == evidence_is_negative:
                supporting.append(item)
            else:
                refuting.append(item)

        if supporting and refuting:
            supporting_high_trust = [item for item in supporting if item.source_tier in {"S", "A"}]
            refuting_high_trust = [item for item in refuting if item.source_tier in {"S", "A"}]
            if supporting_high_trust and not refuting_high_trust:
                confidence = "high" if len(supporting_high_trust) >= 2 else "medium"
                return "supported", confidence, "高可信来源主要支持该说法，反向线索仍停留在低可信传播节点，当前先按支持处理。", (supporting + refuting)[:2]
            if refuting_high_trust and not supporting_high_trust:
                confidence = "high" if len(refuting_high_trust) >= 2 else "medium"
                return "refuted", confidence, "高可信来源主要否定该说法，反向线索仍停留在低可信传播节点，当前先按否定处理。", (refuting + supporting)[:2]
            confidence = "medium" if (supporting_high_trust or refuting_high_trust) else "low"
            return "conflicting", confidence, "公开来源中同时出现了支持和否定线索，当前应保持冲突态。", (refuting + supporting)[:2]
        if refuting:
            high_trust_hits = [item for item in refuting if item.source_tier in {"S", "A"}]
            if high_trust_hits:
                confidence = "high" if len(high_trust_hits) >= 2 else "medium"
                return "refuted", confidence, "检索到与该说法高度相关的辟谣或否认来源，当前更倾向于判定为不成立。", refuting[:2]
            return "insufficient", "low", "相关证据存在否定信号，但可信度还不足以强判。", refuting[:2]
        if supporting:
            high_trust_hits = [item for item in supporting if item.source_tier in {"S", "A"}]
            if high_trust_hits:
                confidence = "high" if len(high_trust_hits) >= 2 else "medium"
                return "supported", confidence, "检索到与该说法高度相关的公开来源，当前更倾向于判定为成立。", supporting[:2]
            return "insufficient", "low", "找到了一些相关来源，但可信度还不足以强判。", supporting[:2]
        return "insufficient", "low", "检索结果与该说法的语义重合仍不足，先保持保守。", relevant[:2] or evidence_pool[:1]

    def _evaluate_source_gap_claim(self, evidence_pool: List[EvidenceItem]) -> Tuple[str, str, str, List[EvidenceItem]] | None:
        supporting = [item for item in evidence_pool if self._looks_like_source_gap_evidence(item)]
        if not supporting:
            return None
        high_trust_hits = sum(1 for item in supporting if item.source_tier in {"S", "A"})
        confidence = "medium" if high_trust_hits >= 1 else "low"
        return (
            "supported",
            confidence,
            "现有传播内容只有截图、聚合页或来源链不完整的材料，可支持“来源不足”的保守判断。",
            supporting[:2],
        )

    def _normalize_claim(self, text: str) -> str:
        normalized = text.strip().lower()
        replacements = (
            ("是不是", ""),
            ("有没有", ""),
            ("最近", ""),
            ("有一个", ""),
            ("死掉了", "死亡"),
            ("死掉", "死亡"),
            ("真的吗", ""),
            ("是否", ""),
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

    def _contains_claim_negation(self, text: str) -> bool:
        return any(marker in text for marker in CLAIM_NEGATION_MARKERS)

    def _contains_evidence_refutation(self, text: str) -> bool:
        return any(marker in text for marker in EVIDENCE_REFUTING_MARKERS)

    def _is_source_gap_claim(self, text: str) -> bool:
        return any(marker in text for marker in SOURCE_GAP_CLAIM_MARKERS)

    def _looks_like_source_gap_evidence(self, item: EvidenceItem) -> bool:
        haystack = self._normalize_claim(f"{item.title} {item.snippet} {item.relevance_reason}")
        return any(marker in haystack for marker in SOURCE_GAP_EVIDENCE_MARKERS)


