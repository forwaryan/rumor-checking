from __future__ import annotations

import logging
import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Optional

from backend.app.core.config import Settings, get_settings
from backend.app.core.exceptions import AppError
from backend.app.models.schemas import NormalizedEvent
from backend.app.services.contract_utils import ensure_datetime_string
from backend.app.services.mock_retriever import MockRetriever
from backend.app.services.question_intent import detect_trend_topic, is_broad_trend_question
from backend.app.services.question_text import clean_question_term, strip_question_tail
from backend.app.services.retrieval_cache import RetrievalCache
from backend.app.services.retrieval_deduper import chronological_sort_key, merge_search_results
from backend.app.services.retrieval_models import (
    RetrievalBundle,
    RetrievalQuerySpec,
    SearchResult,
    build_independence_key,
    detect_signal_tags,
    infer_source_category,
    looks_like_repost,
)
from backend.app.services.playwright_search_provider import PlaywrightSearchProvider
from backend.app.services.progress import emit_log, emit_retrieval
from backend.app.services.retrieval_provider import GdeltNewsProvider, LlmWebSearchProvider, RetrievalProvider

logger = logging.getLogger(__name__)
UTC = timezone.utc

QUESTION_REWRITE_REPLACEMENTS = (
    (r"[\uFF1F?]", " "),
    (r"^(\u8bf7\u95ee|\u60f3\u95ee\u4e00\u4e0b|\u60f3\u95ee|\u6709\u4eba\u77e5\u9053|\u7f51\u4f20|\u542c\u8bf4)", ""),
    (r"(\u662f\u771f\u7684\u5417|\u771f\u7684\u5047\u7684|\u5c5e\u5b9e\u5417|\u662f\u771f\u7684\u5417\u554a)$", ""),
    (r"\u662f\u4e0d\u662f", ""),
    (r"\u6709\u6ca1\u6709", ""),
    (r"\u6700\u8fd1", ""),
    (r"\u6709\u4e00\u4e2a", ""),
    (r"\u6b7b\u6389\u4e86", "\u6b7b\u4ea1"),
    (r"\u6b7b\u6389", "\u6b7b\u4ea1"),
    (r"\u6b7b\u4e86", "\u6b7b\u4ea1"),
)
QUESTION_STOPWORDS = {
    "\u662f\u4e0d\u662f",
    "\u6709\u6ca1\u6709",
    "\u6700\u8fd1",
    "\u6d88\u606f",
    "\u4f20\u95fb",
    "\u4e8b\u4ef6",
    "\u65b0\u95fb",
    "\u4e8b\u60c5",
    "\u4e00\u4e2a",
    "\u6709\u4e00\u4e2a",
}
QUESTION_KEY_PHRASES = (
    "\u5973\u7f51\u7ea2",
    "\u7537\u7f51\u7ea2",
    "\u7f51\u7ea2",
    "\u4e3b\u64ad",
    "\u660e\u661f",
    "\u6f14\u5458",
    "\u8111\u51fa\u8840",
    "\u8111\u6ea2\u8840",
    "\u6b7b\u4ea1",
    "\u53bb\u4e16",
    "\u75c5\u5371",
    "\u4f4f\u9662",
    "\u62a2\u6551",
    "\u8f9f\u8c23",
    "\u901a\u62a5",
    "\u88c1\u5458",
)
OFFICIAL_QUERY_TERMS = ("\u5b98\u65b9", "\u56de\u5e94", "\u901a\u62a5", "\u8bf4\u660e", "\u8f9f\u8c23")
PROPAGATION_QUERY_TERMS = ("\u4f20\u95fb", "\u7f51\u4f20", "\u70ed\u8bae", "\u53d1\u9175", "\u8f6c\u53d1")
CLAUSE_SPLIT_RE = re.compile(r"[\u3002\uff01\uff1f!?;；，,\n]+")


