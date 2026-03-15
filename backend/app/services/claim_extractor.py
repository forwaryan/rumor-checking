from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from backend.app.models.schemas import ClaimItem, ClaimSourceType, NormalizedEvent
from backend.app.services.entity_anchor import extract_subject_anchors
from backend.app.services.question_intent import rewrite_broad_trend_question_as_claim

SCAFFOLDING_MARKERS = (
    "系统已",
    "当前只能",
    "建议",
    "稍后重试",
    "保守提示",
    "保守模式",
    "只拿到用户提供的链接",
    "待核实",
)
QUESTION_TRAILING_MARKERS = ("是真的吗", "属实吗", "是真是假", "真还是假的")
SPLIT_PATTERN = re.compile(r"[。！？?!；;]")
CLAUSE_SPLIT_PATTERN = re.compile(r"[，,、]")
CONNECTOR_SPLIT_PATTERN = re.compile(r"(并且|而且|还说|还称|还传|并称|又说|又称|但是|不过|同时|随后|另称|另有)")
LEADING_CONNECTORS = (
    "并且",
    "而且",
    "还说",
    "还称",
    "还传",
    "并称",
    "又说",
    "又称",
    "但是",
    "但",
    "不过",
    "同时",
    "随后",
    "另称",
    "另有",
)
CONTINUATION_MARKERS = ("其余", "其他", "另有", "目前", "随后", "仍", "还", "并", "同时", "仅", "另")
NOISY_PREFIX_PATTERN = re.compile(
    r"^(?:网传|爆料称|聊天记录显示|截图显示|群聊(?:消息)?(?:显示|称)?|朋友圈(?:消息)?(?:显示|称)?|短视频(?:显示|称)?|视频(?:显示|称)?|据称|传闻称|有消息称)\s*"
)
GENERIC_SUBJECT_PREFIXES = (
    "公司",
    "企业",
    "品牌方",
    "平台",
    "校方",
    "院方",
    "医院",
    "警方",
    "公安",
    "官方",
    "当地",
    "门店",
    "涉事门店",
    "运营公司",
)
GENERIC_SUBJECTS = {
    "公司",
    "企业",
    "平台",
    "校方",
    "院方",
    "警方",
    "官方",
    "当地",
    "运营公司",
    "涉事门店",
    "门店",
    "品牌方",
    "网友",
    "家长",
    "内部员工",
}
COMPATIBILITY_HINTS = {
    "运营公司": ("运营公司", "公司", "集团", "生物", "平台", "地铁"),
    "公司": ("公司", "集团", "生物", "平台", "品牌", "运营公司"),
    "企业": ("公司", "集团", "生物", "品牌", "平台", "运营公司"),
    "品牌方": ("品牌", "公司", "集团", "平台"),
    "平台": ("平台", "公司", "集团"),
    "校方": ("学校", "中学", "大学", "学院"),
    "院方": ("医院",),
    "医院": ("医院",),
    "警方": ("警方", "公安"),
    "公安": ("警方", "公安"),
}
SUBJECT_SUFFIX_PATTERN = re.compile(
    r"[A-Za-z0-9一-龥]{2,24}(?:市场监管局|监管局|交通局|教育局|生态环境局|运营公司|公司|集团|生物|平台|中学|学校|大学|学院|医院|警方|公安|政府|化工厂|门店|品牌)"
)
SUBJECT_BEFORE_ACTION_PATTERN = re.compile(
    r"([A-Za-z0-9一-龥]{2,24}?)(?=(?:明天|今晚|下周|本周|近期|近日|已经|已|将|会|正在)?(?:全线|全面)?(?:停航|停运|停课|裁员|脑出血|去世|死亡|核查|回应|通报|检修|整改|恢复|救治|辟谣|抽检|入院))"
)
TIME_PATTERN = re.compile(
    r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?|\d{1,2}月\d{1,2}日(?:上午|下午|凌晨|晚上|晚间|中午)?|明天|今晚|今早|今天|今日|昨天|昨日|下周|本周|近日|近期"
)
ACTION_MARKERS = (
    "停航",
    "停运",
    "停课",
    "裁员",
    "脑出血",
    "去世",
    "死亡",
    "住院",
    "救治",
    "核查",
    "回应",
    "通报",
    "检修",
    "整改",
    "恢复",
    "辟谣",
    "抽检",
    "召回",
    "入院",
)
DETAIL_MARKERS = (
    "仅",
    "其余",
    "其他",
    "其中",
    "已",
    "已经",
    "正在",
    "恢复",
    "继续",
    "名单",
    "通知",
    "批次",
    "多个部门",
)
OPINION_MARKERS = (
    "觉得",
    "认为",
    "明显",
    "不值得相信",
    "隐瞒",
    "混乱",
    "公关",
    "站不住脚",
    "离谱",
    "甩锅",
    "洗地",
    "吓人",
    "太假",
    "很假",
)
PREDICTION_MARKERS = ("可能", "预计", "预估", "或将", "恐将", "大概率", "猜测", "肯定会", "还会继续")
UNVERIFIABLE_MARKERS = (
    "匿名",
    "据传",
    "传闻",
    "爆料",
    "网传",
    "聊天记录",
    "群聊",
    "朋友圈",
    "网友称",
    "有人说",
    "知情人士",
    "内部员工",
    "很多内部员工",
    "很多家长",
    "家长已经确认",
    "多名家长",
)
OFFICIAL_RESPONSE_MARKERS = (
    "回应",
    "通报",
    "公告",
    "说明",
    "警方",
    "医院",
    "官方",
    "校方",
    "公司称",
    "运营公司称",
    "监管局",
)
PRESERVE_GENERIC_SUBJECT_PREFIXES = {"医院", "院方", "警方", "公安", "官方", "校方", "当地"}


