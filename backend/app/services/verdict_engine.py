from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from backend.app.models.schemas import (
    AnalyzeRequest,
    ClaimItem,
    ClaimResult,
    EvidenceGap,
    EvidenceItem,
    EvidenceSourceType,
    NormalizedEvent,
)
from backend.app.services.claim_correction import annotate_claim_corrections
from backend.app.services.entity_anchor import (
    candidate_matches_subject_anchors,
    extract_subject_anchors,
    text_contains_subject_mismatch,
)
from backend.app.services.evidence_goals import apply_evidence_goals
from backend.app.services.llm_verdict import llm_judge_claims
from backend.app.services.page_fetcher import fetch_page_snippets
from backend.app.services.question_intent import detect_trend_topic, is_broad_trend_claim
from backend.app.services.retrieval_models import RetrievalBundle

_SHANGHAI_TZ = timezone(timedelta(hours=8))
# Undated evidence sorts AFTER any dated evidence in recency order — mirrors
# SearchResult.effective_published_dt so the two layers agree on "no date = oldest".
_DATELESS_SENTINEL = datetime(1970, 1, 1, tzinfo=_SHANGHAI_TZ)
_EXPLICIT_CURRENT_MARKERS = ("目前", "现在", "当前", "今天", "今日", "本周", "本月", "今年")
_CURRENT_SERVICE_STATE = re.compile(r"开放|闭馆|开馆|营业|停业|开业|停课|复课|停运|运营|收费|免票|门票|票价|购房资格|限购|预约")
_CALENDAR_DATE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?:年|[-/])(\d{1,2})(?:月|[-/])(\d{1,2})(?:日|号)?(?!\d)")


def _has_calendar_date(text: str) -> bool:
    for match in _CALENDAR_DATE.finditer(text):
        try:
            datetime(*(int(value) for value in match.groups()))
        except ValueError:
            continue
        return True
    return False


def _evidence_published_dt(item: EvidenceItem) -> datetime | None:
    """Parse EvidenceItem.published_at (ISO string) to a tz-aware datetime.

    Returns None when absent or unparseable. Mirrors SearchResult.published_dt so
    recency comparisons behave identically whether we hold a SearchResult or the
    EvidenceItem projected from it."""
    if not item.published_at:
        return None
    try:
        parsed = datetime.fromisoformat(item.published_at)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_SHANGHAI_TZ)
    return parsed


# Claim markers that make recency probative: a claim asserting something is the
# *current* state is weakened by evidence that is all stale, so for these we let
# publication time break ties in evidence selection (never the verdict itself).
TIME_SENSITIVE_CLAIM_MARKERS = (
    "最新",
    "近日",
    "近期",
    "刚刚",
    "日前",
    "今日",
    "今天",
    "本月",
    "本周",
    "今年",
    "目前",
    "现在",
    "当前",
    "已经",
    "正式",
    "宣布",
)

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
    "不可能",
    "实为",
    "并非",
    "不再",
    "取消",
    "系伪造",
    "为伪造",
    "不属实",
    "恶意谣言",
    "暂无",
    "不能精确",
    "无法实现",
    "运行正常",
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


def _confidence_bucket(confidence: object) -> str:
    """Collapse a categorical or numeric confidence into high/medium/low."""
    if isinstance(confidence, (int, float)):
        if confidence >= 0.8:
            return "high"
        if confidence >= 0.5:
            return "medium"
        return "low"
    if confidence in {"high", "medium", "low"}:
        return str(confidence)
    return "low"


# Deterministic verdict+confidence -> P(true) mapping for the zero-LLM fast path.
# These are coarse, rule-derived numbers (no world knowledge), so they are always
# tagged basis="evidence" when a grounded verdict backs them, and basis="prior"
# for insufficient (no information -> 50/50 midpoint, not a knowledge claim).
_COARSE_PROBABILITY_TABLE = {
    "supported": {"high": 90.0, "medium": 75.0, "low": 62.0},
    "refuted": {"high": 10.0, "medium": 22.0, "low": 32.0},
}


def coarse_truth_probability(
    verdict: str, confidence: object, *, has_evidence: bool = True
) -> tuple[float, str]:
    """Map a rule verdict+confidence to a coarse P(true) and its basis.

    Used only by the fast path, which never invokes an LLM: it turns the existing
    verdict/confidence into a number without pretending to have common-sense
    judgement. ``conflicting`` and ``insufficient`` both center on 50 — the former
    because sources disagree (evidence-backed), the latter because we simply have
    no information (prior)."""
    bucket = _confidence_bucket(confidence)
    if verdict in _COARSE_PROBABILITY_TABLE:
        probability = _COARSE_PROBABILITY_TABLE[verdict][bucket]
        basis = "evidence" if has_evidence else "prior"
        return probability, basis
    if verdict == "conflicting":
        return 50.0, "evidence" if has_evidence else "prior"
    # insufficient / unknown: no information -> honest 50/50, prior basis.
    return 50.0, "prior"