class RetrievalService:
    def __init__(
        self,
        settings: Optional[Settings] = None,
        provider: Optional[RetrievalProvider] = None,
        cache: Optional[RetrievalCache] = None,
        agent_reasoner: Optional[Any] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.provider = provider or self._build_provider()
        self.mock_retriever = MockRetriever(settings=self.settings)
        self.agent_reasoner = agent_reasoner
        self.cache = cache or RetrievalCache(
            cache_root=self.settings.retrieval_cache_dir,
            ttl_seconds=self.settings.retrieval_cache_ttl_seconds,
        )

    def _build_provider(self) -> Optional[RetrievalProvider]:
        if self.settings.retrieval_provider == "gdelt":
            return GdeltNewsProvider(settings=self.settings)
        if self.settings.retrieval_provider == "playwright":
            return PlaywrightSearchProvider(settings=self.settings)
        if self.settings.uses_agent_retrieval:
            return LlmWebSearchProvider(settings=self.settings)
        return None

    def retrieve_for_event(
        self,
        event: NormalizedEvent,
        *,
        request_context: Optional[dict[str, Any]] = None,
    ) -> RetrievalBundle:
        request_context = request_context or {}
        stage_key = "retrieval_follow_up" if request_context.get("force_retrieval_query") else "retrieval_initial"
        query_plan = self._build_query_plan(event, request_context=request_context)
        if not query_plan:
            emit_log(
                stage_key=stage_key,
                level="warning",
                title="检索 query plan 为空",
                summary="当前输入没有生成有效检索 query。",
                details=[f"event_title={event.title or 'unknown'}"],
            )
            raise AppError(
                status_code=422,
                code="empty_retrieval_query",
                message="The request could not be rewritten into a valid retrieval query.",
            )

        emit_log(
            stage_key=stage_key,
            title="已生成 query plan",
            summary=f"本轮检索会执行 {len(query_plan)} 条 query。",
            details=[f"{spec.label}={spec.query}" for spec in query_plan],
        )

        primary_query = query_plan[0].query
        cache_enabled = self.settings.retrieval_cache_enabled
        provider_name = self.settings.retrieval_provider
        if self.provider is not None and provider_name in {"mock", "off"} and self.provider.name not in {"mock", "off"}:
            provider_name = self.provider.name
        bypass_cache = self._as_bool(
            request_context.get("skip_retrieval_cache") or request_context.get("bypass_retrieval_cache")
        )
        cache_only = self._as_bool(request_context.get("retrieval_cache_only"))
        allow_stale = self._as_bool(request_context.get("allow_stale_retrieval_cache"))

        if provider_name == "off":
            return self._empty_bundle(primary_query, provider_name="off", query_plan=query_plan)

        if provider_name == "mock":
            return self._mock_bundle(event, query_plan=query_plan)

        query_bundles: list[RetrievalBundle] = []
        query_failures: list[str] = []
        cache_statuses: list[str] = []
        provider_failure_details: list[str] = []
        provider_unavailable = self.provider is None or not self.provider.enabled

        for spec in query_plan:
            if cache_enabled and not bypass_cache:
                cached = self.cache.read(
                    query_text=spec.query,
                    provider_name=provider_name,
                    allow_stale=cache_only or allow_stale,
                    scope_key=spec.normalized_scope(),
                )
                if cached is not None:
                    cached_bundle = cached.with_runtime_metadata(
                        query_groups=(spec,),
                        query_failures=(),
                    )
                    query_bundles.append(cached_bundle)
                    cache_statuses.append(cached.cache_status)
                    emit_retrieval(
                        stage_key=stage_key,
                        query_label=spec.label,
                        query=spec.query,
                        provider_name=provider_name,
                        summary=f"{spec.label} 命中缓存，直接复用检索结果。",
                        details=_retrieval_preview_details(cached_bundle),
                    )
                    continue

            if cache_only:
                query_failures.append(f"{spec.label}:cache_miss")
                cache_statuses.append("miss")
                emit_log(
                    stage_key=stage_key,
                    level="warning",
                    title="缓存模式未命中",
                    summary=f"{spec.label} 只读缓存但没有命中。",
                    details=[f"query={spec.query}"],
                )
                continue

            if provider_unavailable:
                logger.warning("retrieval_provider_unavailable provider=%s query_label=%s", provider_name, spec.label)
                query_failures.append(f"{spec.label}:provider_unavailable")
                emit_log(
                    stage_key=stage_key,
                    level="warning",
                    title="检索 provider 不可用",
                    summary=f"{provider_name} 当前不可用，无法执行 {spec.label}。",
                    details=[f"query={spec.query}"],
                )
                continue

            try:
                emit_log(
                    stage_key=stage_key,
                    title="执行检索 query",
                    summary=f"正在调用 {provider_name} 执行 {spec.label}。",
                    details=[
                        f"query={spec.query}",
                        f"rationale={spec.rationale}",
                    ],
                )
                raw_results = self.provider.search(spec.query)
            except AppError:
                raise
            except Exception as exc:
                failure_detail = self._describe_exception(exc)
                logger.warning(
                    "retrieval_failed provider=%s query_label=%s error_type=%s",
                    self.provider.name,
                    spec.label,
                    exc.__class__.__name__,
                )
                if cache_enabled and (allow_stale or self.settings.retrieval_cache_allow_stale_on_error):
                    stale_cached = self.cache.read(
                        query_text=spec.query,
                        provider_name=provider_name,
                        allow_stale=True,
                        scope_key=spec.normalized_scope(),
                    )
                    if stale_cached is not None:
                        query_bundles.append(
                            stale_cached.with_runtime_metadata(
                                fallback_used=True,
                                fallback_reason="real_retrieval_failed",
                                failure_detail=failure_detail,
                                query_groups=(spec,),
                                query_failures=(),
                            )
                    )
                        cache_statuses.append("stale_hit")
                        emit_retrieval(
                            stage_key=stage_key,
                            query_label=spec.label,
                            query=spec.query,
                            provider_name=provider_name,
                            summary=f"{spec.label} 实时检索失败，已退回陈旧缓存。",
                            details=_retrieval_preview_details(stale_cached),
                        )
                        continue
                query_failures.append(f"{spec.label}:{failure_detail}")
                provider_failure_details.append(f"{spec.label}:{failure_detail}")
                emit_log(
                    stage_key=stage_key,
                    level="warning",
                    title="实时检索失败",
                    summary=f"{spec.label} 调用 {provider_name} 失败。",
                    details=[
                        f"query={spec.query}",
                        f"failure={failure_detail}",
                    ],
                )
                continue

            bundle = self._build_single_query_bundle(
                spec,
                raw_results,
                provider_name=provider_name,
                cache_status="bypassed" if bypass_cache else ("write_only" if cache_enabled else "not_used"),
            )
            if cache_enabled and not bypass_cache:
                self.cache.write(
                    query_text=spec.query,
                    provider_name=provider_name,
                    bundle=bundle,
                    scope_key=spec.normalized_scope(),
                )
            query_bundles.append(bundle)
            cache_statuses.append(bundle.cache_status)
            emit_retrieval(
                stage_key=stage_key,
                query_label=spec.label,
                query=spec.query,
                provider_name=provider_name,
                summary=f"{spec.label} 已返回 {len(bundle.canonical_results)} 条去重结果。",
                details=_retrieval_preview_details(bundle),
            )

        if not query_bundles:
            if cache_only:
                emit_log(
                    stage_key=stage_key,
                    level="warning",
                    title="检索返回空结果",
                    summary="本轮检索只读缓存且全部 miss。",
                    details=[f"provider={provider_name}"],
                )
                return self._empty_bundle(
                    primary_query,
                    provider_name=provider_name,
                    cache_status="miss",
                    fallback_reason="retrieval_cache_only_miss",
                    failure_detail=self._summarize_query_failures(query_failures),
                    query_plan=query_plan,
                    query_failures=tuple(query_failures),
                )
            if provider_unavailable:
                emit_log(
                    stage_key=stage_key,
                    level="warning",
                    title="检索 provider 不可用",
                    summary="本轮检索没有实际调用到在线 provider。",
                    details=[f"provider={provider_name}"],
                )
                return self._provider_unavailable_bundle(
                    event,
                    query=primary_query,
                    provider_name=provider_name,
                    query_plan=query_plan,
                    query_failures=tuple(query_failures),
                )
            if provider_failure_details:
                emit_log(
                    stage_key=stage_key,
                    level="warning",
                    title="检索阶段全部失败",
                    summary="所有 query 都未拿到在线结果。",
                    details=provider_failure_details[:4],
                )
                return self._provider_failure_bundle(
                    event,
                    query=primary_query,
                    provider_name=provider_name,
                    failure_detail=self._summarize_query_failures(provider_failure_details),
                    query_plan=query_plan,
                    query_failures=tuple(query_failures),
                )
            emit_log(
                stage_key=stage_key,
                level="warning",
                title="检索阶段无结果",
                summary="本轮检索执行完成，但没有保留下任何结果。",
                details=query_failures[:4],
            )
            return self._empty_bundle(
                primary_query,
                provider_name=provider_name,
                cache_status="bypassed" if bypass_cache else "not_used",
                failure_detail=self._summarize_query_failures(query_failures),
                query_plan=query_plan,
                query_failures=tuple(query_failures),
            )

        combined_bundle = self._combine_query_bundles(
            primary_query=primary_query,
            query_plan=query_plan,
            query_bundles=query_bundles,
            provider_name=provider_name,
            cache_statuses=cache_statuses,
            query_failures=query_failures,
        )
        emit_log(
            stage_key=stage_key,
            title="检索阶段汇总完成",
            summary=f"已汇总 {len(combined_bundle.canonical_results)} 条 canonical retrieval hits。",
            details=_retrieval_preview_details(combined_bundle),
        )
        return combined_bundle

    def _build_single_query_bundle(
        self,
        spec: RetrievalQuerySpec,
        raw_results: list[SearchResult],
        *,
        provider_name: str,
        cache_status: str,
    ) -> RetrievalBundle:
        retrieved_at = ensure_datetime_string(datetime.now(UTC).isoformat())
        runtime_results = [
            self._enrich_result(item, spec=spec, provider_name=provider_name, retrieved_at=retrieved_at)
            for item in raw_results
        ]
        canonical_results = merge_search_results(runtime_results)
        return RetrievalBundle(
            query=spec.query,
            matched_case_id="real_search",
            mode_hint=self._mode_hint_for_results(canonical_results),
            raw_results=tuple(sorted(runtime_results, key=chronological_sort_key)),
            canonical_results=tuple(sorted(canonical_results, key=chronological_sort_key)),
            provider_name=provider_name,
            cache_key=self.cache.build_cache_key(
                query_text=spec.query,
                provider_name=provider_name,
                scope_key=spec.normalized_scope(),
            ),
            cache_status=cache_status,
            retrieved_at=retrieved_at,
            query_groups=(spec,),
        )

    def _combine_query_bundles(
        self,
        *,
        primary_query: str,
        query_plan: list[RetrievalQuerySpec],
        query_bundles: list[RetrievalBundle],
        provider_name: str,
        cache_statuses: list[str],
        query_failures: list[str],
    ) -> RetrievalBundle:
        raw_results: list[SearchResult] = []
        expected_origin_result_id = None
        expected_turning_point_result_id = None
        matched_case_id = None
        fallback_used = False
        fallback_reason = None
        retrieved_at = None
        child_failures: list[str] = []

        for bundle in query_bundles:
            raw_results.extend(bundle.raw_results)
            if matched_case_id is None and bundle.matched_case_id:
                matched_case_id = bundle.matched_case_id
            if expected_origin_result_id is None and bundle.expected_origin_result_id:
                expected_origin_result_id = bundle.expected_origin_result_id
            if expected_turning_point_result_id is None and bundle.expected_turning_point_result_id:
                expected_turning_point_result_id = bundle.expected_turning_point_result_id
            if bundle.fallback_used:
                fallback_used = True
                fallback_reason = fallback_reason or bundle.fallback_reason
            if bundle.retrieved_at and (retrieved_at is None or bundle.retrieved_at > retrieved_at):
                retrieved_at = bundle.retrieved_at
            child_failures.extend(bundle.query_failures)

        relevant_raw_results = self._filter_relevant_results(raw_results)
        canonical_results = merge_search_results(relevant_raw_results)
        all_failures = list(dict.fromkeys([*query_failures, *child_failures]))
        combined = RetrievalBundle(
            query=primary_query,
            matched_case_id=matched_case_id or "real_search",
            mode_hint=self._mode_hint_for_results(canonical_results),
            raw_results=tuple(sorted(raw_results, key=chronological_sort_key)),
            canonical_results=tuple(sorted(canonical_results, key=chronological_sort_key)),
            expected_origin_result_id=expected_origin_result_id,
            expected_turning_point_result_id=expected_turning_point_result_id,
            provider_name=provider_name,
            cache_key=self._combine_cache_keys(query_bundles),
            cache_status=self._summarize_cache_status(cache_statuses),
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            retrieved_at=retrieved_at or ensure_datetime_string(datetime.now(UTC).isoformat()),
            failure_detail=self._summarize_query_failures(all_failures),
            query_groups=tuple(query_plan),
            query_failures=tuple(all_failures),
        )
        return combined

    def _filter_relevant_results(self, results: list[SearchResult]) -> list[SearchResult]:
        if len(results) <= 1:
            return results
        filtered = [item for item in results if self._result_matches_query(item)]
        return filtered or results

    def _result_matches_query(self, result: SearchResult) -> bool:
        query_terms = self._relevance_terms(result.query)
        if not query_terms:
            return True
        raw_text = " ".join([result.title, result.snippet, result.source_name])
        text = self._normalize_query(raw_text)
        if any(marker in text for marker in ("未提及", "未涉及", "不涉及", "无关", "another", "unrelated")):
            return False
        matched = [term for term in query_terms if term in text]
        if matched and result.has_response_signal:
            return True
        if len(query_terms) <= 2:
            return bool(matched)
        return len(matched) >= 2

    def _relevance_terms(self, text: str) -> list[str]:
        stopwords = {
            "官方",
            "回应",
            "通报",
            "说明",
            "辟谣",
            "用户提供文本",
            "传闻",
            "网传",
            "热议",
            "发酵",
            "转发",
            "相关",
            "信息",
        }
        terms: list[str] = []
        for term in re.findall(r"[A-Za-z0-9%]{2,}|[\u4e00-\u9fff]{2,12}", text):
            cleaned = term.strip()
            if not cleaned or cleaned in stopwords or cleaned in terms:
                continue
            if re.fullmatch(r"[\u4e00-\u9fff]{5,12}", cleaned):
                for marker in ("拼多多", "雄安", "新区", "招聘", "入住", "研发", "技术", "裁员", "脑出血", "死亡"):
                    if marker in cleaned and marker not in terms:
                        terms.append(marker)
                if "死了" in cleaned and "死亡" not in terms:
                    terms.append("死亡")
                if "女网红" in cleaned and "女网红" not in terms:
                    terms.append("女网红")
                if cleaned not in terms:
                    terms.append(cleaned)
            else:
                terms.append(cleaned)
        return terms[:5]

    def _llm_query_terms(self, event: NormalizedEvent):
        """Entity-focused search terms from the reasoner, or None to fall back.

        Only fires on the agent+LLM retrieval path; any failure degrades silently to the
        rule-based query builder so the off+mock path is unchanged.
        """
        reasoner = self.agent_reasoner
        if reasoner is None or not getattr(reasoner, "enabled", False):
            return None
        try:
            return reasoner.extract_query_terms(event=event)
        except Exception as exc:
            emit_log(
                stage_key="retrieval_initial",
                level="warning",
                title="query 抽取失败",
                summary="LLM query 抽取抛错，沿用规则构造的 query。",
                details=[f"error_type={exc.__class__.__name__}"],
            )
            return None

    def _build_query_plan(self, event: NormalizedEvent, *, request_context: dict[str, Any]) -> list[RetrievalQuerySpec]:
        forced_query = request_context.get("force_retrieval_query")
        if isinstance(forced_query, str) and forced_query.strip():
            base_query = forced_query.strip()
            return self._dedupe_query_plan(
                [
                    RetrievalQuerySpec(
                        label="follow_up_core",
                        query=base_query,
                        rationale="问题解析后围绕候选事件做 follow-up 检索。",
                        claim_hint=base_query,
                    ),
                    RetrievalQuerySpec(
                        label="follow_up_official",
                        query=self._extend_query(base_query, *OFFICIAL_QUERY_TERMS, event.source_name),
                        rationale="补抓候选事件的官方回应、通报与说明。",
                        claim_hint=base_query,
                    ),
                    RetrievalQuerySpec(
                        label="follow_up_propagation",
                        query=self._extend_query(base_query, *PROPAGATION_QUERY_TERMS),
                        rationale="补抓候选事件的传播扩散节点。",
                        claim_hint=base_query,
                    ),
                ]
            )

        primary_query = self._build_primary_query(event)
        if not primary_query:
            return []

        keyword_query = self._build_term_query(event.title, event.summary, " ".join(event.keywords[:5]), event.source_name)
        first_clause_query = self._build_term_query(*self._extract_claim_clauses(event.title, event.summary))

        # LLM-driven query construction: the raw sentence is a poor search query
        # ("京东开始造游轮了，而且..."), so when the reasoner is available, replace
        # the primary/keyword query with entity-focused terms it extracts. Falls
        # back to the rule-based queries above when disabled/unparseable.
        llm_terms = self._llm_query_terms(event)
        if llm_terms is not None:
            primary_query = llm_terms.primary_query
            keyword_query = llm_terms.primary_query

        official_query = self._extend_query(keyword_query or primary_query, *OFFICIAL_QUERY_TERMS, event.source_name)
        propagation_query = self._extend_query(keyword_query or primary_query, *PROPAGATION_QUERY_TERMS)

        if event.input_type == "question_only":
            if is_broad_trend_question(event.raw_input):
                return self._dedupe_query_plan(
                    [
                        RetrievalQuerySpec(
                            label="trend_topic",
                            query=primary_query,
                            rationale="范围型问句先收敛到主题，不强行拆成单事件传播链。",
                            claim_hint=primary_query,
                        )
                    ]
                )
            rewritten_query = self._rewrite_question_query(event.raw_input)
            official_query = self._extend_query(rewritten_query or primary_query, *OFFICIAL_QUERY_TERMS, event.source_name)
            propagation_query = self._extend_query(rewritten_query or primary_query, *PROPAGATION_QUERY_TERMS)
            primary_label = "question_raw" if self.settings.uses_agent_retrieval else "question_core"
            return self._dedupe_query_plan(
                [
                    RetrievalQuerySpec(
                        label=primary_label,
                        query=primary_query,
                        rationale="保留问句核心表达，先抓与原始问题最接近的公开结果。",
                        claim_hint=rewritten_query or primary_query,
                    ),
                    RetrievalQuerySpec(
                        label="question_claim",
                        query=rewritten_query,
                        rationale="收紧到 claim-first 的核心实体和动作，避免只命中泛化传闻。",
                        claim_hint=rewritten_query or primary_query,
                    ),
                    RetrievalQuerySpec(
                        label="question_official",
                        query=official_query,
                        rationale="补抓官方回应、医院/警方/机构说明等高可信来源。",
                        claim_hint=rewritten_query or primary_query,
                    ),
                    RetrievalQuerySpec(
                        label="question_propagation",
                        query=propagation_query,
                        rationale="补抓网传、发酵、转载等传播链节点。",
                        claim_hint=rewritten_query or primary_query,
                    ),
                ]
            )

        return self._dedupe_query_plan(
            [
                RetrievalQuerySpec(
                    label="event_core",
                    query=primary_query,
                    rationale="围绕事件标题、摘要与关键词建立主检索 query。",
                    claim_hint=event.summary or primary_query,
                ),
                RetrievalQuerySpec(
                    label="event_claim",
                    query=first_clause_query or keyword_query,
                    rationale="把事件摘要压到更接近单条 claim 的 query，补足细粒度证据。",
                    claim_hint=event.summary or primary_query,
                ),
                RetrievalQuerySpec(
                    label="event_official",
                    query=official_query,
                    rationale="优先抓官方源、主流媒体跟进与后续说明。",
                    claim_hint=event.summary or primary_query,
                ),
                RetrievalQuerySpec(
                    label="event_propagation",
                    query=propagation_query,
                    rationale="补抓传播扩散和转载放大节点，供时间线使用。",
                    claim_hint=event.summary or primary_query,
                ),
            ]
        )

    def _dedupe_query_plan(self, candidates: list[RetrievalQuerySpec]) -> list[RetrievalQuerySpec]:
        query_plan: list[RetrievalQuerySpec] = []
        seen_queries: set[str] = set()
        for candidate in candidates:
            normalized_query = self._normalize_query(candidate.query)
            if not normalized_query or normalized_query in seen_queries:
                continue
            seen_queries.add(normalized_query)
            query_plan.append(
                RetrievalQuerySpec(
                    label=candidate.label,
                    query=normalized_query,
                    rationale=candidate.rationale,
                    claim_hint=candidate.claim_hint,
                    cache_scope=candidate.cache_scope or f"{candidate.label}:{candidate.claim_hint or normalized_query}",
                )
            )
            if len(query_plan) >= 4:
                break
        if len(query_plan) == 1:
            only = query_plan[0]
            official_query = self._extend_query(only.query, *OFFICIAL_QUERY_TERMS)
            if self._normalize_query(official_query) and self._normalize_query(official_query) != self._normalize_query(only.query):
                query_plan.append(
                    RetrievalQuerySpec(
                        label=f"{only.label}_official",
                        query=self._normalize_query(official_query),
                        rationale="补一条官方回应 query，避免单 query 漏掉关键说明。",
                        claim_hint=only.claim_hint or only.query,
                        cache_scope=f"{only.label}_official:{only.claim_hint or only.query}",
                    )
                )
        return query_plan[:5]

    def _build_primary_query(self, event: NormalizedEvent) -> str:
        if event.input_type == "question_only":
            if self.settings.uses_agent_retrieval:
                return event.raw_input.strip().rstrip("\uFF1F?")
            return self._rewrite_question_query(event.raw_input)

        ordered_parts: list[str] = []
        seen = set()
        for part in [event.title, event.summary, *event.keywords[:4]]:
            if not part:
                continue
            compact = re.sub(r"\s+", " ", part).strip()
            if compact and compact not in seen:
                seen.add(compact)
                ordered_parts.append(compact)
        return " ".join(ordered_parts) or event.raw_input.strip()

    def _build_term_query(self, *texts: Optional[str], max_terms: int = 8) -> str:
        terms: list[str] = []
        seen: set[str] = set()
        for text in texts:
            if not text:
                continue
            for term in re.findall(r"[A-Za-z0-9%]{2,}|[\u4e00-\u9fff]{2,12}", text):
                cleaned = term.strip()
                if not cleaned or cleaned in seen:
                    continue
                seen.add(cleaned)
                terms.append(cleaned)
                if len(terms) >= max_terms:
                    return " ".join(terms)
        return " ".join(terms)

    def _extract_claim_clauses(self, *texts: Optional[str]) -> list[str]:
        clauses: list[str] = []
        seen: set[str] = set()
        for text in texts:
            if not text:
                continue
            for clause in CLAUSE_SPLIT_RE.split(text):
                compact = self._normalize_query(clause)
                if len(compact) < 4 or compact in seen:
                    continue
                seen.add(compact)
                clauses.append(compact)
                if len(clauses) >= 3:
                    return clauses
        return clauses

    def _extend_query(self, base_query: str, *extra_terms: Optional[str]) -> str:
        return self._build_term_query(base_query, " ".join(term for term in extra_terms if term))

    def _enrich_result(
        self,
        result: SearchResult,
        *,
        spec: RetrievalQuerySpec,
        provider_name: str,
        retrieved_at: str,
    ) -> SearchResult:
        relation_type = result.relation_type
        if relation_type is None and (result.duplicate_of or looks_like_repost(result.title, result.source_name)):
            relation_type = "repost"
        return (
            replace(result, query=spec.query)
            .with_runtime_metadata(provider_name=provider_name, retrieved_at=retrieved_at)
            .with_enrichment_metadata(
                source_category=infer_source_category(result.url, result.source_name),
                independence_key=build_independence_key(result.url, result.source_name),
                relation_type=relation_type,
                signal_tags=detect_signal_tags(result.title, result.snippet, result.source_name),
                query_label=spec.label,
            )
        )

    def _combine_cache_keys(self, bundles: list[RetrievalBundle]) -> Optional[str]:
        keys = [bundle.cache_key for bundle in bundles if bundle.cache_key]
        if not keys:
            return None
        if len(keys) == 1:
            return keys[0]
        return f"multi:{'+'.join(keys[:3])}"

    def _summarize_cache_status(self, statuses: list[str]) -> str:
        normalized = [status for status in statuses if status]
        if not normalized:
            return "not_used"
        unique = list(dict.fromkeys(normalized))
        if len(unique) == 1:
            return unique[0]
        if all(status in {"hit", "stale_hit"} for status in unique):
            return "partial_hit"
        return "mixed"

    def _mode_hint_for_results(self, canonical_results: tuple[SearchResult, ...]) -> str:
        high_trust_sources = {
            item.effective_independence_key for item in canonical_results if item.is_high_trust and item.effective_independence_key
        }
        if len(high_trust_sources) >= 2:
            return "complete_or_partial"
        if canonical_results:
            return "partial"
        return "safe"

    def _empty_bundle(
        self,
        query: str,
        *,
        provider_name: str,
        cache_status: str = "not_used",
        fallback_used: bool = False,
        fallback_reason: str | None = None,
        failure_detail: str | None = None,
        query_plan: Optional[list[RetrievalQuerySpec]] = None,
        query_failures: tuple[str, ...] = (),
    ) -> RetrievalBundle:
        return RetrievalBundle(
            query=query,
            matched_case_id="real_search",
            provider_name=provider_name,
            cache_status=cache_status,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            retrieved_at=ensure_datetime_string(datetime.now(UTC).isoformat()),
            failure_detail=failure_detail,
            query_groups=tuple(query_plan or ()),
            query_failures=query_failures,
        )

    def _mock_bundle(
        self,
        event: NormalizedEvent,
        *,
        query_plan: list[RetrievalQuerySpec],
        fallback_used: bool = False,
        fallback_reason: str | None = None,
        failure_detail: str | None = None,
        query_failures: tuple[str, ...] = (),
    ) -> RetrievalBundle:
        bundle = self.mock_retriever.retrieve_for_event(event)
        return bundle.with_runtime_metadata(
            provider_name="mock",
            cache_status="not_used",
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            failure_detail=failure_detail,
            retrieved_at=ensure_datetime_string(datetime.now(UTC).isoformat()),
            query_groups=tuple(query_plan),
            query_failures=query_failures,
        )

    def _provider_unavailable_bundle(
        self,
        event: NormalizedEvent,
        *,
        query: str,
        provider_name: str,
        query_plan: list[RetrievalQuerySpec],
        query_failures: tuple[str, ...],
    ) -> RetrievalBundle:
        if self.settings.retrieval_fallback_to_mock:
            return self._mock_bundle(
                event,
                query_plan=query_plan,
                fallback_used=True,
                fallback_reason="retrieval_provider_unavailable",
                query_failures=query_failures,
            )
        return self._empty_bundle(
            query,
            provider_name=provider_name,
            fallback_used=True,
            fallback_reason="retrieval_provider_unavailable",
            query_plan=query_plan,
            query_failures=query_failures,
        )

    def _provider_failure_bundle(
        self,
        event: NormalizedEvent,
        *,
        query: str,
        provider_name: str,
        failure_detail: str,
        query_plan: list[RetrievalQuerySpec],
        query_failures: tuple[str, ...],
    ) -> RetrievalBundle:
        if self.settings.retrieval_fallback_to_mock:
            return self._mock_bundle(
                event,
                query_plan=query_plan,
                fallback_used=True,
                fallback_reason="real_retrieval_failed",
                failure_detail=failure_detail,
                query_failures=query_failures,
            )
        return self._empty_bundle(
            query,
            provider_name=provider_name,
            fallback_used=True,
            fallback_reason="real_retrieval_failed",
            failure_detail=failure_detail,
            query_plan=query_plan,
            query_failures=query_failures,
        )

    def _rewrite_question_query(self, raw_input: str) -> str:
        if is_broad_trend_question(raw_input):
            topic = detect_trend_topic(raw_input)
            if topic:
                return topic

        query = raw_input.strip()
        for pattern, replacement in QUESTION_REWRITE_REPLACEMENTS:
            query = re.sub(pattern, replacement, query)
        query = strip_question_tail(query)

        terms = []
        seen = set()

        def push(term: str) -> None:
            cleaned = clean_question_term(term.strip())
            if not cleaned or cleaned in QUESTION_STOPWORDS or cleaned in seen:
                return
            seen.add(cleaned)
            terms.append(cleaned)

        for phrase in QUESTION_KEY_PHRASES:
            if phrase in query:
                push(phrase)

        for term in re.findall(r"\d+(?:\.\d+)?%?|[A-Za-z0-9]{2,}", query):
            push(term)

        for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", query):
            if len(chunk) <= 4:
                push(chunk)
            else:
                for window in (4, 3, 2):
                    if len(chunk) < window:
                        continue
                    for index in range(0, len(chunk) - window + 1):
                        push(chunk[index : index + window])
                        if len(terms) >= 8:
                            return " ".join(terms[:8])
            if len(terms) >= 8:
                break

        return " ".join(terms[:8]) or raw_input.strip().rstrip("\uFF1F?")

    def _normalize_query(self, query: str) -> str:
        return re.sub(r"\s+", " ", query).strip()

    def _summarize_query_failures(self, failures: list[str]) -> Optional[str]:
        normalized = [failure for failure in failures if failure]
        if not normalized:
            return None
        return "; ".join(list(dict.fromkeys(normalized))[:4])

    def _describe_exception(self, exc: Exception) -> str:
        response = getattr(exc, "response", None)
        if response is not None:
            status_code = getattr(response, "status_code", None)
            reason_phrase = getattr(response, "reason_phrase", None) or ""
            if status_code is not None:
                detail = f"HTTP {status_code} {reason_phrase}".strip()
                return detail
        return exc.__class__.__name__

    def _as_bool(self, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return False


def _retrieval_preview_details(bundle: RetrievalBundle) -> list[str]:
    details = [
        f"cache_status={bundle.cache_status}",
        f"canonical_results={len(bundle.canonical_results)}",
        f"raw_results={len(bundle.raw_results)}",
        f"high_trust_sources={bundle.high_trust_result_count}",
        f"independent_sources={bundle.independent_source_count}",
    ]
    for result in bundle.canonical_results[:3]:
        details.append(f"hit={result.title} | {result.source_name} | {result.published_at}")
    if bundle.failure_detail:
        details.append(f"failure_detail={bundle.failure_detail}")
    return details