@dataclass(frozen=True)
class ClaimExtraction:
    claims: List[ClaimItem]
    source: ClaimSourceType
    query_hints: Dict[str, List[str]] = field(default_factory=dict)


class ClaimExtractor:
    def extract(self, event: NormalizedEvent, provider_claims: Optional[List[ClaimItem]] = None) -> List[ClaimItem]:
        return self.extract_with_source(event, provider_claims=provider_claims).claims

    def extract_with_source(
        self,
        event: NormalizedEvent,
        provider_claims: Optional[List[ClaimItem]] = None,
    ) -> ClaimExtraction:
        if provider_claims:
            merged = self._refine_provider_claims(event, provider_claims)
            if merged:
                return ClaimExtraction(
                    claims=merged,
                    source="provider",
                    query_hints=self._build_query_hints(event, merged),
                )

        rule_claims = self._extract_rule_claims(event)
        if not rule_claims:
            fallback_text = (event.summary or event.title or event.raw_input).strip()
            if fallback_text:
                normalized = fallback_text if fallback_text.endswith("。") else f"{fallback_text}。"
                rule_claims = [ClaimItem(claim=normalized, claim_type=self.classify(normalized))]

        return ClaimExtraction(
            claims=rule_claims,
            source="rule",
            query_hints=self._build_query_hints(event, rule_claims),
        )

    def classify(self, claim: str, provider_type: Optional[str] = None) -> str:
        normalized = claim.strip()
        if any(token in normalized for token in OPINION_MARKERS):
            return "opinion"
        if any(token in normalized for token in UNVERIFIABLE_MARKERS) and not any(
            token in normalized for token in OFFICIAL_RESPONSE_MARKERS
        ):
            return "unverifiable"
        if any(token in normalized for token in PREDICTION_MARKERS):
            return "prediction"
        if provider_type in {"opinion", "prediction", "unverifiable"}:
            return provider_type
        return "fact"

    def _extract_rule_claims(self, event: NormalizedEvent) -> List[ClaimItem]:
        broad_trend_claim = rewrite_broad_trend_question_as_claim(event.raw_input)
        if event.input_type == "question_only" and broad_trend_claim:
            return [ClaimItem(claim=broad_trend_claim, claim_type="fact")]

        fragments = self._candidate_fragments(event)
        claims: List[ClaimItem] = []
        seen: set[str] = set()

        if event.fallback_used and event.input_type in {"url_news", "url_unknown"}:
            self._push_claim("当前链接页面缺少完整正文或正式来源。", claims, seen)

        for fragment in fragments:
            cleaned = self._normalize_fragment(fragment, context_subjects=self._event_subject_candidates(event), last_subject=None)
            if not cleaned or len(cleaned) < 6 or self._looks_like_scaffolding(cleaned):
                continue
            self._push_claim(cleaned, claims, seen)
            if len(claims) >= 6:
                break
        return claims[:6]

    def _refine_provider_claims(self, event: NormalizedEvent, provider_claims: Sequence[ClaimItem]) -> List[ClaimItem]:
        context_subjects = self._event_subject_candidates(event)
        best_by_claim: Dict[str, Tuple[int, int, int, ClaimItem]] = {}
        order = 0

        for item in provider_claims:
            fragments = self._expand_provider_claim(item.claim)
            last_subject: Optional[str] = None
            for fragment in fragments:
                cleaned = self._normalize_fragment(fragment, context_subjects=context_subjects, last_subject=last_subject)
                if not cleaned or self._looks_like_scaffolding(cleaned):
                    continue

                claim_type = self.classify(cleaned, provider_type=item.claim_type)
                role_rank = self._claim_role_rank(cleaned, claim_type)
                score = self._claim_score(cleaned, claim_type)
                claim_text = cleaned if cleaned.endswith("。") else f"{cleaned}。"
                claim_item = ClaimItem(claim=claim_text, claim_type=claim_type)
                key = claim_item.claim
                candidate = (role_rank, -score, order, claim_item)
                if key not in best_by_claim or candidate[:3] < best_by_claim[key][:3]:
                    best_by_claim[key] = candidate
                order += 1

                subjects = self._extract_subject_candidates(claim_text)
                if subjects:
                    last_subject = subjects[0]

        ordered = [item[3] for item in sorted(best_by_claim.values(), key=lambda value: (value[0], value[1], value[2]))]
        return ordered[:6]

    def _candidate_fragments(self, event: NormalizedEvent) -> List[str]:
        fragments: List[str] = []
        source_texts = [event.raw_input, event.summary]
        if event.input_type != "question_only":
            source_texts.append(event.title)

        for text in source_texts:
            if not text:
                continue
            for sentence in SPLIT_PATTERN.split(text):
                if not sentence.strip():
                    continue
                fragments.extend(self._split_compound_fragment(sentence))
        return fragments

    def _expand_provider_claim(self, claim: str) -> List[str]:
        fragments: List[str] = []
        for sentence in SPLIT_PATTERN.split(claim):
            if not sentence.strip():
                continue
            fragments.extend(self._split_compound_fragment(sentence))
        return fragments or [claim]

    def _split_compound_fragment(self, fragment: str) -> List[str]:
        clauses: List[str] = []
        comma_parts = [part.strip() for part in CLAUSE_SPLIT_PATTERN.split(fragment) if part.strip()]
        if not comma_parts:
            return []

        for part in comma_parts:
            if "：" in part or ":" in part:
                head, tail = re.split(r"[：:]", part, maxsplit=1)
                if head.strip() and tail.strip():
                    part = f"{head.strip()}{tail.strip()}"

            pieces = CONNECTOR_SPLIT_PATTERN.split(part)
            if len(pieces) == 1:
                clauses.append(part)
                continue

            current = pieces[0].strip()
            if current:
                clauses.append(current)
            for index in range(1, len(pieces), 2):
                connector = pieces[index].strip()
                tail = pieces[index + 1].strip() if index + 1 < len(pieces) else ""
                merged = f"{connector}{tail}".strip()
                if merged:
                    clauses.append(merged)

        return clauses or [fragment]

    def _push_claim(self, raw_text: str, claims: List[ClaimItem], seen: set[str]) -> None:
        normalized = re.sub(r"[。！？?!]+$", "", raw_text).strip()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        claim_text = normalized if normalized.endswith("。") else f"{normalized}。"
        claims.append(ClaimItem(claim=claim_text, claim_type=self.classify(claim_text)))

    def _normalize_fragment(
        self,
        fragment: str,
        *,
        context_subjects: Sequence[str],
        last_subject: Optional[str],
    ) -> str:
        cleaned = self._clean_fragment(fragment)
        if not cleaned:
            return ""

        cleaned = NOISY_PREFIX_PATTERN.sub("", cleaned).strip()
        if not cleaned:
            return ""

        topic_subject = self._topic_subject(context_subjects)
        if cleaned.startswith(CONTINUATION_MARKERS):
            anchor = topic_subject or last_subject
            if anchor:
                cleaned = f"{anchor}{cleaned}"
        elif self._starts_with_generic_subject(cleaned):
            if not any(cleaned.startswith(prefix) for prefix in PRESERVE_GENERIC_SUBJECT_PREFIXES):
                anchor = self._best_subject_for_fragment(cleaned, context_subjects, last_subject)
                if anchor:
                    cleaned = self._replace_generic_subject(cleaned, anchor)
        elif not self._extract_subject_candidates(cleaned):
            anchor = last_subject or topic_subject
            if anchor and any(marker in cleaned for marker in ACTION_MARKERS):
                cleaned = f"{anchor}{cleaned}"

        return cleaned if cleaned.endswith("。") else f"{cleaned}。"

    def _clean_fragment(self, fragment: str) -> str:
        cleaned = re.sub(r"^【[^】]+】", "", fragment).strip(" ，,：:；;")
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        for marker in LEADING_CONNECTORS:
            if cleaned.startswith(marker):
                cleaned = cleaned[len(marker) :].strip()
        for marker in QUESTION_TRAILING_MARKERS:
            if cleaned.endswith(marker):
                cleaned = cleaned[: -len(marker)].strip()
        cleaned = re.sub(r"[\"'“”‘’]+", "", cleaned)
        if cleaned.startswith(("http://", "https://")):
            return ""
        return cleaned

    def _looks_like_scaffolding(self, text: str) -> bool:
        return any(marker in text for marker in SCAFFOLDING_MARKERS)

    def _starts_with_generic_subject(self, text: str) -> bool:
        return any(text.startswith(prefix) for prefix in GENERIC_SUBJECT_PREFIXES)

    def _best_subject_for_fragment(
        self,
        fragment: str,
        context_subjects: Sequence[str],
        last_subject: Optional[str],
    ) -> Optional[str]:
        for prefix, hints in COMPATIBILITY_HINTS.items():
            if fragment.startswith(prefix):
                for candidate in list(filter(None, [last_subject])) + list(context_subjects):
                    if any(hint in candidate for hint in hints):
                        return candidate
                return None
        return last_subject or self._topic_subject(context_subjects)

    def _replace_generic_subject(self, fragment: str, anchor: str) -> str:
        for prefix in GENERIC_SUBJECT_PREFIXES:
            if fragment.startswith(prefix):
                if anchor.endswith(prefix):
                    replaced = f"{anchor}{fragment[len(prefix):]}"
                elif prefix in {"公司", "企业", "品牌方", "平台", "门店", "涉事门店"}:
                    replaced = f"{anchor}{fragment[len(prefix):]}"
                else:
                    replaced = f"{anchor}{fragment}"
                return replaced.strip()
        return f"{anchor}{fragment}".strip()

    def _claim_role_rank(self, claim: str, claim_type: str) -> int:
        if claim_type == "opinion":
            return 2
        if claim_type in {"prediction", "unverifiable"} and not any(marker in claim for marker in ACTION_MARKERS):
            return 2
        if any(marker in claim for marker in DETAIL_MARKERS) and any(marker in claim for marker in ACTION_MARKERS):
            return 1
        if any(marker in claim for marker in ACTION_MARKERS):
            return 0
        return 1

    def _claim_score(self, claim: str, claim_type: str) -> int:
        score = 0
        if any(marker in claim for marker in ACTION_MARKERS):
            score += 4
        if any(marker in claim for marker in ("回应", "通报", "核查", "整改", "恢复")):
            score += 2
        if re.search(r"\d", claim):
            score += 2
        if self._extract_subject_candidates(claim):
            score += 2
        if TIME_PATTERN.search(claim):
            score += 1
        if claim_type != "fact":
            score -= 1
        return score

    def _event_subject_candidates(self, event: NormalizedEvent) -> List[str]:
        ordered: List[str] = []
        seen = set()

        def push(candidate: Optional[str]) -> None:
            if not candidate:
                return
            cleaned = candidate.strip(" ，,：:；;。")
            if not cleaned or cleaned in GENERIC_SUBJECTS or cleaned in seen:
                return
            seen.add(cleaned)
            ordered.append(cleaned)

        for candidate in [event.source_name, *(event.keywords or [])]:
            push(candidate)
        combined = " ".join(filter(None, [event.title, event.summary, event.raw_input]))
        for candidate in self._extract_subject_candidates(combined):
            push(candidate)
        return ordered

    def _extract_subject_candidates(self, text: str) -> List[str]:
        ordered: List[str] = []
        seen = set()

        def push(candidate: str) -> None:
            cleaned = candidate.strip(" ，,：:；;。")
            if not cleaned or cleaned in GENERIC_SUBJECTS or cleaned in seen:
                return
            seen.add(cleaned)
            ordered.append(cleaned)

        for candidate in extract_subject_anchors(text):
            push(candidate)
        for candidate in SUBJECT_SUFFIX_PATTERN.findall(text):
            push(candidate)
        for candidate in SUBJECT_BEFORE_ACTION_PATTERN.findall(text):
            push(candidate)
        return ordered

    def _topic_subject(self, candidates: Sequence[str]) -> Optional[str]:
        if not candidates:
            return None
        preferred = [item for item in candidates if not item.endswith(("公司", "集团", "运营公司"))]
        if preferred:
            return min(preferred, key=len)
        return min(candidates, key=len)

    def _build_query_hints(self, event: NormalizedEvent, claims: Sequence[ClaimItem]) -> Dict[str, List[str]]:
        query_hints: Dict[str, List[str]] = {}
        context_subjects = self._event_subject_candidates(event)

        for item in claims:
            subjects = self._extract_subject_candidates(item.claim) or list(context_subjects)
            topic_subject = self._topic_subject(subjects)
            actions = [marker for marker in ACTION_MARKERS if marker in item.claim]
            numbers = re.findall(r"\d+(?:\.\d+)?%?", item.claim)
            times = [match.group(0) for match in TIME_PATTERN.finditer(item.claim)]

            queries: List[str] = []
            base_tokens = self._dedupe_tokens(([topic_subject] if topic_subject else []) + actions + numbers + times)
            if base_tokens:
                queries.append(" ".join(base_tokens[:6]))

            official_tokens = self._dedupe_tokens(([topic_subject] if topic_subject else []) + actions + ["回应", "通报", "官方"])
            if official_tokens:
                queries.append(" ".join(official_tokens[:6]))

            source_tokens = self._dedupe_tokens(([topic_subject] if topic_subject else []) + actions + ([event.source_name] if event.source_name else []))
            if source_tokens:
                queries.append(" ".join(source_tokens[:6]))

            query_hints[item.claim] = self._dedupe_tokens(queries)[:3]
        return query_hints

    def _dedupe_tokens(self, values: Sequence[str]) -> List[str]:
        ordered: List[str] = []
        seen = set()
        for item in values:
            cleaned = item.strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            ordered.append(cleaned)
        return ordered
