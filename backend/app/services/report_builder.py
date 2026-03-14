from __future__ import annotations

from typing import List, Tuple

from backend.app.models.schemas import (
    ClaimResult,
    Event,
    EvidenceItem,
    Investigation,
    InvestigationStep,
    NormalizedEvent,
    PossibilityItem,
    Report,
    RetrievalDiagnostics,
    ReportProvenance,
    TimelineNode,
)
from backend.app.services.contract_utils import default_source_name, default_source_url, ensure_datetime_string

URL_FALLBACK_RISK_MAP = {
    "url_content_incomplete": "\u9875\u9762\u53ea\u62ff\u5230\u90e8\u5206\u6b63\u6587\u6216\u7247\u6bb5\uff0c\u5f53\u524d\u53ea\u80fd\u6309\u4fdd\u5b88\u8f93\u51fa\u7406\u89e3\u3002",
    "url_content_missing": "\u9875\u9762\u672a\u63d0\u53d6\u5230\u53ef\u7528\u6b63\u6587\uff0c\u5f53\u524d\u53ea\u80fd\u5148\u4fdd\u5b88\u8f93\u51fa\u3002",
    "url_fetch_timeout": "\u9875\u9762\u6293\u53d6\u8d85\u65f6\uff0c\u5f53\u524d\u672a\u62ff\u5230\u6b63\u6587\uff0c\u53ea\u80fd\u5148\u4fdd\u5b88\u8f93\u51fa\uff1b\u53ef\u7a0d\u540e\u91cd\u8bd5\u6216\u76f4\u63a5\u7c98\u8d34\u6b63\u6587\u3002",
    "url_fetch_failed": "\u9875\u9762\u6293\u53d6\u5931\u8d25\uff0c\u5f53\u524d\u672a\u62ff\u5230\u6b63\u6587\uff0c\u53ea\u80fd\u5148\u6839\u636e\u8f93\u5165\u8fb9\u754c\u5316\u5c55\u793a\u3002",
    "url_content_unsupported": "\u5f53\u524d\u4ec5\u652f\u6301\u516c\u5f00 HTML \u9875\u9762\uff0c\u6682\u4e0d\u652f\u6301\u767b\u5f55\u9875\u3001\u5f3a\u811a\u672c\u6e32\u67d3\u9875\u6216\u4e0d\u53ef\u76f4\u63a5\u6293\u53d6\u9875\u9762\u3002",
    "url_invalid": "\u5f53\u524d\u8f93\u5165\u7684 URL \u65e0\u6548\u6216\u4e0d\u53ef\u8bbf\u95ee\uff0c\u8bf7\u786e\u8ba4\u94fe\u63a5\u683c\u5f0f\u540e\u91cd\u8bd5\u3002",
}
RETRIEVAL_FALLBACK_REASONS = {
    "real_retrieval_failed",
    "real_retrieval_empty",
    "retrieval_provider_unavailable",
    "retrieval_cache_only_miss",
}
SERIOUS_HARM_MARKERS = ("脑出血", "脑溢血", "去世", "死亡", "病危", "抢救", "住院", "昏迷")