QUANTITY_TOKEN_PATTERN = re.compile(
    r"\d+(?:\.\d+)?%|\d+(?:\.\d+)?(?:万|亿)?(?:元|人|名|例|起|条|线|艘|班|个|年|月|天|小时|分钟)"
)
QUANTITATIVE_CORRECTION_MARKERS = ("并非", "实际", "而是", "仅为", "最高", "不超过", "更正")
# Compare measurements, not bags of number strings. Attribute families are
# intentionally conservative: unrecognized quantities do not establish a
# contradiction by themselves. The ordinary evidence alignment still runs.
_MEASUREMENT = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<scale>百|千|万|亿)?\s*"
    r"(?P<unit>%|元|人|名|位|例|起|条线|条|艘|班|个|家|栋|天|小时|分钟)"
)
_MEASUREMENT_ATTRIBUTES = (
    ("recruitment", r"招聘|招收|招募|招了|招(?=\d)"),
    ("layoffs", r"裁员|裁减|解雇"),
    ("injuries", r"受伤|伤者|伤员"),
    ("deaths", r"死亡|遇难|死者"),
    ("cases", r"确诊|病例|感染"),
    ("staff", r"员工|职工|在职|共有"),
    ("salary", r"工资|薪资|薪酬|月薪|年薪|日薪|时薪"),
    ("price", r"票价|售价|价格|门票|收费"),
    ("revenue", r"营收|营业收入|销售额"),
    ("profit", r"净利润|利润"),
)
_MEASUREMENT_ACTION = re.compile("|".join(f"(?P<a{i}>{pattern})" for i, (_, pattern) in enumerate(_MEASUREMENT_ATTRIBUTES)))
_MEASUREMENT_SCOPE = re.compile(r"新增|累计|总人数|总数|合计|共有|全职|兼职")
_MEASUREMENT_TIME = re.compile(
    r"(?:19|20)\d{2}(?:年(?:\d{1,2}月(?:\d{1,2}[日号])?)?|[-/]\d{1,2}[-/]\d{1,2})"
    r"|\d{1,2}时(?:\d{1,2}分)?"
)
_MEASUREMENT_PERIOD = re.compile(r"月薪|年薪|日薪|时薪|每月|每年|每日|每小时")
_MEASUREMENT_BOUND = re.compile(r"最高|最多|不超过|至多|最低|至少|不少于|超过|多于|不足|少于")
_MEASUREMENT_NOISE = re.compile(
    r"招聘规模|招聘人数|招聘数量|规模|人数|数量|总人数|总数|实际|事实上|目前|本次|本轮|"
    r"新增|累计|合计|共有|截至|截止|已确认|确认|据称|网传|宣布|此前|传闻|消息|"
    r"今日|今天|现已|已经|正式|应为|仅为|更正为|而是|最高|最多|不超过|最低|至少|"
    r"明确表示|表示|没有|并未|尚未|并非|否认|"
    r"在|于|为|的|了|共|有|是|\s|[：:、]"
)


def _measurement_context(text: str) -> str:
    return _MEASUREMENT_NOISE.sub("", _MEASUREMENT_TIME.sub("", text)).strip()


@dataclass(frozen=True)
class _Measurement:
    value: Decimal
    unit: str
    attribute: str
    scope: frozenset[str]
    context: str
    time: tuple[tuple[int, ...], ...]
    period: str
    bounded: bool
    corrected: bool
    denied: bool


def _measurements(text: str, *, default_context: str = "") -> list[_Measurement]:
    measurements = []
    for sentence in re.split(r"[。！？!?\n]", text):
        clauses = re.split(r"[，,；;]", sentence)
        inherited: _Measurement | None = None
        sentence_time: tuple[tuple[int, ...], ...] = ()
        statement_context = ""
        for index, clause in enumerate(clauses):
            matches = list(_MEASUREMENT.finditer(clause))
            if not matches:
                dates = tuple(tuple(map(int, re.findall(r"\d+", value)))
                              for value in _MEASUREMENT_TIME.findall(clause))
                if dates:
                    sentence_time = dates
                if re.search(r"(?:表示|通报|说明|宣布|回应)\s*$", clause):
                    statement_context = _measurement_context(re.sub(r"(?:通报|说明|回应)\s*$", "", clause))
                continue
            actions = list(_MEASUREMENT_ACTION.finditer(clause))
            for measurement_index, match in enumerate(matches):
                start = matches[measurement_index - 1].end() if measurement_index else 0
                end = matches[measurement_index + 1].start() if measurement_index + 1 < len(matches) else len(clause)
                local_actions = [action for action in actions if start <= action.start() < end]
                nearest = min(local_actions, key=lambda action: min(
                    abs(action.end() - match.start()), abs(action.start() - match.end())
                ), default=None)
                # Role nouns within a recruitment phrase are objects, whereas
                # "招聘结束后员工2000人" describes a different population.
                recruitment = next((action for action in local_actions if action.lastgroup == "a0"), None)
                if nearest and nearest.lastgroup == "a5" and recruitment and re.fullmatch(
                    r"新?", clause[recruitment.end():nearest.start()]
                ):
                    nearest = recruitment
                # Generic "共有5人受伤" takes the explicit following predicate.
                if nearest and nearest.group() == "共有":
                    following_action = next((action for action in local_actions
                                             if action.start() >= match.end()), None)
                    nearest = following_action or nearest
                attribute = _MEASUREMENT_ATTRIBUTES[int(nearest.lastgroup[1:])][0] if nearest else ""
                prefix_end = nearest.start() if nearest and nearest.start() < match.start() else match.start()
                if nearest and nearest.start() < match.start():
                    # Adjacent synonyms can form one predicate ("确诊病例").
                    # Do not turn the earlier synonym into a subject qualifier
                    # merely because the last synonym is closest to the number.
                    for action in reversed(local_actions):
                        if action.lastgroup == nearest.lastgroup and action.end() == prefix_end:
                            prefix_end = action.start()
                prefix = clause[start:prefix_end]
                # Limit correction/polarity to this measurement's relation.
                next_action = min((action.start() for action in actions
                                   if action.start() >= match.end() and action != nearest), default=end)
                local_end = min(end, next_action)
                local = clause[start:local_end]
                correction = any(marker in local for marker in QUANTITATIVE_CORRECTION_MARKERS)
                context = _measurement_context(prefix)
                inherited_correction = not attribute and correction and not context and inherited is not None
                if inherited_correction:
                    attribute = inherited.attribute
                # Unknown predicates retain their literal relation rather than
                # disappearing and permitting a later lexical-support shortcut.
                if not attribute:
                    attribute = "literal"
                    if statement_context and statement_context not in context:
                        context = statement_context + context
                dates = tuple(tuple(map(int, re.findall(r"\d+", value)))
                              for value in _MEASUREMENT_TIME.findall(local))
                time = dates or sentence_time
                scope = frozenset("total" if value in {"总人数", "总数", "合计", "共有"} else value
                                  for value in _MEASUREMENT_SCOPE.findall(local))
                periods = _MEASUREMENT_PERIOD.findall(local)
                period = {"月薪": "month", "每月": "month", "年薪": "year", "每年": "year",
                          "日薪": "day", "每日": "day", "时薪": "hour", "每小时": "hour"}.get(periods[-1], "") if periods else ""
                if context in {"公司", "该公司", "本公司", "该机构", "本机构"} and default_context:
                    context = default_context
                elif not context:
                    context = inherited.context if inherited else default_context
                if inherited_correction:
                    time = time or inherited.time
                    scope = scope or inherited.scope
                    period = period or inherited.period
                following = clauses[index + 1] if index + 1 < len(clauses) else ""
                if not _MEASUREMENT.search(following) and not _MEASUREMENT_ACTION.search(following):
                    correction |= bool(re.fullmatch(r"\s*(?:并非|不是|更正)[^，,。]{0,16}(?:传闻|数字|说法|数量)[^，,。]*", following))
                denied = bool(re.search(r"传言不实|报道有误|消息不实|并非|不属实|不是|没有|并未", local))
                scale = {None: 1, "百": 100, "千": 1000, "万": 10000, "亿": 100000000}[match.group("scale")]
                unit = match.group("unit")
                unit = "person" if unit in {"人", "名", "位"} else unit
                current = _Measurement(Decimal(match.group("value")) * scale,
                                       unit, attribute, scope, context, time, period,
                                       bool(_MEASUREMENT_BOUND.search(local)), correction, denied)
                measurements.append(current)
                inherited = current
    return measurements


