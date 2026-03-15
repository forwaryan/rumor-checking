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
from backend.app.services.entity_anchor import (
    candidate_matches_subject_anchors,
    extract_subject_anchors,
    text_contains_subject_mismatch,
)
from backend.app.services.question_intent import detect_trend_topic, is_broad_trend_claim
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
    "未有",
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
    "只暂停",
    "一条产线",
    "正常运行",
    "其余产线正常",
)
WEAK_REFUTING_MARKERS = ("仅", "只有", "部分")
WEAK_REFUTING_CONTEXT_MARKERS = (
    "号线",
    "线路",
    "检修",
    "停运",
    "停课",
    "暂停",
    "产线",
    "门店",
    "班次",
    "运行",
    "营业",
    "恢复",
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
HIGH_TRUST_SOURCE_TIERS = {"S", "A"}
DECISIVE_HIGH_CONFIDENCE_TIER = "S"
QUANTITY_TOKEN_PATTERN = re.compile(r"\d+(?:\.\d+)?%|\d+(?:\.\d+)?[人名例起条线艘班个年月天小时分钟]")
RESOLUTION_CLAIM_MARKERS = (
    "已经解决",
    "彻底解决",
    "完全恢复",
    "恢复正常",
    "没有问题",
    "不存在问题",
    "问题不大",
    "消息不实",
    "传闻不实",
)
ONGOING_UNCERTAINTY_MARKERS = (
    "仍在核查",
    "正在核查",
    "已进场核查",
    "调查中",
    "仍在调查",
    "异味持续",
    "仍有投诉",
    "居民仍称",
    "生命体征平稳",
    "仍在救治",
    "尚未恢复",
)
CONTEXT_ONLY_MARKERS = ("回应", "传闻", "传言", "网传", "热议", "消息", "报道")
POSITIVE_ASSERTION_MARKERS = ("确认", "证实", "停业", "停产", "暂停", "整改", "发现", "受伤", "送医", "去世", "入院", "恢复")
FULL_SCOPE_CLAIM_MARKERS = ("完全", "全面", "全部", "整体")
UNRELIABLE_ANCHOR_MARKERS = ("确认", "存在", "已经", "标题", "摘要", "来源", "时间", "原始问题", "第一次检索后")
STRONG_OVERLAP_TERMS = {
    "停产",
    "停业",
    "停课",
    "停航",
    "裁员",
    "去世",
    "死亡",
    "脑出血",
    "中毒",
    "受伤",
    "暂停",
    "辟谣",
    "否认",
    "声明",
    "整改",
}
TIER_PRIORITY = {"S": 0, "A": 1, "B": 2, "C": 3}


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

            subject_anchors = self._subject_anchors_for_claim(claim_text=claim.claim, event=event)
            verdict, confidence, notes, selected = self._evaluate_fact_claim(
                claim_text=claim.claim,
                evidence_pool=evidence_pool,
                subject_anchors=subject_anchors,
            )
            results.append(
                ClaimResult(
                    claim=claim.claim,
                    claim_type=claim.claim_type,
                    verdict=verdict,
                    confidence=confidence,
                    evidence=selected,
                    notes=self._append_evidence_context(notes=notes, selected=selected),
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
        subject_anchors: List[str],
    ) -> Tuple[str, str, str, List[EvidenceItem]]:
        normalized_claim = self._normalize_claim(claim_text)
        trend_result = self._evaluate_broad_trend_claim(
            claim_text=claim_text,
            normalized_claim=normalized_claim,
            evidence_pool=evidence_pool,
            subject_anchors=subject_anchors,
        )
        if trend_result is not None:
            return trend_result
        if self._is_source_gap_claim(normalized_claim):
            source_gap_result = self._evaluate_source_gap_claim(evidence_pool)
            if source_gap_result is not None:
                return source_gap_result
        resolution_result = self._evaluate_resolution_claim(
            claim_text=claim_text,
            normalized_claim=normalized_claim,
            evidence_pool=evidence_pool,
            subject_anchors=subject_anchors,
        )
        if resolution_result is not None:
            return resolution_result

        claim_terms = self._extract_terms(normalized_claim)
        if not claim_terms:
            return "insufficient", "low", "当前 claim 过于模糊，无法与公开来源稳定对齐。", []

        claim_is_negative = self._contains_claim_negation(normalized_claim)
        full_scope_claim = any(marker in claim_text or marker in normalized_claim for marker in FULL_SCOPE_CLAIM_MARKERS)
        supporting: List[EvidenceItem] = []
        refuting: List[EvidenceItem] = []
        relevant: List[EvidenceItem] = []
        for item in evidence_pool:
            item_text = f"{item.title} {item.snippet} {item.source_name}"
            if text_contains_subject_mismatch(
                item.title,
                item.snippet,
                item.source_name,
                item.relevance_reason,
            ):
                continue
            haystack = self._normalize_claim(item_text)
            if subject_anchors and not candidate_matches_subject_anchors(
                subject_anchors,
                item.title,
                item.snippet,
                item.source_name,
                item.relevance_reason,
            ):
                if not (item.source_tier in HIGH_TRUST_SOURCE_TIERS and self._contains_evidence_refutation(haystack)):
                    continue
            matched_segment, segment_supports, segment_refutes = self._segment_evidence_alignment(
                segment_text=f"{item.title}。{item.snippet}" if item.snippet else item.title or item_text,
                claim_terms=claim_terms,
                claim_is_negative=claim_is_negative,
                full_scope_claim=full_scope_claim,
            )
            if matched_segment:
                relevant.append(item)
                if segment_supports:
                    supporting.append(item)
                if segment_refutes:
                    refuting.append(item)
                continue

        quantitative_conflict = self._detect_quantitative_conflict(
            claim_text=normalized_claim,
            evidence_pool=evidence_pool,
        )
        if quantitative_conflict is not None:
            return quantitative_conflict

        if supporting and refuting:
            supporting_high_trust = [item for item in supporting if item.source_tier in HIGH_TRUST_SOURCE_TIERS]
            refuting_high_trust = [item for item in refuting if item.source_tier in HIGH_TRUST_SOURCE_TIERS]
            supporting_decisive = self._has_decisive_high_trust_hits(supporting_high_trust)
            refuting_decisive = self._has_decisive_high_trust_hits(refuting_high_trust)
            if supporting_decisive and not refuting_decisive:
                confidence = self._confidence_from_high_trust_hits(supporting_high_trust)
                return "supported", confidence, "高可信来源主要支持该说法，反向线索仍停留在低可信传播节点，当前先按支持处理。", (supporting + refuting)[:2]
            if refuting_decisive and not supporting_decisive:
                confidence = self._confidence_from_high_trust_hits(refuting_high_trust)
                return "refuted", confidence, "高可信来源主要否定该说法，反向线索仍停留在低可信传播节点，当前先按否定处理。", (refuting + supporting)[:2]
            confidence = "medium" if (supporting_high_trust or refuting_high_trust) else "low"
            return "conflicting", confidence, "公开来源中同时出现了支持和否定线索，当前应保持冲突态。", (refuting + supporting)[:2]
        if refuting:
            high_trust_hits = [item for item in refuting if item.source_tier in HIGH_TRUST_SOURCE_TIERS]
            if self._has_decisive_high_trust_hits(high_trust_hits):
                confidence = self._confidence_from_high_trust_hits(high_trust_hits)
                return "refuted", confidence, "检索到与该说法高度相关的辟谣或否认来源，当前更倾向于判定为不成立。", refuting[:2]
            return "insufficient", "low", "相关证据存在否定信号，但可信度还不足以强判。", refuting[:2]
        if supporting:
            high_trust_hits = [item for item in supporting if item.source_tier in HIGH_TRUST_SOURCE_TIERS]
            if self._has_decisive_high_trust_hits(high_trust_hits):
                confidence = self._confidence_from_high_trust_hits(high_trust_hits)
                return "supported", confidence, "检索到与该说法高度相关的公开来源，当前更倾向于判定为成立。", supporting[:2]
            return "insufficient", "low", "找到了一些相关来源，但可信度还不足以强判。", supporting[:2]
        return "insufficient", "low", "检索结果与该说法的语义重合仍不足，先保持保守。", relevant[:2]

    def _subject_anchors_for_claim(self, *, claim_text: str, event: NormalizedEvent) -> List[str]:
        if is_broad_trend_claim(claim_text):
            return []
        claim_anchors = self._filter_subject_anchors(extract_subject_anchors(claim_text))
        if claim_anchors:
            return claim_anchors
        if event.input_type != "question_only":
            return []
        return self._filter_subject_anchors(extract_subject_anchors(" ".join(filter(None, [event.title, event.summary, event.raw_input]))))

    def _filter_subject_anchors(self, anchors: List[str]) -> List[str]:
        return [anchor for anchor in anchors if not any(marker in anchor for marker in UNRELIABLE_ANCHOR_MARKERS)]

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

    def _evaluate_broad_trend_claim(
        self,
        *,
        claim_text: str,
        normalized_claim: str,
        evidence_pool: List[EvidenceItem],
        subject_anchors: List[str],
    ) -> Tuple[str, str, str, List[EvidenceItem]] | None:
        if subject_anchors or not is_broad_trend_claim(claim_text):
            return None

        topic = detect_trend_topic(normalized_claim) or detect_trend_topic(claim_text)
        if topic is None:
            return None

        supporting: List[EvidenceItem] = []
        for item in evidence_pool:
            haystack = self._normalize_claim(f"{item.title} {item.snippet} {item.source_name}")
            if topic not in haystack or self._contains_evidence_refutation(haystack):
                continue
            supporting.append(item)

        high_trust_hits = [item for item in supporting if item.source_tier in HIGH_TRUST_SOURCE_TIERS]
        if self._has_decisive_high_trust_hits(high_trust_hits):
            confidence = self._confidence_from_high_trust_hits(high_trust_hits)
            return (
                "supported",
                confidence,
                "检索结果里已经出现多条与该范围问题直接相关的公开报道，当前可以回答为“最近确实有相关消息”，但它不是单一事件。",
                high_trust_hits[:2],
            )
        if supporting:
            return "insufficient", "low", "检索里有一些相关报道，但高可信来源还不够，先保持保守。", supporting[:2]
        return None

    def _evaluate_resolution_claim(
        self,
        *,
        claim_text: str,
        normalized_claim: str,
        evidence_pool: List[EvidenceItem],
        subject_anchors: List[str],
    ) -> Tuple[str, str, str, List[EvidenceItem]] | None:
        if not any(marker in claim_text or marker in normalized_claim for marker in RESOLUTION_CLAIM_MARKERS):
            return None

        unresolved_signals: List[EvidenceItem] = []
        for item in evidence_pool:
            if subject_anchors and not candidate_matches_subject_anchors(
                subject_anchors,
                item.title,
                item.snippet,
                item.source_name,
                item.relevance_reason,
            ):
                continue
            if self._looks_like_unresolved_evidence(item):
                unresolved_signals.append(item)

        if not unresolved_signals:
            return None

        high_trust_hits = [item for item in unresolved_signals if item.source_tier in HIGH_TRUST_SOURCE_TIERS]
        confidence = "medium" if high_trust_hits else "low"
        verdict = "conflicting" if high_trust_hits or len(unresolved_signals) >= 2 else "insufficient"
        return (
            verdict,
            confidence,
            "检索里仍有“正在核查 / 投诉持续 / 仅部分恢复”这类未收口信号，当前不能把事件直接说成已经完全解决或纯属误传。",
            unresolved_signals[:2],
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
            ("真的假的", ""),
            ("真的还是假的", ""),
            ("真假", ""),
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
            if len(ordered) >= 48:
                return
            if term and term not in seen:
                seen.add(term)
                ordered.append(term)

        for term in re.findall(r"[a-z0-9]{2,}", text):
            push(term)

        for term in self._extract_quantity_tokens(text):
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
                    if len(ordered) >= 48:
                        return ordered

        return ordered

    def _segment_evidence_alignment(
        self,
        *,
        segment_text: str,
        claim_terms: List[str],
        claim_is_negative: bool,
        full_scope_claim: bool,
    ) -> Tuple[bool, bool, bool]:
        matched_segment = False
        segment_supports = False
        segment_refutes = False
        for segment in re.split(r"[。！？!?；;\n]", segment_text):
            haystack = self._normalize_claim(segment)
            overlap = self._overlap_terms(claim_terms, haystack)
            if not haystack:
                continue
            if not self._has_sufficient_overlap(claim_terms, overlap):
                if not (full_scope_claim and self._contains_evidence_refutation(haystack)):
                    continue
            matched_segment = True
            evidence_is_negative = self._contains_evidence_refutation(haystack)
            if not evidence_is_negative and self._is_context_only_segment(haystack):
                continue
            if claim_is_negative and not evidence_is_negative and not self._has_negative_claim_refutation_overlap(overlap):
                continue
            if claim_is_negative == evidence_is_negative:
                segment_supports = True
            else:
                segment_refutes = True
        return matched_segment, segment_supports, segment_refutes

    def _overlap_terms(self, claim_terms: List[str], haystack: str) -> List[str]:
        return [term for term in claim_terms if term in haystack]

    def _has_sufficient_overlap(self, claim_terms: List[str], overlap: List[str]) -> bool:
        if any(len(term) >= 3 or term in STRONG_OVERLAP_TERMS or any(char.isdigit() for char in term) for term in overlap):
            return True
        return len(overlap) >= 2 or (len(claim_terms) <= 2 and bool(overlap))

    def _is_context_only_segment(self, haystack: str) -> bool:
        return any(marker in haystack for marker in CONTEXT_ONLY_MARKERS) and not any(
            marker in haystack for marker in POSITIVE_ASSERTION_MARKERS
        )

    def _has_negative_claim_refutation_overlap(self, overlap: List[str]) -> bool:
        return any(len(term) >= 3 or any(char.isdigit() for char in term) for term in overlap)

    def _confidence_from_high_trust_hits(self, items: List[EvidenceItem]) -> str:
        if len(items) >= 2 or any(item.source_tier == DECISIVE_HIGH_CONFIDENCE_TIER for item in items):
            return "high"
        if items:
            return "medium"
        return "low"

    def _has_decisive_high_trust_hits(self, items: List[EvidenceItem]) -> bool:
        return bool(items)

    def _extract_quantity_tokens(self, text: str) -> List[str]:
        return [match.group(0) for match in QUANTITY_TOKEN_PATTERN.finditer(text)]

    def _detect_quantitative_conflict(
        self,
        *,
        claim_text: str,
        evidence_pool: List[EvidenceItem],
    ) -> Tuple[str, str, str, List[EvidenceItem]] | None:
        claim_quantity_tokens = set(self._extract_quantity_tokens(claim_text))
        if not claim_quantity_tokens:
            return None

        evidence_with_quantities: List[Tuple[EvidenceItem, set[str]]] = []
        distinct_quantities = set()
        claim_quantity_supported = False
        for item in evidence_pool:
            if item.source_tier not in HIGH_TRUST_SOURCE_TIERS:
                continue
            haystack = self._normalize_claim(f"{item.title} {item.snippet} {item.source_name}")
            quantity_tokens = set(self._extract_quantity_tokens(haystack))
            if not quantity_tokens:
                continue
            evidence_with_quantities.append((item, quantity_tokens))
            distinct_quantities.update(quantity_tokens)
            if quantity_tokens & claim_quantity_tokens:
                claim_quantity_supported = True

        if len(evidence_with_quantities) < 2 or len(distinct_quantities) < 2 or not claim_quantity_supported:
            return None
        if not any(tokens.isdisjoint(claim_quantity_tokens) for _, tokens in evidence_with_quantities):
            return None

        selected = [item for item, _ in evidence_with_quantities[:2]]
        return (
            "conflicting",
            "medium",
            "高可信来源对同一数量细节给出了不一致说法，当前应保持冲突态。",
            selected,
        )

    def _contains_claim_negation(self, text: str) -> bool:
        return any(marker in text for marker in CLAIM_NEGATION_MARKERS)

    def _contains_evidence_refutation(self, text: str) -> bool:
        if any(marker in text for marker in EVIDENCE_REFUTING_MARKERS):
            return True
        if any(marker in text for marker in WEAK_REFUTING_MARKERS):
            return any(marker in text for marker in WEAK_REFUTING_CONTEXT_MARKERS)
        return False

    def _looks_like_unresolved_evidence(self, item: EvidenceItem) -> bool:
        haystack = self._normalize_claim(f"{item.title} {item.snippet} {item.source_name}")
        if any(marker in haystack for marker in ONGOING_UNCERTAINTY_MARKERS):
            return True
        if any(marker in haystack for marker in WEAK_REFUTING_MARKERS):
            return any(marker in haystack for marker in WEAK_REFUTING_CONTEXT_MARKERS)
        return False

    def _is_source_gap_claim(self, text: str) -> bool:
        return any(marker in text for marker in SOURCE_GAP_CLAIM_MARKERS)

    def _looks_like_source_gap_evidence(self, item: EvidenceItem) -> bool:
        haystack = self._normalize_claim(f"{item.title} {item.snippet} {item.relevance_reason}")
        return any(marker in haystack for marker in SOURCE_GAP_EVIDENCE_MARKERS)

    def _append_evidence_context(self, *, notes: str, selected: List[EvidenceItem]) -> str:
        if not selected:
            return notes
        ranked_tiers = sorted({item.source_tier for item in selected}, key=lambda tier: TIER_PRIORITY.get(tier, 99))
        source_names: List[str] = []
        for item in selected:
            if item.source_name not in source_names:
                source_names.append(item.source_name)
            if len(source_names) >= 2:
                break
        return (
            f"{notes} 复核依据：共引用 {len(selected)} 条关联证据，"
            f"最高来源等级 {ranked_tiers[0]}，代表来源包括 {'、'.join(source_names)}。"
        )