class ReportBuilder:
    def build(
        self,
        *,
        event: NormalizedEvent,
        claim_results: List[ClaimResult],
        timeline: List[TimelineNode],
        evidence: List[EvidenceItem],
        evidence_grade: str,
        provenance: ReportProvenance,
        retrieval_hits: List[EvidenceItem] | None = None,
        retrieval_diagnostics: RetrievalDiagnostics | None = None,
        original_input: str | None = None,
    ) -> Report:
        retrieval_hits = list(retrieval_hits or [])
        mode = self._select_mode(
            event=event,
            claim_results=claim_results,
            timeline=timeline,
            evidence_grade=evidence_grade,
            provenance=provenance,
        )
        final_summary, risks = self._compose_sections(
            mode=mode,
            event=event,
            claim_results=claim_results,
            timeline=timeline,
            evidence=evidence,
            provenance=provenance,
        )

        public_event = Event(
            title=event.title or "\u5f85\u6838\u4e8b\u4ef6",
            summary=event.summary,
            source_url=event.source_url or default_source_url(event.input_type, event.raw_input),
            source_name=event.source_name or default_source_name(event.input_type),
            published_at=ensure_datetime_string(event.published_at),
            keywords=event.keywords or ["\u5f85\u6838\u67e5"],
            mode=mode,
        )
        investigation = self._build_investigation(
            mode=mode,
            event=event,
            public_event=public_event,
            original_input=original_input or event.raw_input,
            claim_results=claim_results,
            timeline=timeline,
            evidence=evidence,
            retrieval_hits=retrieval_hits,
            final_summary=final_summary,
            provenance=provenance,
        )

        return Report(
            mode=mode,
            event=public_event,
            claim_results=claim_results,
            timeline=timeline,
            sources=evidence,
            retrieval_hits=retrieval_hits,
            retrieval_diagnostics=retrieval_diagnostics,
            final_summary=final_summary,
            risks=risks,
            investigation=investigation,
            provenance=provenance,
        )

    def _select_mode(
        self,
        *,
        event: NormalizedEvent,
        claim_results: List[ClaimResult],
        timeline: List[TimelineNode],
        evidence_grade: str,
        provenance: ReportProvenance,
    ) -> str:
        decisive_count = sum(1 for item in claim_results if item.verdict in {"supported", "refuted", "conflicting"})
        if event.input_type == "question_only" and decisive_count == 0:
            return "safe_mode"
        if decisive_count == 0 and (event.fallback_used or provenance.evidence_source == "none"):
            return "safe_mode"
        if (
            event.input_type != "question_only"
            and
            evidence_grade in {"A", "S"}
            and decisive_count >= 2
            and len(timeline) >= 2
            and provenance.timeline_source == "retrieval"
            and not event.fallback_used
        ):
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
        provenance: ReportProvenance,
    ) -> Tuple[str, List[str]]:
        strong_claims = [item for item in claim_results if item.verdict in {"supported", "refuted", "conflicting"}]
        supported_claims = [item for item in claim_results if item.verdict == "supported"]
        refuted_claims = [item for item in claim_results if item.verdict == "refuted"]
        insufficient_claims = [item for item in claim_results if item.verdict == "insufficient"]
        conflicting_claims = [item for item in claim_results if item.verdict == "conflicting"]

        if supported_claims and refuted_claims:
            summary = "这句话里同时有能被公开来源支持和被反驳的部分，当前更应按“真假混杂、部分被加料”来理解。"
        elif supported_claims and insufficient_claims and mode != "complete_mode":
            summary = "核心事件大体能对上，但句子里的部分追加细节仍缺公开证据，不能整句一起判真。"
        elif refuted_claims and insufficient_claims and mode != "complete_mode":
            summary = "主说法里有站不住的部分，但也可能混入了相近真实信息或二次加工细节，不能简单整句判假。"
        elif mode == "complete_mode":
            headline = strong_claims[0].claim if strong_claims else event.summary
            summary = "已形成相对完整的公开证据链，当前更倾向于：" + headline + "。"
        elif mode == "partial_mode":
            summary = "已拿到部分公开证据，但链路仍不完整；当前不能给出完整定论，只给出边界化结论。"
        else:
            summary = "当前证据仍不足，系统保持 safe mode，只展示核查边界与原始检索命中。"

        risks: List[str] = []
        if conflicting_claims:
            risks.append("\u516c\u5f00\u6765\u6e90\u4e4b\u95f4\u4ecd\u6709\u51b2\u7a81\uff0c\u4e0d\u80fd\u76f4\u63a5\u4e0b\u5355\u4e00\u7ed3\u8bba\u3002")
        if provenance.source_type == "backend_mock":
            risks.append("\u5f53\u524d\u7ed3\u679c\u6765\u81ea mock \u6570\u636e\u6216 mock \u56de\u9000\u8def\u5f84\uff0c\u4e0d\u80fd\u5f53\u4f5c\u771f\u5b9e\u8054\u7f51\u6838\u67e5\u7ed3\u8bba\u3002")
        if provenance.source_type == "backend_replay":
            risks.append("\u5f53\u524d\u7ed3\u679c\u6765\u81ea replay \u6f14\u793a\u6837\u672c\uff0c\u4e0d\u80fd\u5f53\u4f5c\u5b9e\u65f6\u68c0\u7d22\u7ed3\u679c\u7406\u89e3\u3002")
        if event.fallback_used:
            risks.append(self._fallback_risk_message(event))
        if any(reason in RETRIEVAL_FALLBACK_REASONS for reason in provenance.fallback_reasons):
            risks.append("\u771f\u5b9e\u68c0\u7d22\u94fe\u8def\u672c\u6b21\u672a\u7a33\u5b9a\u547d\u4e2d\uff0c\u9875\u9762\u4f1a\u4fdd\u7559\u539f\u59cb\u68c0\u7d22\u547d\u4e2d\u4f9b\u4eba\u5de5\u590d\u6838\u3002")
        if provenance.timeline_source == "input_seed":
            risks.append("\u65f6\u95f4\u7ebf\u4ecd\u542b\u8f93\u5165\u4fa7\u79cd\u5b50\u4fe1\u606f\uff0c\u5c1a\u672a\u5b8c\u5168\u7531\u68c0\u7d22\u8bc1\u636e\u95ed\u73af\u652f\u6491\u3002")
        if not evidence:
            risks.append("\u5f53\u524d\u8fd8\u6ca1\u6709\u8fdb\u5165\u8bc1\u636e\u94fe\u7684\u7a33\u5b9a\u6765\u6e90\u3002")
        if mode == "safe_mode":
            risks.append("\u5f53\u524d\u9875\u9762\u53ea\u9002\u5408\u63d0\u793a\u6838\u67e5\u70b9\uff0c\u4e0d\u5e94\u88ab\u5f53\u4f5c\u786e\u5b9a\u6027\u7ed3\u8bba\u3002")
            risks.append("\u5efa\u8bae\u8865\u5145\u59d3\u540d\u3001\u94fe\u63a5\u3001\u539f\u6587\u6216\u65f6\u95f4\u70b9\u540e\u518d\u8bd5\u3002")
        if not timeline:
            risks.append("\u65f6\u95f4\u7ebf\u672a\u5efa\u7acb\u6210\u529f\uff0c\u5f53\u524d\u7ed3\u679c\u4e0d\u4ee3\u8868\u5b8c\u6574\u4f20\u64ad\u94fe\u3002")

        return summary, list(dict.fromkeys(risks))

    def _build_investigation(
        self,
        *,
        mode: str,
        event: NormalizedEvent,
        public_event: Event,
        original_input: str,
        claim_results: List[ClaimResult],
        timeline: List[TimelineNode],
        evidence: List[EvidenceItem],
        retrieval_hits: List[EvidenceItem],
        final_summary: str,
        provenance: ReportProvenance,
    ) -> Investigation:
        reframed_question = self._derive_reframed_question(
            original_input=original_input,
            public_event=public_event,
            claim_results=claim_results,
        )
        thinking_process = self._build_thinking_process(
            original_input=original_input,
            reframed_question=reframed_question,
            claim_results=claim_results,
            timeline=timeline,
            evidence=evidence,
            retrieval_hits=retrieval_hits,
            provenance=provenance,
        )
        possibilities = self._build_possibilities(
            mode=mode,
            original_input=original_input,
            public_event=public_event,
            claim_results=claim_results,
            evidence=evidence,
            retrieval_hits=retrieval_hits,
            provenance=provenance,
        )
        final_conclusion = self._build_investigation_conclusion(
            mode=mode,
            original_input=original_input,
            public_event=public_event,
            claim_results=claim_results,
            timeline=timeline,
            evidence=evidence,
            retrieval_hits=retrieval_hits,
            provenance=provenance,
            final_summary=final_summary,
        )
        return Investigation(
            question=original_input.strip() or public_event.summary,
            reframed_question=reframed_question,
            thinking_process=thinking_process,
            possibilities=possibilities,
            final_conclusion=final_conclusion,
        )

    def _derive_reframed_question(
        self,
        *,
        original_input: str,
        public_event: Event,
        claim_results: List[ClaimResult],
    ) -> str:
        decisive = next((item.claim.rstrip("。") for item in claim_results if item.verdict in {"supported", "refuted", "conflicting"}), None)
        if decisive:
            return decisive
        if public_event.summary:
            return public_event.summary.rstrip("。")
        if public_event.title:
            return public_event.title.rstrip("。")
        return original_input.strip().rstrip("？?")

    def _build_thinking_process(
        self,
        *,
        original_input: str,
        reframed_question: str,
        claim_results: List[ClaimResult],
        timeline: List[TimelineNode],
        evidence: List[EvidenceItem],
        retrieval_hits: List[EvidenceItem],
        provenance: ReportProvenance,
    ) -> List[InvestigationStep]:
        fact_count = sum(1 for item in claim_results if item.claim_type == "fact")
        opinion_count = sum(1 for item in claim_results if item.claim_type == "opinion")
        prediction_count = sum(1 for item in claim_results if item.claim_type == "prediction")
        unverifiable_count = sum(1 for item in claim_results if item.claim_type == "unverifiable")
        supported_count = sum(1 for item in claim_results if item.verdict == "supported")
        refuted_count = sum(1 for item in claim_results if item.verdict == "refuted")
        conflicting_count = sum(1 for item in claim_results if item.verdict == "conflicting")
        insufficient_count = sum(1 for item in claim_results if item.verdict == "insufficient")
        high_trust_hit_count = sum(1 for item in retrieval_hits if item.source_tier in {"S", "A"})

        if provenance.event_source == "retrieval_resolved":
            event_lock_detail = "第一轮检索已经锁定到较匹配的候选事件，后续 claim 和证据判断会围绕这个更具体的对象继续展开。"
        elif retrieval_hits:
            event_lock_detail = (
                f"当前检索命中了 {len(retrieval_hits)} 条相关结果，其中 {high_trust_hit_count} 条来自高可信来源；"
                "但原句里的锚点还不够强，系统不会直接把这些结果视为同一事件。"
            )
        else:
            event_lock_detail = "当前还没有拿到稳定的相关结果，系统只能先把它当成一条待核查传闻，而不是既成事实。"

        if timeline:
            timeline_detail = (
                f"传播链目前还原出 {len(timeline)} 个关键节点，"
                f"最早节点是“{timeline[0].title}”，最新节点是“{timeline[-1].title}”。"
            )
        else:
            timeline_detail = "传播链还没能形成稳定时间线，这意味着系统还不能回答它是从哪开始发酵、又在什么时候被回应或纠偏。"

        return [
            InvestigationStep(
                title="先把口语问题收束成可核查对象",
                detail=f"原始输入是“{original_input.strip()}”，系统先把它收束成更适合核查的命题：{reframed_question}。",
            ),
            InvestigationStep(
                title="再判断能不能锁定到具体事件",
                detail=event_lock_detail,
            ),
            InvestigationStep(
                title="把内容拆成事实、观点和待核查点",
                detail=(
                    f"当前共拆出 {len(claim_results)} 条 claim，其中事实 {fact_count} 条、观点 {opinion_count} 条、"
                    f"预测 {prediction_count} 条、公开资料难直接核验 {unverifiable_count} 条；"
                    f"对应 verdict 为支持 {supported_count} 条、反驳 {refuted_count} 条、冲突 {conflicting_count} 条、"
                    f"待定 {insufficient_count} 条。"
                ),
            ),
            InvestigationStep(
                title="最后看传播链有没有闭环",
                detail=timeline_detail if evidence else f"{timeline_detail} 当前进入证据链的稳定来源仍然不足，不能把一句话直接判成真或假。",
            ),
        ]

    def _build_possibilities(
        self,
        *,
        mode: str,
        original_input: str,
        public_event: Event,
        claim_results: List[ClaimResult],
        evidence: List[EvidenceItem],
        retrieval_hits: List[EvidenceItem],
        provenance: ReportProvenance,
    ) -> List[PossibilityItem]:
        possibilities: List[PossibilityItem] = []
        seen: set[str] = set()
        refuted = next((item for item in claim_results if item.verdict == "refuted"), None)
        supported = next((item for item in claim_results if item.verdict == "supported"), None)
        conflicting = next((item for item in claim_results if item.verdict == "conflicting"), None)
        high_trust_hit_count = sum(1 for item in retrieval_hits if item.source_tier in {"S", "A"})

        def push(scenario: str, likelihood: str, summary: str) -> None:
            if scenario in seen or len(possibilities) >= 4:
                return
            seen.add(scenario)
            possibilities.append(
                PossibilityItem(
                    scenario=scenario,
                    likelihood=self._normalize_confidence(likelihood),
                    summary=summary,
                )
            )

        if refuted is not None:
            push(
                "这句话对应的主说法不成立，或已经被回应/辟谣",
                refuted.confidence,
                f"当前最强的反向线索是“{refuted.claim}”，备注为：{refuted.notes}",
            )
        if supported is not None:
            push(
                "相关事件大体存在，但原话可能把细节说满了",
                supported.confidence,
                f"当前能被公开来源支撑的是“{supported.claim}”，但仍需要核对人物、时间点和上下文。",
            )
        if conflicting is not None:
            push(
                "公开来源仍在打架，不能只信单一版本",
                conflicting.confidence,
                f"系统已经识别到冲突 claim：“{conflicting.claim}”；当前更适合保留争议，而不是强判真假。",
            )
        if retrieval_hits and provenance.event_source != "retrieval_resolved":
            push(
                "可能存在多个相似事件，原问题还没给出足够锚点来锁定同一人同一事",
                "medium" if high_trust_hit_count else "low",
                f"当前能看到的相似命中里，最新一条是“{retrieval_hits[0].title}”，但系统还不能证明原句说的就是它。",
            )
        if any(marker in original_input for marker in SERIOUS_HARM_MARKERS):
            push(
                "可能确有生病或送医事件，但传播里把病情夸大成了死亡",
                "medium" if retrieval_hits else "low",
                "涉及伤病、抢救和死亡的传闻，最常见的失真就是把“住院/病危/脑出血”直接改写成“已经去世”。",
            )
        if mode == "safe_mode" or not evidence:
            push(
                "也可能是旧闻回流、张冠李戴，或经过二次加工后的传闻",
                "medium" if retrieval_hits else "low",
                "在缺姓名、链接、原帖和明确时间点时，旧新闻、评论截图和转述很容易被重新拼成一条新传闻。",
            )
        if not retrieval_hits:
            push(
                "目前公开检索还对不上稳定事实锚点，这句话暂时只能当线索不能当结论",
                "medium",
                "当前输入过于泛化，缺少姓名、平台账号、原始链接或精确时间，系统还不能稳定定位到具体事件。",
            )

        return possibilities

    def _build_investigation_conclusion(
        self,
        *,
        mode: str,
        original_input: str,
        public_event: Event,
        claim_results: List[ClaimResult],
        timeline: List[TimelineNode],
        evidence: List[EvidenceItem],
        retrieval_hits: List[EvidenceItem],
        provenance: ReportProvenance,
        final_summary: str,
    ) -> str:
        refuted = next((item for item in claim_results if item.verdict == "refuted"), None)
        supported = next((item for item in claim_results if item.verdict == "supported"), None)
        conflicting = next((item for item in claim_results if item.verdict == "conflicting"), None)

        if refuted is not None:
            conclusion = f"当前更倾向于：这句话对应的核心说法不成立，或至少已经被公开回应明显削弱。"
        elif supported is not None:
            conclusion = f"当前更倾向于：相关事件大体存在，但原句仍可能省略了限定条件或夸大了细节。"
        elif conflicting is not None:
            conclusion = "当前结论只能停在冲突态：公开来源没有收敛到单一版本，不能直接判真或判假。"
        elif retrieval_hits and provenance.event_source != "retrieval_resolved":
            conclusion = "当前更合理的结论是：系统找到了相似事件，但还不能证明原句说的就是其中哪一个。"
        else:
            conclusion = "当前不能判定真假。这更像一条缺关键锚点的传闻线索，现阶段只能列出可能情况，不能下确定性结论。"

        if not timeline:
            conclusion += " 传播链也还没有完全还原。"
        if not evidence:
            conclusion += " 公开证据链仍然偏弱，最好补充姓名、原帖链接、原文或明确时间点。"
        elif mode != "complete_mode":
            conclusion += " 虽然已经有部分证据，但还不足以把边界完全抹掉。"
        if public_event.title and public_event.title != "待核事件":
            conclusion += f" 当前最接近的事件锚点是“{public_event.title}”。"
        return conclusion

    def _normalize_confidence(self, value: str | float) -> str:
        if isinstance(value, str) and value in {"high", "medium", "low"}:
            return value
        if isinstance(value, (int, float)):
            if value >= 0.75:
                return "high"
            if value >= 0.4:
                return "medium"
        return "low"

    def _fallback_risk_message(self, event: NormalizedEvent) -> str:
        if event.input_type == "url" or event.input_type.startswith("url_"):
            return URL_FALLBACK_RISK_MAP.get(
                event.fallback_reason or "",
                "\u9875\u9762\u6293\u53d6\u94fe\u8def\u53d1\u751f\u56de\u9000\uff0c\u672c\u6b21\u53ea\u80fd\u4fdd\u5b88\u8f93\u51fa\u4e0e\u8fb9\u754c\u5316\u5c55\u793a\u3002",
            )
        return "\u5f53\u524d\u94fe\u8def\u53d1\u751f\u964d\u7ea7\u6216\u56de\u9000\uff0c\u672c\u6b21\u8f93\u51fa\u53ea\u4fdd\u7559\u8fb9\u754c\u5316\u4fe1\u606f\u3002"