def _same_measurement_relation(expected: _Measurement, actual: _Measurement) -> bool:
    # Missing scope, date or period is uncertainty, not a wildcard. Named
    # contexts must align locally; a different entity elsewhere in the document
    # cannot borrow the claim subject from the first sentence.
    return (actual.unit == expected.unit and actual.attribute == expected.attribute
            and actual.scope == expected.scope and actual.time == expected.time
            and actual.period == expected.period
            and bool(expected.context) and expected.context in actual.context)


SUPERSESSION_MARKERS = (
    "不再",
    "现行",
    "最新规定",
    "正式实施",
    "开始施行",
    "截图来自",
    "旧闻",
    "运行正常",
)
SUPERSESSION_EFFECTIVE_DATE_PATTERN = re.compile(
    r"自.{0,24}(?:起|开始|施行|实施)"
)
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
SUBJECT_DISCLAIMER_MARKERS = (
    "another patient",
    "another person",
    "another case",
    "another creator",
    "another influencer",
    "not the same",
    "does not confirm",
    "not confirm",
    "without verifying",
    "不是同一",
    "并非同一",
    "另一位",
    "另一起",
    "无法确认",
    "未能确认",
)
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
    claim_results: list[ClaimResult]
    evidence: list[EvidenceItem]
    evidence_grade: str
    evidence_source: EvidenceSourceType


class VerdictEngine:
    def evaluate(
        self,
        *,
        request: AnalyzeRequest,
        event: NormalizedEvent,
        claims: list[ClaimItem],
        retrieval_bundle: RetrievalBundle | None = None,
    ) -> tuple[list[ClaimResult], list[EvidenceItem], str]:
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
        claims: list[ClaimItem],
        retrieval_bundle: RetrievalBundle | None = None,
        completion_fn=None,
    ) -> VerdictEvaluation:
        evidence_pool, evidence_grade, evidence_source = self._resolve_evidence_pool(
            request=request,
            event=event,
            retrieval_bundle=retrieval_bundle,
        )

        # Fetch page content for top results to enrich correction context
        page_bodies: dict[str, str] = {}
        if retrieval_bundle and retrieval_bundle.canonical_results:
            page_bodies = fetch_page_snippets(retrieval_bundle.canonical_results)

        results: list[ClaimResult] = []
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
                        notes=self._empty_evidence_note(retrieval_bundle),
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

        results = llm_judge_claims(results, completion_fn=completion_fn)

        results = annotate_claim_corrections(
            results,
            page_bodies=page_bodies,
            all_evidence_titles=[
                r.title for r in (retrieval_bundle.canonical_results if retrieval_bundle else [])
                if r.title.strip()
            ],
            completion_fn=completion_fn,
        )

        # Rule fallback safety net: when the rule/LLM judge path selected almost
        # nothing but the retrieval bundle clearly has high-tier evidence, attach
        # the strongest hits to the main fact claim so the report actually shows
        # the material we collected. Without this, LLM synthesis failing quietly
        # yields "证据不足" while the trace lists 20+ canonical hits — the exact
        # 耿同学 / Nature 撤稿 case that motivated this. See rumor-checking task
        # #16 for context.
        results = self._backfill_rule_fallback_evidence(
            results=results,
            evidence_pool=evidence_pool,
        )

        results = apply_evidence_goals(results, retrieval_bundle, page_bodies,
                                       raw_evidence=evidence_pool if evidence_source == "request_mock" else None)
        results = self._guard_undated_current_claims(results, evidence_pool, retrieval_bundle, page_bodies)
        return VerdictEvaluation(
            claim_results=results,
            evidence=evidence_pool,
            evidence_grade=evidence_grade,
            evidence_source=evidence_source,
        )

    @staticmethod
    def _guard_undated_current_claims(
        results: list[ClaimResult], evidence_pool: list[EvidenceItem],
        bundle: RetrievalBundle | None, page_bodies: dict[str, str],
    ) -> list[ClaimResult]:
        # Run after every verdict/correction/property pass so a model cannot
        # silently reinstate certainty about an undated current arrangement.
        # This checks only the existence of a time anchor, not its freshness.
        raw_by_url: dict[str, list[EvidenceItem]] = {}
        for item in evidence_pool:
            raw_by_url.setdefault(item.url, []).append(item)
        bodies_by_url = dict(page_bodies)
        for item in bundle.canonical_results if bundle else ():
            if item.result_id in page_bodies:
                bodies_by_url[item.url] = page_bodies[item.result_id]
        guarded = []
        for result in results:
            if (result.claim_type != "fact"
                    or not any(marker in result.claim for marker in _EXPLICIT_CURRENT_MARKERS)
                    or not _CURRENT_SERVICE_STATE.search(result.claim)):
                guarded.append(result)
                continue
            cited = [raw for item in result.evidence for raw in raw_by_url.get(item.url, [])]
            if any(_evidence_published_dt(item) is not None
                   or _has_calendar_date(f"{item.snippet}\n{bodies_by_url.get(item.url, '')}") for item in cited):
                guarded.append(result)
                continue
            description = "当前状态的关联证据缺少可核验发布日期或正文年月日时间锚，无法确认其适用于当前。"
            gaps = list(result.evidence_gaps)
            if not any(gap.dimension == "time" for gap in gaps):
                gaps.append(EvidenceGap(dimension="time", description=description,
                                        suggested_queries=[f"{result.claim[:100]} 最新 官方 日期 适用时间"]))
            guarded.append(result.model_copy(update={
                "verdict": "insufficient", "confidence": "low", "correction": None,
                "truth_probability": None, "probability_basis": None, "evidence_gaps": gaps,
                "notes": f"{result.notes} 时间证据缺口：{description}",
            }))
        return guarded

    def _backfill_rule_fallback_evidence(
        self,
        *,
        results: list[ClaimResult],
        evidence_pool: list[EvidenceItem],
    ) -> list[ClaimResult]:
        """Attach the top B/A/S-tier retrieval hits to the main fact claim when
        the rule / LLM judge path returned near-empty evidence despite the pool
        having plenty of high-tier material.

        This only fires as a rescue: when at least one fact claim exists, the
        combined attached evidence across all fact claims is ≤ 1, and the pool
        contains ≥ 3 tier-B-or-better hits. The attached items carry a stance
        of ``ambiguous`` and a note that they were surfaced by fallback so
        downstream reporting doesn't over-claim their probative weight.
        """
        fact_results = [cr for cr in results if cr.claim_type == "fact"]
        if not fact_results:
            return results
        attached_urls: set[str] = set()
        for cr in fact_results:
            for ev in cr.evidence:
                if ev.url:
                    attached_urls.add(ev.url)
        if len(attached_urls) > 1:
            return results
        high_tier_pool = [item for item in evidence_pool if item.source_tier in {"S", "A", "B"} and item.url]
        if len(high_tier_pool) < 3:
            return results

        # Pick top hits by tier priority then most recent publication. Undated
        # hits fall back to a fixed-past sentinel so they sort after dated ones
        # instead of being ordered by the meaningless length of their date string.
        def _rank_key(item: EvidenceItem) -> tuple[int, float]:
            tier_rank = {"S": 0, "A": 1, "B": 2}.get(item.source_tier, 3)
            dt = _evidence_published_dt(item) or _DATELESS_SENTINEL
            return (tier_rank, -dt.timestamp())

        ranked = sorted(high_tier_pool, key=_rank_key)
        # Only attach hits that actually mention the claim's subject. The backfill
        # historically stapled the top-tier hits on regardless, which surfaced
        # 京东镇 (a village) and a 京东白条 scam notice as S-tier "evidence" for a
        # 京东-the-company layoff claim — off-subject material wearing an
        # authoritative badge. `_mentions_claim_subject` does a boundary-aware
        # check so 京东镇/京东白条 no longer count as a 京东 mention.
        subject_terms = self._claim_subject_terms(fact_results[0].claim)
        # Deduplicate by URL and cap at 3 to avoid drowning the panel.
        picked: list[EvidenceItem] = []
        seen: set[str] = set(attached_urls)
        for item in ranked:
            if item.url in seen:
                continue
            haystack = f"{item.title} {item.snippet}"
            if subject_terms and not self._mentions_claim_subject(haystack, subject_terms):
                continue
            seen.add(item.url)
            # REPLACE the category-derived relevance line (which asserts "官方来源
            # 直接提及当前事件" purely from the domain) — keeping it alongside
            # "未做主体核对" was self-contradictory. This is fallback material whose
            # subject alignment we have NOT confirmed; say exactly that.
            picked.append(item.model_copy(update={
                "stance": "ambiguous",
                "stance_quote": None,
                "relevance_reason": "[规则兜底] 顶部检索材料，主体未逐条核对，仅作参考，未必直接支持本说法。",
            }))
            if len(picked) >= 3:
                break
        if not picked:
            return results

        # Attach to the first (main) fact claim. Splitting across claims risks
        # implying subject alignment we don't have — one clear pile is cleaner.
        target = fact_results[0]
        target_idx = results.index(target)
        merged_evidence = list(target.evidence) + picked
        note_suffix = f"\n[规则兜底] 已追加 {len(picked)} 条检索命中作为参考材料。"
        updated_claim = target.model_copy(update={
            "evidence": merged_evidence,
            "notes": (target.notes or "") + note_suffix,
        })
        results = list(results)
        results[target_idx] = updated_claim
        return results

    # Brand/proper-noun tokens the backfill uses to gate off-subject hits. Kept
    # deliberately small and unambiguous; a 2-char brand that is also a common
    # place-name prefix (阿里/字节) is omitted for the same reason retrieval_service
    # omits them — the boundary check below still guards the ones we keep.
    _BACKFILL_SUBJECT_BRANDS = (
        "拼多多", "京东", "淘宝", "阿里巴巴", "腾讯", "百度", "美团", "字节跳动", "华为", "小米",
    )
    # CJK chars that, immediately after a brand, form a DIFFERENT proper noun —
    # 京东镇 (a village), 京东白条 (a product). A brand followed by one of these is
    # not a mention of the company itself.
    _BRAND_COMPOUND_SUFFIXES = ("镇", "村", "区", "县", "市", "省", "路", "街", "白条", "金融", "白")

    def _claim_subject_terms(self, claim_text: str) -> list[str]:
        """Brand names the claim itself names — the subjects any backfilled hit
        must actually be about. Empty when the claim names no known brand (then
        the backfill does not subject-gate, preserving prior behavior)."""
        normalized = self._normalize_claim(claim_text)
        return [brand for brand in self._BACKFILL_SUBJECT_BRANDS if brand in normalized]

    def _mentions_claim_subject(self, text: str, subject_terms: list[str]) -> bool:
        """True if `text` mentions any subject brand as the brand itself — not as a
        prefix of a different compound noun (京东镇/京东白条 do NOT count as 京东)."""
        haystack = self._normalize_claim(text)
        for brand in subject_terms:
            start = 0
            while True:
                idx = haystack.find(brand, start)
                if idx < 0:
                    break
                tail = haystack[idx + len(brand):]
                if not any(tail.startswith(suffix) for suffix in self._BRAND_COMPOUND_SUFFIXES):
                    return True
                start = idx + len(brand)
        return False

    def _empty_evidence_note(self, retrieval_bundle: RetrievalBundle | None) -> str:
        # A live search that ran cleanly but came back with no on-topic hits is a
        # different signal from "we never searched" or "the search errored" — say so
        # plainly instead of implying the input itself was thin. The probability
        # layer still reports a 50/50 prior here (basis="prior"), so the note carries
        # the honesty about *why*. Only claim "已联网检索" when the provider actually
        # ran without failing or degrading to a fallback.
        searched_live = (
            retrieval_bundle is not None
            and retrieval_bundle.provider_name not in ("mock", "off")
            and not retrieval_bundle.fallback_used
            and not retrieval_bundle.failure_detail
        )
        if searched_live:
            return "已联网检索，但未找到与该说法相关的公开报道，无法核验真伪。"
        return "当前输入缺少可核验的证据链，先保持保守。"

    def _resolve_evidence_pool(
        self,
        *,
        request: AnalyzeRequest,
        event: NormalizedEvent,
        retrieval_bundle: RetrievalBundle | None = None,
    ) -> tuple[list[EvidenceItem], str, EvidenceSourceType]:
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

    def _grade_evidence_items(self, evidence_items: list[EvidenceItem]) -> str:
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
        evidence_pool: list[EvidenceItem],
        subject_anchors: list[str],
    ) -> tuple[str, str, str, list[EvidenceItem]]:
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
        supporting: list[EvidenceItem] = []
        refuting: list[EvidenceItem] = []
        relevant: list[EvidenceItem] = []
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
                subject_anchors=subject_anchors,
                anchor_context=item.source_name,
                measurement_attributes=frozenset(item.attribute for item in _measurements(normalized_claim)),
            )
            if matched_segment:
                relevant.append(item)
                if segment_supports:
                    supporting.append(item)
                if segment_refutes:
                    refuting.append(item)
                continue

        # For claims asserting a *current* state ("最新/近日/已经宣布"…), recency is
        # a tiebreaker within the same source tier when choosing which evidence to
        # show. Source authority remains primary and verdict logic is unchanged.
        if self._is_time_sensitive_claim(claim_text, normalized_claim):
            def _recency_key(item: EvidenceItem) -> tuple[int, float]:
                dt = _evidence_published_dt(item) or _DATELESS_SENTINEL
                return (TIER_PRIORITY.get(item.source_tier, 99), -dt.timestamp())

            supporting.sort(key=_recency_key)
            refuting.sort(key=_recency_key)
            relevant.sort(key=_recency_key)

            superseding_result = self._evaluate_superseding_evidence(
                supporting=supporting,
                refuting=refuting,
            )
            if superseding_result is not None:
                return superseding_result

            aligned = supporting + refuting
            if aligned and all(_evidence_published_dt(item) is None for item in aligned):
                return (
                    "insufficient",
                    "low",
                    "该说法描述当前状态，但关联证据没有可核验日期，无法确认其仍然有效。",
                    aligned[:2],
                )

        # Only weigh a quantitative conflict against evidence we've already
        # deemed on-topic for this claim (subject-anchor + term overlap). Scanning
        # the raw pool let an unrelated source's number masquerade as a conflict —
        # e.g. a "美团裁员50%" claim flipped to 各方矛盾 by a "Meta 裁员20%" article
        # that the subject gate had already rejected.
        quantitative_conflict = self._detect_quantitative_conflict(
            claim_text=normalized_claim,
            evidence_pool=relevant,
        )
        if quantitative_conflict is not None:
            return quantitative_conflict

        if supporting and refuting:
            supporting_high_trust = [item for item in supporting if item.source_tier in HIGH_TRUST_SOURCE_TIERS]
            refuting_high_trust = [item for item in refuting if item.source_tier in HIGH_TRUST_SOURCE_TIERS]
            supporting_decisive = self._has_any_high_trust_hit(supporting_high_trust)
            refuting_decisive = self._has_any_high_trust_hit(refuting_high_trust)
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
            if self._has_any_high_trust_hit(high_trust_hits):
                confidence = self._confidence_from_high_trust_hits(high_trust_hits)
                return "refuted", confidence, "检索到与该说法高度相关的辟谣或否认来源，当前更倾向于判定为不成立。", refuting[:2]
            return "insufficient", "low", "相关证据存在否定信号，但可信度还不足以强判。", refuting[:2]
        if supporting:
            high_trust_hits = [item for item in supporting if item.source_tier in HIGH_TRUST_SOURCE_TIERS]
            if self._has_any_high_trust_hit(high_trust_hits):
                confidence = self._confidence_from_high_trust_hits(high_trust_hits)
                return "supported", confidence, "检索到与该说法高度相关的公开来源，当前更倾向于判定为成立。", supporting[:2]
            return "insufficient", "low", "找到了一些相关来源，但可信度还不足以强判。", supporting[:2]
        if relevant:
            return "insufficient", "low", "检索到了相关主体的公开报道，但其内容未直接涉及该具体说法，无法判定。", relevant[:2]
        if subject_anchors:
            return "insufficient", "low", f"已联网检索，未找到直接提及「{'、'.join(subject_anchors[:2])}」与该说法相关的公开报道。", []
        return "insufficient", "low", "检索结果与该说法的语义重合仍不足，先保持保守。", []

    def _subject_anchors_for_claim(self, *, claim_text: str, event: NormalizedEvent) -> list[str]:
        if is_broad_trend_claim(claim_text):
            return []
        claim_anchors = self._filter_subject_anchors(extract_subject_anchors(claim_text))
        if claim_anchors:
            return claim_anchors
        # The claim names no subject of its own. This is the split-sub-claim case:
        # "京东在今年…裁员" splits into "…裁员" + "主要针对的是中层", and the
        # predicate-only half loses 京东, so it floats with no anchor and the rule
        # engine can't align it to the obvious 京东砍层级 hits. Inherit the event's
        # subject so a split half still matches evidence about the same entity.
        # (Previously only question_only input fell back here, which missed the far
        # more common text_news split case.)
        return self._filter_subject_anchors(
            extract_subject_anchors(" ".join(filter(None, [event.title, event.summary, event.raw_input])))
        )

    def _filter_subject_anchors(self, anchors: list[str]) -> list[str]:
        return [anchor for anchor in anchors if not any(marker in anchor for marker in UNRELIABLE_ANCHOR_MARKERS)]

    def _evaluate_source_gap_claim(self, evidence_pool: list[EvidenceItem]) -> tuple[str, str, str, list[EvidenceItem]] | None:
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
        evidence_pool: list[EvidenceItem],
        subject_anchors: list[str],
    ) -> tuple[str, str, str, list[EvidenceItem]] | None:
        if subject_anchors or not is_broad_trend_claim(claim_text):
            return None

        topic = detect_trend_topic(normalized_claim) or detect_trend_topic(claim_text)
        if topic is None:
            return None

        supporting: list[EvidenceItem] = []
        for item in evidence_pool:
            haystack = self._normalize_claim(f"{item.title} {item.snippet} {item.source_name}")
            if topic not in haystack or self._contains_evidence_refutation(haystack):
                continue
            supporting.append(item)

        high_trust_hits = [item for item in supporting if item.source_tier in HIGH_TRUST_SOURCE_TIERS]
        if self._has_any_high_trust_hit(high_trust_hits):
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
        evidence_pool: list[EvidenceItem],
        subject_anchors: list[str],
    ) -> tuple[str, str, str, list[EvidenceItem]] | None:
        if not any(marker in claim_text or marker in normalized_claim for marker in RESOLUTION_CLAIM_MARKERS):
            return None

        unresolved_signals: list[EvidenceItem] = []
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
            ("死了", "死亡"),
            ("裁了", "裁员"),
            ("裁掉", "裁员"),
            ("停了", "停产"),
            ("关了", "停业"),
            ("倒了", "倒闭"),
            ("跑了", "跑路"),
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

    def _extract_terms(self, text: str) -> list[str]:
        ordered: list[str] = []
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

        # Strip high-frequency function chars before CJK chunking so they
        # don't pollute bigram windows (e.g. "\u7684\u4ea7\u54c1" \u2192 "\u4ea7\u54c1")
        cjk_text = re.sub(r"[\u7684\u4e86\u5728\u8fc7\u7740\u628a\u88ab\u8ba9\u7ed9\u8ddf]", "", text)
        for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", cjk_text):
            if len(chunk) <= 4:
                push(chunk)
                # Also emit 2-char bigrams so entities like "\u7f8e\u56e2" match
                if len(chunk) >= 3:
                    for idx in range(len(chunk) - 1):
                        push(chunk[idx : idx + 2])
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
        claim_terms: list[str],
        claim_is_negative: bool,
        full_scope_claim: bool,
        subject_anchors: list[str] | None = None,
        anchor_context: str | None = None,
        measurement_attributes: frozenset[str] = frozenset(),
    ) -> tuple[bool, bool, bool]:
        matched_segment = False
        segment_supports = False
        segment_refutes = False
        anchor_cores = self._anchor_cores(subject_anchors) if subject_anchors else None
        # The entity name can live only in a structured field (e.g. source_name =
        # "中国科学技术大学") while the body uses an abbreviation ("中科大"). Let the
        # anchor-core identity gate see that context WITHOUT feeding it into term
        # overlap or support/refute scoring — those must stay driven by the segment
        # text alone, or an authoritative source_name would inflate matches.
        anchor_context_norm = self._normalize_claim(anchor_context) if anchor_context else ""
        for segment in re.split(r"[。！？!?；;\n]", segment_text):
            if measurement_attributes:
                # Do not borrow polarity from a separately quantified attribute:
                # "招聘2000人，工资并非8000元" still supports the hiring count.
                clauses = []
                for clause in re.split(r"[，,]", segment):
                    attributes = {item.attribute for item in _measurements(clause)}
                    if attributes and attributes.isdisjoint(measurement_attributes):
                        continue
                    clauses.append(clause)
                segment = "，".join(clauses)
            haystack = self._normalize_claim(segment)
            overlap = self._overlap_terms(claim_terms, haystack)
            if not haystack:
                continue
            if not self._has_sufficient_overlap(claim_terms, overlap):
                if not (full_scope_claim and self._contains_evidence_refutation(haystack)):
                    continue
            matched_segment = True
            if self._disclaims_subject(segment) or self._disclaims_subject(haystack):
                continue
            if anchor_cores and not any(
                core in segment or core in anchor_context_norm for core in anchor_cores
            ):
                continue
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

    @staticmethod
    def _anchor_cores(anchors: list[str]) -> list[str]:
        cores = []
        for anchor in anchors:
            core = anchor[:4] if len(anchor) > 4 else anchor
            if len(core) >= 2:
                cores.append(core)
        return cores

    def _overlap_terms(self, claim_terms: list[str], haystack: str) -> list[str]:
        return [term for term in claim_terms if term in haystack]

    def _has_sufficient_overlap(self, claim_terms: list[str], overlap: list[str]) -> bool:
        if any(len(term) >= 3 or term in STRONG_OVERLAP_TERMS or self._is_strong_numeric_term(term) for term in overlap):
            return True
        return len(overlap) >= 2 or (len(claim_terms) <= 2 and bool(overlap))

    def _is_strong_numeric_term(self, term: str) -> bool:
        if not any(ch.isdigit() for ch in term):
            return False
        if re.fullmatch(r"\d+", term):
            return False
        return True

    def _is_context_only_segment(self, haystack: str) -> bool:
        return any(marker in haystack for marker in CONTEXT_ONLY_MARKERS) and not any(
            marker in haystack for marker in POSITIVE_ASSERTION_MARKERS
        )

    def _disclaims_subject(self, text: str) -> bool:
        lowered = text.lower()
        return any(marker in lowered for marker in SUBJECT_DISCLAIMER_MARKERS)

    def _has_negative_claim_refutation_overlap(self, overlap: list[str]) -> bool:
        return any(len(term) >= 3 or self._is_strong_numeric_term(term) for term in overlap)

    def _confidence_from_high_trust_hits(self, items: list[EvidenceItem]) -> str:
        if len(items) >= 2 or any(item.source_tier == DECISIVE_HIGH_CONFIDENCE_TIER for item in items):
            return "high"
        if items:
            return "medium"
        return "low"

    def _has_any_high_trust_hit(self, items: list[EvidenceItem]) -> bool:
        """Callers pass an already-tier-filtered list, so any hit here is a
        tier-S/A source. One such hit is sufficient to move a claim off the
        insufficient bucket — the finer decisiveness gradation (single vs.
        multiple, A vs. S) is done in ``_confidence_from_high_trust_hits``."""
        return bool(items)

    def _extract_quantity_tokens(self, text: str) -> list[str]:
        return [match.group(0) for match in QUANTITY_TOKEN_PATTERN.finditer(text)]

    def _detect_quantitative_conflict(
        self,
        *,
        claim_text: str,
        evidence_pool: list[EvidenceItem],
    ) -> tuple[str, str, str, list[EvidenceItem]] | None:
        claim_measurements = _measurements(claim_text)
        if not claim_measurements:
            return None

        matching: list[EvidenceItem] = []
        differing: list[EvidenceItem] = []
        corrections: list[EvidenceItem] = []
        corrected_matches: list[EvidenceItem] = []
        aligned: set[int] = set()
        uncertain = False
        for item in evidence_pool:
            title_measurements = _measurements(item.title)
            contexts = {measurement.context for measurement in title_measurements}
            default_context = next(iter(contexts)) if len(contexts) == 1 else ""
            if not default_context:
                title_subjects = extract_subject_anchors(item.title)
                if len(title_subjects) == 1:
                    default_context = title_subjects[0]
            measurements = title_measurements + _measurements(item.snippet, default_context=default_context)
            for index, expected in enumerate(claim_measurements):
                comparable = [measurement for measurement in measurements
                              if _same_measurement_relation(expected, measurement)]
                precise = [measurement for measurement in comparable if not measurement.bounded]
                uncertain |= bool(comparable) and not precise
                if not precise:
                    continue
                aligned.add(index)
                same = [measurement for measurement in precise if measurement.value == expected.value]
                different = [measurement for measurement in precise
                             if measurement.value != expected.value and not measurement.denied]
                if same and item not in matching:
                    matching.append(item)
                if different and item not in differing:
                    differing.append(item)
                if any(measurement.corrected for measurement in different) and item not in corrections:
                    corrections.append(item)
                if any(measurement.corrected and not measurement.denied for measurement in same) and item not in corrected_matches:
                    corrected_matches.append(item)

        if len(aligned) != len(claim_measurements) or (uncertain and not matching and not differing):
            return (
                "insufficient", "low",
                "数量证据的主体、事项、时间、统计范围或单位尚未完整对齐，不能仅凭词语重合支持或否定该说法。",
                evidence_pool[:2],
            )
        if not differing:
            high_trust_matches = [item for item in corrected_matches if item.source_tier in HIGH_TRUST_SOURCE_TIERS]
            if high_trust_matches and not self._contains_claim_negation(claim_text):
                return ("supported", self._confidence_from_high_trust_hits(high_trust_matches),
                        "高可信来源明确更正为与该说法一致的数量，旧值不作为反向证据。", high_trust_matches[:2])
            return None
        high_trust_corrections = [item for item in corrections if item.source_tier in HIGH_TRUST_SOURCE_TIERS]
        # A directly scoped correction may quote the original number as well.
        # Preserve that useful case instead of suppressing all multi-number text.
        if high_trust_corrections:
            selected = sorted(high_trust_corrections, key=lambda item: TIER_PRIORITY.get(item.source_tier, 99))[:2]
            return (
                "refuted",
                self._confidence_from_high_trust_hits(high_trust_corrections),
                "高可信来源针对同一事项明确给出了不同数量并纠正原说法，当前按不成立处理。",
                selected,
            )
        # For unresolved disagreement show both values when both are available;
        # sorting all hits by tier first can hide one side behind duplicate hits.
        selected = sorted(differing, key=lambda item: TIER_PRIORITY.get(item.source_tier, 99))[:1]
        opposite = next((item for item in matching if item not in selected), None)
        if opposite is not None:
            selected.append(opposite)
        else:
            selected.extend(item for item in differing if item not in selected and len(selected) < 2)
        return (
            "conflicting",
            "medium",
            "关联来源对同一事项、可比较单位的具体数量存在差异，当前应保持冲突态。",
            selected,
        )

    def _evaluate_superseding_evidence(
        self,
        *,
        supporting: list[EvidenceItem],
        refuting: list[EvidenceItem],
    ) -> tuple[str, str, str, list[EvidenceItem]] | None:
        if not supporting or not refuting:
            return None

        def latest(items: list[EvidenceItem]) -> datetime | None:
            dates = [_evidence_published_dt(item) for item in items]
            return max((value for value in dates if value is not None), default=None)

        candidates = (
            ("refuted", refuting, supporting),
            ("supported", supporting, refuting),
        )
        for verdict, current_side, previous_side in candidates:
            explicit = [
                item
                for item in current_side
                if self._has_supersession_signal(item)
            ]
            current_date = latest(explicit)
            previous_date = latest(previous_side)
            if not explicit or current_date is None or previous_date is None:
                continue
            if current_date <= previous_date:
                continue
            high_trust = [item for item in explicit if item.source_tier in HIGH_TRUST_SOURCE_TIERS]
            if not high_trust:
                continue
            return (
                verdict,
                self._confidence_from_high_trust_hits(high_trust),
                "较新的高可信来源明确更新或取代了旧状态，当前按最新有效信息判断。",
                explicit[:2],
            )
        return None

    def _has_supersession_signal(self, item: EvidenceItem) -> bool:
        text = self._normalize_claim(f"{item.title} {item.snippet}")
        return any(marker in text for marker in SUPERSESSION_MARKERS) or bool(
            SUPERSESSION_EFFECTIVE_DATE_PATTERN.search(text)
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

    def _is_time_sensitive_claim(self, claim_text: str, normalized_claim: str) -> bool:
        return any(
            marker in claim_text or marker in normalized_claim
            for marker in TIME_SENSITIVE_CLAIM_MARKERS
        )

    def _looks_like_source_gap_evidence(self, item: EvidenceItem) -> bool:
        haystack = self._normalize_claim(f"{item.title} {item.snippet} {item.relevance_reason}")
        return any(marker in haystack for marker in SOURCE_GAP_EVIDENCE_MARKERS)

    def _append_evidence_context(self, *, notes: str, selected: list[EvidenceItem]) -> str:
        if not selected:
            return notes
        ranked_tiers = sorted({item.source_tier for item in selected}, key=lambda tier: TIER_PRIORITY.get(tier, 99))
        source_names: list[str] = []
        for item in selected:
            if item.source_name not in source_names:
                source_names.append(item.source_name)
            if len(source_names) >= 2:
                break
        return (
            f"{notes} 复核依据：共引用 {len(selected)} 条关联证据，"
            f"最高来源等级 {ranked_tiers[0]}，代表来源包括 {'、'.join(source_names)}。"
        )
