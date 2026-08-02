from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from backend.app.core.config import Settings, get_settings
from backend.app.core.exceptions import AppError
from backend.app.models.schemas import NormalizedEvent
from backend.app.services.contract_utils import INPUT_PLACEHOLDER_SOURCE_NAMES, ensure_datetime_string
from backend.app.services.mock_retriever import MockRetriever
from backend.app.services.piyao_provider import PiyaoSearchProvider
from backend.app.services.playwright_search_provider import PlaywrightSearchProvider
from backend.app.services.progress import (
    emit_log,
    emit_retrieval,
    get_progress_callback,
    reset_progress_callback,
    reset_retrieval_stage_key,
    set_progress_callback,
    set_retrieval_stage_key,
)
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
from backend.app.services.retrieval_provider import GdeltNewsProvider, LlmWebSearchProvider, RetrievalProvider
from backend.app.services.sogou_weixin_provider import SogouWeixinSearchProvider
from backend.app.services.toutiao_search_provider import ToutiaoSearchProvider
from backend.app.services.xhs_search_provider import XhsSearchProvider

logger = logging.getLogger(__name__)
UTC = UTC

# Site: whitelist for the targeted official-source boost. Grouped by rough
# domain so a rumor about academia doesn't waste a query slot on 疾控中心, etc.
# The provider still infers S/A/B tier per hit — this only steers where to look.
OFFICIAL_BOOST_ALWAYS = (
    "gov.cn",
    "xinhuanet.com",
    "people.com.cn",
    "cctv.com",
    "chinanews.com.cn",
    "piyao.org.cn",
    "news.cn",
)
OFFICIAL_BOOST_ACADEMIC = (
    "nature.com",
    "sciencemag.org",
    "cas.cn",
    "cae.cn",
    "nsfc.gov.cn",
    "moe.gov.cn",
    "retractionwatch.com",
)
OFFICIAL_BOOST_HEALTH = ("nhc.gov.cn", "chinacdc.cn", "who.int")
OFFICIAL_BOOST_QUAKE = ("cea.gov.cn", "cenc.ac.cn")
OFFICIAL_BOOST_FINANCE = ("stats.gov.cn", "pbc.gov.cn", "csrc.gov.cn")

# Query keyword → extra whitelist. Cheap heuristic; leaves the door open for
# richer intent classification later.
OFFICIAL_BOOST_TOPICAL_HINTS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("院士", "Nature", "论文", "撤稿", "杰青", "学术"), OFFICIAL_BOOST_ACADEMIC),
    (("疫苗", "疫情", "确诊", "病例", "卫健"), OFFICIAL_BOOST_HEALTH),
    (("地震", "余震", "震级"), OFFICIAL_BOOST_QUAKE),
    (("GDP", "统计局", "利率", "央行", "证监会"), OFFICIAL_BOOST_FINANCE),
)

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
        settings: Settings | None = None,
        provider: RetrievalProvider | None = None,
        cache: RetrievalCache | None = None,
        agent_reasoner: Any | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.provider = provider or self._build_provider()
        self.mock_retriever = MockRetriever(settings=self.settings)
        self.agent_reasoner = agent_reasoner
        self.xhs_provider = XhsSearchProvider(settings=self.settings)
        self.toutiao_provider = ToutiaoSearchProvider(settings=self.settings)
        self.sogou_weixin_provider = SogouWeixinSearchProvider(settings=self.settings)
        self.piyao_provider = PiyaoSearchProvider(settings=self.settings)
        self.cache = cache or RetrievalCache(
            cache_root=self.settings.retrieval_cache_dir,
            ttl_seconds=self.settings.retrieval_cache_ttl_seconds,
        )

    def _build_provider(self) -> RetrievalProvider | None:
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
        request_context: dict[str, Any] | None = None,
    ) -> RetrievalBundle:
        request_context = request_context or {}
        # The caller (agent tool) owns the pipeline step this retrieval belongs to
        # and passes it via retrieval_stage_key; only fall back to the force-query
        # heuristic when it is absent. Publish it so the provider layer tags its
        # own HTTP/LLM sub-events with the same stage instead of a hardcoded one.
        stage_key = request_context.get("retrieval_stage_key") or (
            "retrieval_follow_up" if request_context.get("force_retrieval_query") else "retrieval_initial"
        )
        # Caller may pass search_sources to limit which providers run.
        search_sources = request_context.get("search_sources")
        stage_token = set_retrieval_stage_key(stage_key)
        try:
            if self._source_enabled("baidu", search_sources):
                bundle = self._retrieve_for_event(event, request_context=request_context, stage_key=stage_key)
            else:
                query_plan = self._build_query_plan(event, request_context=request_context)
                primary_query = query_plan[0].query if query_plan else (event.title or "")
                bundle = self._empty_bundle(primary_query, provider_name="skipped", query_plan=query_plan or [])
            # Supplementary sources run after the primary retrieval (including
            # cache path) so they supplement regardless of cache state.
            if self._source_enabled("xiaohongshu", search_sources):
                bundle = self._append_xhs_results(bundle, bundle.query, stage_key=stage_key)
            if self._source_enabled("toutiao", search_sources):
                bundle = self._append_toutiao_results(bundle, bundle.query, stage_key=stage_key)
            if self._source_enabled("sogou_weixin", search_sources):
                bundle = self._append_sogou_weixin_results(bundle, bundle.query, stage_key=stage_key)
            if self._source_enabled("piyao", search_sources):
                bundle = self._append_piyao_results(bundle, bundle.query, stage_key=stage_key)
            # Targeted official-source boost runs last so it can inspect
            # everything the other providers already collected before deciding
            # whether to spend a query slot. It reuses the primary provider so
            # `retrieval_cache_only` must also gate it — an offline replay run
            # must NOT punch through to a live search.
            if (
                self._source_enabled("official_boost", search_sources)
                and not request_context.get("disable_official_boost")
                and not self._as_bool(request_context.get("retrieval_cache_only"))
            ):
                bundle = self._append_official_source_results(bundle, bundle.query, stage_key=stage_key)
        finally:
            reset_retrieval_stage_key(stage_token)
        return bundle

    @staticmethod
    def _source_enabled(source_name: str, search_sources: list[str] | None) -> bool:
        """Check if a source should run. If search_sources is None (no filter),
        all sources run. If it's a list, only listed sources run."""
        if search_sources is None:
            return True
        return source_name in search_sources

    def _retrieve_for_event(
        self,
        event: NormalizedEvent,
        *,
        request_context: dict[str, Any],
        stage_key: str,
    ) -> RetrievalBundle:
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

        query_bundles_by_index: dict[int, RetrievalBundle] = {}
        cache_status_by_index: dict[int, str] = {}
        query_failures: list[str] = []
        provider_failure_details: list[str] = []
        provider_unavailable = self.provider is None or not self.provider.enabled

        # Phase 1 (sequential): resolve cache and fast-fail paths, collecting the
        # specs that still need a live network fetch.
        fetch_indices: list[int] = []
        for index, spec in enumerate(query_plan):
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
                    query_bundles_by_index[index] = cached_bundle
                    cache_status_by_index[index] = cached.cache_status
                    emit_retrieval(
                        stage_key=stage_key,
                        query_label=spec.label,
                        query=spec.query,
                        provider_name=provider_name,
                        summary=f"{spec.label} 命中缓存，直接复用检索结果。",
                        details=_retrieval_preview_details(cached_bundle),
                        results=_retrieval_result_items(cached_bundle),
                    )
                    continue

            if cache_only:
                query_failures.append(f"{spec.label}:cache_miss")
                cache_status_by_index[index] = "miss"
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

            fetch_indices.append(index)

        # Phase 2 (concurrent): the query plan issues independent network calls, so
        # run the cache-miss fetches in parallel instead of summing their latencies.
        # ContextVar-based progress callbacks and the retrieval stage key don't cross
        # threads, so rebind both inside each worker.
        fetch_outcomes: dict[int, tuple[list[SearchResult] | None, Exception | None]] = {}
        if fetch_indices:
            parent_callback = get_progress_callback()

            def _run_fetch(index: int) -> tuple[list[SearchResult] | None, Exception | None]:
                spec = query_plan[index]
                token = set_progress_callback(parent_callback) if parent_callback is not None else None
                stage_token = set_retrieval_stage_key(stage_key)
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
                    return self.provider.search(spec.query), None
                except AppError:
                    raise
                except Exception as exc:  # noqa: BLE001 - degraded per-query, surfaced below
                    return None, exc
                finally:
                    reset_retrieval_stage_key(stage_token)
                    if token is not None:
                        reset_progress_callback(token)

            with ThreadPoolExecutor(max_workers=len(fetch_indices)) as executor:
                future_map = {executor.submit(_run_fetch, index): index for index in fetch_indices}
                for future, index in future_map.items():
                    fetch_outcomes[index] = future.result()

        # Phase 3 (sequential, query-plan order): assemble bundles and cache writes
        # deterministically from the fetched results.
        for index in fetch_indices:
            spec = query_plan[index]
            raw_results, exc = fetch_outcomes[index]
            if exc is not None:
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
                        query_bundles_by_index[index] = stale_cached.with_runtime_metadata(
                            fallback_used=True,
                            fallback_reason="real_retrieval_failed",
                            failure_detail=failure_detail,
                            query_groups=(spec,),
                            query_failures=(),
                        )
                        cache_status_by_index[index] = "stale_hit"
                        emit_retrieval(
                            stage_key=stage_key,
                            query_label=spec.label,
                            query=spec.query,
                            provider_name=provider_name,
                            summary=f"{spec.label} 实时检索失败，已退回陈旧缓存。",
                            details=_retrieval_preview_details(stale_cached),
                            results=_retrieval_result_items(stale_cached),
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
            query_bundles_by_index[index] = bundle
            cache_status_by_index[index] = bundle.cache_status
            emit_retrieval(
                stage_key=stage_key,
                query_label=spec.label,
                query=spec.query,
                provider_name=provider_name,
                summary=f"{spec.label} 已返回 {len(bundle.canonical_results)} 条去重结果。",
                details=_retrieval_preview_details(bundle),
                results=_retrieval_result_items(bundle),
            )

        query_bundles = [query_bundles_by_index[index] for index in sorted(query_bundles_by_index)]
        cache_statuses = [cache_status_by_index[index] for index in sorted(cache_status_by_index)]

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
        relevant_results = self._filter_relevant_results(runtime_results)
        canonical_results = merge_search_results(relevant_results)
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

        for position, bundle in enumerate(query_bundles):
            # Each query numbers its own hits pw-1, pw-2, … so result_ids COLLIDE
            # across queries in the combined pool. Downstream maps keyed by id
            # (dedup union-find, synthesis result_map) then silently conflate
            # unrelated articles — one such collision once collapsed 16 hits,
            # including 4 官方辟谣, into a single unrelated result. Namespace each
            # bundle's ids by query position so they're globally unique; genuine
            # cross-query duplicates still merge via the URL/title relation.
            raw_results.extend(self._namespace_bundle_results(bundle.raw_results, position))
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

    def _append_supplementary_results(
        self,
        bundle: RetrievalBundle,
        primary_query: str,
        *,
        provider,
        log_prefix: str,
        override_source_category: str | None = None,
    ) -> RetrievalBundle:
        """Run a supplementary provider (XHS / Toutiao / Sogou-WeChat / Piyao) and
        merge its hits into ``bundle`` under the standard enrichment schema.

        Supplementary providers are best-effort: any exception is logged and the
        original bundle is returned unchanged.

        ``override_source_category`` pins a fixed source_category (e.g. Piyao's
        ``official_debunking``); otherwise the category is inferred per hit.
        """
        if not provider.enabled:
            return bundle
        short_query = self._shorten_for_supplementary(primary_query)
        if not short_query:
            return bundle
        try:
            hits = provider.search(short_query, max_results=5)
        except Exception as exc:
            logger.warning("%s_append_failed error=%s", log_prefix, exc)
            return bundle
        if not hits:
            return bundle

        retrieved_at = ensure_datetime_string(datetime.now(UTC).isoformat())
        enriched = [
            replace(
                item,
                retrieved_at=retrieved_at,
                source_category=(
                    override_source_category
                    if override_source_category
                    else infer_source_category(item.url, item.source_name)
                ),
                independence_key=build_independence_key(item.url, item.source_name),
                signal_tags=detect_signal_tags(item.title, item.snippet, item.source_name),
            )
            for item in hits
        ]

        existing_keys = {r.independence_key for r in bundle.canonical_results if r.independence_key}
        new_results = [r for r in enriched if r.independence_key not in existing_keys]
        if not new_results:
            return bundle

        combined_canonical = tuple(list(bundle.canonical_results) + new_results)
        combined_raw = tuple(list(bundle.raw_results) + new_results)
        return replace(
            bundle,
            canonical_results=combined_canonical,
            raw_results=combined_raw,
        )

    def _append_xhs_results(
        self, bundle: RetrievalBundle, primary_query: str, *, stage_key: str
    ) -> RetrievalBundle:
        return self._append_supplementary_results(
            bundle, primary_query, provider=self.xhs_provider, log_prefix="xhs"
        )

    def _append_toutiao_results(
        self, bundle: RetrievalBundle, primary_query: str, *, stage_key: str
    ) -> RetrievalBundle:
        return self._append_supplementary_results(
            bundle, primary_query, provider=self.toutiao_provider, log_prefix="toutiao"
        )

    def _append_sogou_weixin_results(
        self, bundle: RetrievalBundle, primary_query: str, *, stage_key: str
    ) -> RetrievalBundle:
        return self._append_supplementary_results(
            bundle, primary_query, provider=self.sogou_weixin_provider, log_prefix="sogou_weixin"
        )

    def _append_piyao_results(
        self, bundle: RetrievalBundle, primary_query: str, *, stage_key: str
    ) -> RetrievalBundle:
        return self._append_supplementary_results(
            bundle,
            primary_query,
            provider=self.piyao_provider,
            log_prefix="piyao",
            override_source_category="official_debunking",
        )

    def _pick_official_whitelist(self, query_text: str) -> tuple[str, ...]:
        """Assemble the site: whitelist for an official-source boost query.

        Always includes the top-tier Chinese state media / gov.cn cluster.
        Extends with a topical group (academic / health / quake / finance) when
        the query text mentions the trigger keyword — a cheap heuristic that
        avoids wasting one query slot on 疾控中心 for a physics-paper rumor.
        """
        extras: list[str] = []
        for hints, domains in OFFICIAL_BOOST_TOPICAL_HINTS:
            if any(hint in query_text for hint in hints):
                extras.extend(domains)
        seen: set[str] = set()
        combined: list[str] = []
        for domain in list(OFFICIAL_BOOST_ALWAYS) + extras:
            if domain not in seen:
                seen.add(domain)
                combined.append(domain)
        return tuple(combined)

    def _append_official_source_results(
        self,
        bundle: RetrievalBundle,
        primary_query: str,
        *,
        stage_key: str,
    ) -> RetrievalBundle:
        """Targeted second-pass retrieval for high-tier official / mainstream sources.

        Triggered ONLY when the initial bundle is thin on independent high-tier
        evidence (grade C/D or zero S/A-tier sources) — the case where a
        C-heavy result set is about to be shipped as-is and the credibility
        score has nothing solid to lean on.

        Fires one ``<query> site:<domain>`` query per whitelist domain (capped
        to a small budget), rather than an ``OR``-joined clause. Baidu treats
        OR-joined site filters as ordinary keywords and Bing's fallback silently
        does the same — a single-domain query is the only form both engines
        will actually filter on. The per-domain hits are dedup'd by
        independence key so redundant OR-noise doesn't inflate the bundle.
        """
        if self.provider is None or not self.provider.enabled:
            return bundle
        if bundle.independent_high_trust_source_count >= 1:
            return bundle
        if bundle.evidence_grade not in {"C", "D"}:
            return bundle
        short_query = self._shorten_for_supplementary(primary_query) or primary_query
        if not short_query:
            return bundle
        whitelist = self._pick_official_whitelist(f"{primary_query} {bundle.query}")
        if not whitelist:
            return bundle

        # Per-domain budget: cap at 4 domains so we don't spend 12 supplementary
        # queries per run. Always-on group leads (gov.cn / xinhuanet / cctv /
        # people.com.cn), topical add-ons follow — `_pick_official_whitelist`
        # already orders them this way.
        max_domains = 4
        existing_keys = {r.independence_key for r in bundle.canonical_results if r.independence_key}
        new_results: list[SearchResult] = []
        matched_domains: list[str] = []
        for domain in whitelist[:max_domains]:
            boost_query = f"{short_query} site:{domain}"
            try:
                hits = self.provider.search(boost_query)
            except Exception as exc:
                logger.warning("official_boost_failed domain=%s error=%s", domain, exc)
                continue
            if not hits:
                continue
            hits = self._filter_relevant_results(list(hits))
            if not hits:
                continue
            retrieved_at = ensure_datetime_string(datetime.now(UTC).isoformat())
            for item in hits:
                enriched = replace(
                    item,
                    retrieved_at=retrieved_at,
                    source_category=infer_source_category(item.url, item.source_name),
                    independence_key=build_independence_key(item.url, item.source_name),
                    signal_tags=detect_signal_tags(item.title, item.snippet, item.source_name),
                )
                if enriched.independence_key in existing_keys:
                    continue
                existing_keys.add(enriched.independence_key)
                new_results.append(enriched)
            matched_domains.append(domain)

        if not new_results:
            return bundle

        logger.info(
            "official_boost_appended count=%d domains=%s",
            len(new_results),
            ",".join(matched_domains),
        )
        combined_canonical = tuple(list(bundle.canonical_results) + new_results)
        combined_raw = tuple(list(bundle.raw_results) + new_results)
        return replace(
            bundle,
            canonical_results=combined_canonical,
            raw_results=combined_raw,
        )

    def _shorten_for_supplementary(self, query: str) -> str:
        """Produce a short query suitable for supplementary providers (XHS,
        Toutiao, Sogou-WeChat, Piyao).

        These providers all work best with concise natural-language queries
        (4-8 Chinese chars). Strategy: extract the first entity-like segment and
        first action-like segment from the space-separated terms.
        """
        # The primary_query is already term-extracted (e.g. "美团 裁了 30% 产品 美团")
        tokens = query.split()
        skip = {
            "官方", "回应", "通报", "说明", "辟谣", "传闻", "网传",
            "热议", "发酵", "转发", "最近", "近日", "近期", "目前",
        }
        kept = [t for t in tokens if t not in skip]
        if not kept:
            return ""
        # Deduplicate preserving order, take first 2-3 meaningful tokens
        seen: set[str] = set()
        result: list[str] = []
        for t in kept:
            if t in seen:
                continue
            seen.add(t)
            result.append(t)
            if len(result) >= 2:
                break
        return " ".join(result)

    def _namespace_bundle_results(
        self, results: tuple[SearchResult, ...], position: int
    ) -> list[SearchResult]:
        # Prefix every result_id with the query's position so ids are globally
        # unique across the combined pool. Remap duplicate_of the same way so an
        # intra-query duplicate link still points at its (renamed) target.
        prefix = f"q{position}-"
        renamed: list[SearchResult] = []
        for item in results:
            new_duplicate_of = f"{prefix}{item.duplicate_of}" if item.duplicate_of else item.duplicate_of
            renamed.append(replace(item, result_id=f"{prefix}{item.result_id}", duplicate_of=new_duplicate_of))
        return renamed

    def _filter_relevant_results(self, results: list[SearchResult]) -> list[SearchResult]:
        if not results:
            return results
        # Hard filter: dictionary/encyclopedia junk (surfaced when a search engine
        # splits a Chinese phrase into single chars) and navigational brand pages
        # (a homepage / section index that only matches the entity term) are never
        # real evidence, so drop them even when they're all we have — returning
        # nothing is more honest than presenting a 字典 entry or a bare homepage as
        # a source.
        grounded = [
            item
            for item in results
            if not self._is_noise_result(item)
            and not self._is_navigational_non_evidence(item)
            and not self._is_topically_disjoint(item)
        ]
        if len(grounded) <= 1:
            return grounded
        # Soft filter: query relevance can be over-aggressive, so fall back to the
        # hard-filtered set rather than dropping everything.
        on_topic = [item for item in grounded if self._result_matches_query(item)]
        return on_topic or grounded

    def _is_noise_result(self, result: SearchResult) -> bool:
        title = result.title
        title_lower = title.lower()
        url = result.url.lower()
        snippet_lower = (result.snippet or "").lower()
        noise_title_patterns = (
            "百度百科", "汉语", "拼音", "笔顺", "部首", "笔画",
            "字典", "词典", "汉字", "解释", "组词", "地名",
            "怎么读", "的意思", "的读音",
            # Baidu image search cards (title always ends with "- 百度图片") are not
            # article evidence — they're a thumbnail gallery page.
            "- 百度图片", "-百度图片",
        )
        if any(p in title_lower for p in noise_title_patterns):
            return True
        # Baidu's "no results" placeholder: when the exact query returns zero
        # indexed items, Baidu still emits a SERP entry whose title echoes the
        # query and ends with "的最新相关信息". It carries no article body — the
        # aggregator page just says "we don't have this". Distinct wording from
        # organic news titles which use "最新消息" not "最新相关信息".
        if "的最新相关信息" in title:
            return True
        # Time-calibration / clock / calendar utility pages: search engines return
        # these for any query containing a place name or number, but they carry no
        # event content (e.g. beijing-time.org for "拼多多雄安买楼").
        time_junk_patterns = (
            "时间校准", "北京时间", "在线时钟", "标准时间", "时间校对",
            "现在时间", "世界时间", "万年历", "对时服务", "时间同步",
        )
        title_and_snippet = f"{title_lower} {snippet_lower}"
        if any(p in title_and_snippet for p in time_junk_patterns):
            return True
        noise_domains = (
            "baike.baidu.com", "dict.", "zidian.", "hanyu.", "hanyuguoxue.com",
            "zdic.net", "guoxuedashi", "hgcha.com", "chagushici.com",
            "shidianguji.com", "gxdq.com",
            "beijing-time.org", "time.org", "-time.com", "shijian.cc",
            "mergeimage.org",
            # Baidu's image search vertical + its captcha/no-result placeholder
            # host — both surface as SERP items with no article content.
            "image.baidu.com", "wappass.baidu.com",
        )
        if any(d in url for d in noise_domains):
            return True
        # CJK dictionary/idiom sites Bing surfaces when it splits a phrase into
        # single chars all share a /zidian/, /hans/ or /character/ lookup path.
        if re.search(r"/(?:zidian|hans|character)/", url):
            return True
        if re.search(r"^《?[一-鿿]》?（", title):
            return True
        if re.search(r"^[一-鿿]（.{0,10}）", title):
            return True
        if re.search(r"^[一-鿿]{1,2}[,，、][一-鿿]{1,4}[,，、]", title):
            return True
        return False

    def _is_navigational_non_evidence(self, result: SearchResult) -> bool:
        # A navigational brand page (homepage / section index like pinduoduo.com/)
        # only ever matches the dominant entity term, so it is not evidence about the
        # claimed event. Keep it ONLY when its title/snippet actually discusses the
        # event — i.e. it shares a *whole* event-specific query token (雄安/研发/招聘),
        # not a brand word (拼多多) and not a bigram fragment that coincidentally lands
        # inside an unrelated word (e.g. the "办公" of 办公楼 matching a batch-platform's
        # "办公采购"). Anything else is a landing page riding the brand name — drop it.
        if not result.is_navigational:
            return False
        event_terms = self._event_specific_terms(result.query or "")
        if not event_terms:
            # No event-specific term to anchor on (query is only the brand): a
            # navigational page can never be evidence, so drop it.
            return True
        haystack = self._normalize_query(" ".join([result.title, result.snippet]))
        return not any(term in haystack for term in event_terms)

    # Well-known brand names the query builder treats as generic scaffolding.
    # These are subjects of interest — when the query names one, results that
    # don't mention it are almost always off-topic (an "美团 裁员" query pulling
    # back Amazon/Meta/辛选 layoff aggregator titles just because they share the
    # verb 裁员). Kept as a class-level constant so _query_subject_tokens and
    # _event_specific_terms stay in sync.
    #
    # We deliberately spell out "阿里巴巴" and "字节跳动" instead of the shorter
    # "阿里" / "字节" because those 2-char prefixes are ambiguous with place names
    # and generic vocabulary (阿里山 / 字节流) — activating the subject gate on
    # them would cause the compound-prefix matcher below to reject legitimate
    # unrelated queries.
    _SUBJECT_BRANDS = frozenset({
        "拼多多", "京东", "淘宝", "阿里巴巴", "腾讯", "百度", "美团", "字节跳动",
    })

    def _event_specific_terms(self, query: str) -> list[str]:
        """Whole-word query tokens that identify the *event*, not the brand.

        Splits the query on whitespace (the query builder already tokenizes into
        space-separated terms), then drops generic scaffolding: the retrieval
        stopwords, generic commerce/navigation words a brand homepage matches by
        default, and any single character. Unlike the old bigram approach these are
        whole tokens, so "办公楼" no longer matches a stray "办公" on a shopping page."""
        generic = self._SUBJECT_BRANDS | {
            "官方", "平台", "采购", "办公", "批发", "旗下", "服务", "企业",
            "公司", "集团", "商城", "商家", "店铺", "下载", "登录", "首页",
            "电商", "购物", "客服", "热线", "联系", "我们", "关于",
        }
        stopwords = self._relevance_stopwords()
        terms: list[str] = []
        for token in self._normalize_query(query).split():
            for chunk in re.findall(r"\d+(?:\.\d+)?[万亿千百]?%?|[A-Za-z]{2,}|[一-鿿]{2,}", token):
                if chunk in generic or chunk in stopwords or chunk in terms:
                    continue
                terms.append(chunk)
        return terms

    def _query_subject_tokens(self, query: str) -> list[str]:
        """Brand/subject tokens the query names — treated as REQUIRED anchors.

        These are the brand names _event_specific_terms strips out as generic
        scaffolding, but they matter for topicality: when the user asks about
        "美团 裁员", a Chinese aggregator page that only shares the verb "裁员"
        (subject is Amazon/Meta/辛选) is off-topic. If the query names a subject
        brand, the result must mention it — otherwise it isn't evidence for
        THIS claim.

        Match a brand against the query's CJK chunks (produced by the same
        chunk regex _event_specific_terms uses). A chunk activates the subject
        gate when it either equals the brand ("美团 产品") or starts with it
        ("拼多多雄安新区招聘信息"). Merely appearing as a substring is NOT
        enough — otherwise a "阿里山 事故" query would falsely trigger the
        "阿里" (Alibaba) gate. Ambiguous 2-char brands ("阿里"/"字节") are kept
        out of _SUBJECT_BRANDS specifically to make this prefix rule safe."""
        tokens: list[str] = []
        normalized = self._normalize_query(query)
        chunks = re.findall(r"\d+(?:\.\d+)?[万亿千百]?%?|[A-Za-z]{2,}|[一-鿿]{2,}", normalized)
        for brand in self._SUBJECT_BRANDS:
            for chunk in chunks:
                if chunk == brand or chunk.startswith(brand):
                    if brand not in tokens:
                        tokens.append(brand)
                    break
        return tokens

    def _result_matches_query(self, result: SearchResult) -> bool:
        raw_text = " ".join([result.title, result.snippet, result.source_name])
        text = self._normalize_query(raw_text)
        # Case-fold once for the event-token fallback below. CJK characters are
        # invariant under casefold, so brand/subject matching is unaffected; the
        # Latin path becomes case-insensitive so an "OpenAI Layoffs" query still
        # matches a "openai layoffs" title.
        text_folded = text.casefold()
        if any(marker in text for marker in ("未提及", "未涉及", "不涉及", "无关", "another", "unrelated")):
            return False
        # Dual filter — subject brand REQUIRED, event term as fallback.
        #
        # Historically this method only rejected results carrying explicit "无关"
        # markers, which meant any Chinese aggregator page sharing the query's
        # verb ("裁员") slipped through: an "美团 产品 裁员 70%" query kept
        # Amazon/Meta/辛选 layoff titles that never mention 美团.
        #
        # Fix: when the query names a subject brand (美团/京东/…), require the
        # result text to mention that brand — no brand mention, not evidence.
        # When the query has no brand (e.g. a pure question), fall back to
        # event-specific tokens so we don't drop everything for open queries.
        # If neither exists (very short query), keep the pre-existing accept-all
        # behavior so this never returns an empty set for legitimate queries.
        subjects = self._query_subject_tokens(result.query or "")
        if subjects:
            return any(subject in text for subject in subjects)
        event_terms = self._event_specific_terms(result.query or "")
        if event_terms:
            return any(term.casefold() in text_folded for term in event_terms)
        return True

    def _is_topically_disjoint(self, result: SearchResult) -> bool:
        """Hard filter: an English/non-CJK result returned for a CJK query that
        shares none of the query's event terms.

        A search engine that splits a Chinese phrase into single chars (or has no
        real hits) will surface totally off-topic pages — e.g. English dictionary
        entries for "Chauffeur" returned for a query about 拼多多雄安. These are
        never evidence. Unlike the soft ``_result_matches_query`` filter, this
        drops such results even when they are the entire batch: a dictionary entry
        masquerading as evidence is worse than returning nothing.

        Deliberately narrow — fires ONLY when the query is CJK-dominant but the
        result title+snippet is essentially non-CJK (an English/foreign page) AND
        shares no event-specific term. A Chinese result whose wording merely
        differs from the query is left to the soft filter, so a live provider's
        genuine (if loosely matched) hits are never hard-dropped."""
        query = result.query or ""
        event_terms = self._event_specific_terms(query)
        if len(event_terms) < 2:
            return False
        # The query must be CJK-dominant for this filter to apply.
        if not re.search(r"[一-鿿]", query):
            return False
        haystack = self._normalize_query(" ".join([result.title, result.snippet]))
        if not haystack:
            return False
        # If the result text carries almost no CJK, it is a foreign-language page
        # surfaced for a Chinese query — only keep it if it shares an event term.
        cjk_chars = len(re.findall(r"[一-鿿]", haystack))
        if cjk_chars >= 4:
            # Enough Chinese content to be a plausible domestic hit; defer to soft filter.
            return False
        return not any(term in haystack for term in event_terms)

    def _relevance_stopwords(self) -> set[str]:
        return {
            "官方", "回应", "通报", "说明", "辟谣", "用户提供文本",
            "传闻", "网传", "热议", "发酵", "转发", "相关", "信息",
            "开始", "已经", "而且", "可能", "到底", "是否", "是不是",
            "了吗", "真的", "假的", "的吗", "是真",
        }

    def _llm_query_terms(self, event: NormalizedEvent):
        """Entity-focused search terms from the reasoner, or None to fall back.

        Only fires on the agent+LLM retrieval path; any failure degrades silently to the
        rule-based query builder so the off+mock path is unchanged.

        Gated behind ``llm_query_extraction_enabled`` (default off): the extraction
        call costs a full ~40s LLM round-trip on the current gateway, but the
        rule-based dedup query builder already produces clean queries, so we skip
        it by default and reserve the LLM budget for synthesis/verdict.
        """
        if not self.settings.llm_query_extraction_enabled:
            return None
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

    def _alias_query_specs(self, alias_query: str, *, claim_hint: str) -> list[RetrievalQuerySpec]:
        normalized = self._normalize_query(alias_query)
        if not normalized:
            return []
        return [
            RetrievalQuerySpec(
                label="alias_recall",
                query=normalized,
                rationale="用 LLM 抽取的别名/母品牌/相关表述再补一路检索，扩大召回。",
                claim_hint=claim_hint,
            )
        ]

    def _subclaim_query_specs(self, event: NormalizedEvent) -> list[RetrievalQuerySpec]:
        """Focused sub-queries so a multi-part rumor's each sub-fact gets its own
        search, not just the whole combined sentence.

        A rumor like "拼多多在雄安买了三栋楼招了5000研发人员" bundles distinct facts
        (buildings count, headcount, role) that a single whole-sentence query tends
        to answer only for the dominant one. We keep the leading entities/place as an
        anchor, split the rest into segments at action verbs (买 / 招 / 投资 …), and
        pair each segment with the anchor — e.g. "拼多多 雄安 买 楼" and
        "拼多多 雄安 招 研发人员". Empirically these surface distinct evidence (e.g. a
        page clarifying 5000 = total posts, first batch 1000) the combined query misses.
        Rule-based (no extra LLM round-trip) so it never adds gateway latency.
        Fires only when the sentence has ≥2 action verbs — a single-fact rumor keeps
        the normal plan and gets no redundant sub-queries.
        """
        # De-dupe the parts first: title/summary/raw_input often coincide, and a
        # repeated sentence would fake multiple action segments (买…买…买…). Prefer the
        # single longest distinct part as the claim sentence to split.
        parts = list(dict.fromkeys(filter(None, [event.title, event.summary, event.raw_input])))
        text = self._normalize_query(max(parts, key=len) if parts else "")
        if not text:
            return []
        anchor_terms = self._subclaim_anchor_terms(text)
        segments = self._subclaim_action_segments(text)
        if not anchor_terms or len(segments) < 2:
            return []
        specs: list[RetrievalQuerySpec] = []
        seen: set[str] = set()
        for index, segment in enumerate(segments):
            seg_terms = [
                t
                for t in self._build_term_query(segment).split()
                if t not in anchor_terms and not any(a in t or t in a for a in anchor_terms)
            ]
            if not seg_terms:
                continue
            query = self._normalize_query(" ".join([*anchor_terms, *seg_terms[:4]]))
            if not query or query in seen:
                continue
            seen.add(query)
            specs.append(
                RetrievalQuerySpec(
                    label=f"subclaim_{index + 1}",
                    query=query,
                    rationale="把多部分传闻按子事实拆开各检一路，给每个子说法找独立证据（数量/人数/岗位类型）。",
                    claim_hint=segment,
                )
            )
            if len(specs) >= 2:
                break
        return specs

    # Action verbs that start a new sub-fact ("买了…楼" vs "招了…研发人员"). Splitting
    # on these separates the bundled facts without needing a digit, so Chinese
    # numerals (三栋 / 五千) don't defeat the split.
    # Deliberately EXCLUDES 收 and 成: with no Chinese word boundaries these fire
    # inside common 2-char words (营收 / 年收入 / 完成 / 达成 / 3成), cutting a clause
    # mid-word and producing junk sub-queries like "收降3". 收购 still splits on 购
    # and 建成 on 建, so dropping the two ambiguous chars loses little real coverage.
    _SUBCLAIM_VERBS = "买购租建招设开裁持投"
    _SUBCLAIM_VERB_RE = re.compile(f"[{_SUBCLAIM_VERBS}]")

    def _subclaim_anchor_terms(self, text: str) -> list[str]:
        # Terms before the first action verb = subject + place anchor. Regex can't
        # word-segment Chinese, so we take the head, strip trailing particles, and
        # keep it whole plus split off a trailing place token — good enough to anchor.
        match = self._SUBCLAIM_VERB_RE.search(text)
        head = (text[: match.start()] if match else text).strip()
        # Strip leading/trailing scaffolding chars so "拼多多在雄安" -> "拼多多在雄安"
        # then peel a trailing 在X place: keep both the full head and the tail token.
        head = re.sub(r"(最近|有个|有一个|据说|网传|听说)", "", head)
        terms: list[str] = []
        for token in re.findall(r"\d+(?:\.\d+)?[万亿千百]?%?|[A-Za-z]{2,}|[一-鿿]{2,8}", head):
            token = re.sub(r"[在了的和与并还]$", "", token)
            # If the token embeds a place after 在, split it: 拼多多在雄安 -> 拼多多, 雄安
            for part in re.split(r"在", token):
                part = part.strip()
                if len(part) >= 2 and part not in terms:
                    terms.append(part)
        return terms[:3]

    def _subclaim_action_segments(self, text: str) -> list[str]:
        # Cut the sentence at each action verb; each piece is one sub-fact clause.
        starts = [m.start() for m in self._SUBCLAIM_VERB_RE.finditer(text)]
        if not starts:
            return []
        # Collapse adjacent verbs (投资/收购 back-to-back) into one boundary so a single
        # action isn't split mid-word.
        bounds: list[int] = []
        for s in starts:
            if not bounds or s - bounds[-1] >= 3:
                bounds.append(s)
        bounds.append(len(text))
        segments = [text[bounds[i] : bounds[i + 1]].strip() for i in range(len(bounds) - 1)]
        return [s for s in segments if len(s) >= 2][:3]

    def build_query_plan(
        self, event: NormalizedEvent, *, request_context: dict[str, Any] | None = None
    ) -> list[RetrievalQuerySpec]:
        """Public entry to the query planner.

        Lets callers outside this service (e.g. the multi-agent normalize step)
        compute the plan once and reuse its primary query, instead of each
        parallel source agent re-planning and re-triggering the LLM extractor."""
        return self._build_query_plan(event, request_context=request_context or {})

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
                        query=self._extend_query(base_query, *OFFICIAL_QUERY_TERMS, self._real_source_name(event.source_name)),
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

        keyword_query = self._build_term_query(event.title, event.summary, " ".join(event.keywords[:5]), self._real_source_name(event.source_name))
        first_clause_query = self._build_term_query(*self._extract_claim_clauses(event.title, event.summary))

        # LLM-driven query construction: the raw sentence is a poor search query
        # ("京东开始造游轮了，而且..."), so when the reasoner is available, replace
        # the primary/keyword query with entity-focused terms it extracts. Falls
        # back to the rule-based queries above when disabled/unparseable.
        alias_query = ""
        deep_mode = str(request_context.get("mode", "")).strip().lower() == "deep"
        llm_terms = self._llm_query_terms(event) if deep_mode else None
        if llm_terms is not None:
            primary_query = llm_terms.primary_query
            keyword_query = llm_terms.primary_query
            # The reasoner also surfaces aliases (parent brand, person behind it,
            # alternate phrasings) that hit the same event from another angle;
            # fold them into one extra query to widen recall.
            alias_query = self._build_term_query(*llm_terms.aliases[:4])

        official_query = self._extend_query(keyword_query or primary_query, *OFFICIAL_QUERY_TERMS, self._real_source_name(event.source_name))
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
            official_query = self._extend_query(rewritten_query or primary_query, *OFFICIAL_QUERY_TERMS, self._real_source_name(event.source_name))
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
                    *self._alias_query_specs(alias_query, claim_hint=rewritten_query or primary_query),
                ]
            )

        numeric_fuzzy_query = self._build_numeric_fuzzy_query(primary_query)

        return self._dedupe_query_plan(
            [
                RetrievalQuerySpec(
                    label="event_core",
                    query=primary_query,
                    rationale="围绕事件标题、摘要与关键词建立主检索 query。",
                    claim_hint=event.summary or primary_query,
                ),
                *(
                    [RetrievalQuerySpec(
                        label="event_numeric_fuzzy",
                        query=numeric_fuzzy_query,
                        rationale="去掉具体数字，用实体+动作检索，命中数字不同但同一事件的辟谣/报道。",
                        claim_hint=event.summary or primary_query,
                    )]
                    if numeric_fuzzy_query else []
                ),
                RetrievalQuerySpec(
                    label="event_claim",
                    query=first_clause_query or keyword_query,
                    rationale="把事件摘要压到更接近单条 claim 的 query，补足细粒度证据。",
                    claim_hint=event.summary or primary_query,
                ),
                # Sub-claim queries (deep mode only): split a multi-part rumor so each
                # sub-fact gets its own search. Placed before official/propagation so
                # they survive the 5-query cap when the rumor is genuinely multi-part.
                *(self._subclaim_query_specs(event) if deep_mode else []),
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
                *self._alias_query_specs(alias_query, claim_hint=event.summary or primary_query),
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
            if len(query_plan) >= 5:
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

    def _real_source_name(self, source_name: str | None) -> str | None:
        # default_source_name emits UI placeholders ("用户提供文本") for inputs with
        # no real publisher. Those are provenance labels, never search terms — folding
        # them into a query drags in unrelated hits, so drop them before query build.
        if source_name and source_name in INPUT_PLACEHOLDER_SOURCE_NAMES:
            return None
        return source_name

    def _build_primary_query(self, event: NormalizedEvent) -> str:
        if event.input_type == "question_only":
            if self.settings.uses_agent_retrieval:
                return event.raw_input.strip().rstrip("\uFF1F?")
            return self._rewrite_question_query(event.raw_input)

        # Extract deduplicated terms rather than concatenating raw parts: title and
        # summary usually overlap heavily (title is often a prefix of summary), so
        # whole-part dedup leaves a redundant, punctuation-laden blob that makes the
        # search engine fall back to matching only the brand \u2192 homepage hits.
        term_query = self._build_term_query(
            event.title, event.summary, " ".join(event.keywords[:4])
        )
        return term_query or event.raw_input.strip()

    def _build_term_query(self, *texts: str | None, max_terms: int = 8) -> str:
        terms: list[str] = []
        seen: set[str] = set()
        for text in texts:
            if not text:
                continue
            for term in re.findall(r"\d+(?:\.\d+)?[万亿千百]?%?|[A-Za-z]{2,}|[\u4e00-\u9fff]{2,12}", text):
                cleaned = term.strip()
                if not cleaned or cleaned in seen:
                    continue
                seen.add(cleaned)
                terms.append(cleaned)
                if len(terms) >= max_terms:
                    return " ".join(terms)
        return " ".join(terms)

    def _extract_claim_clauses(self, *texts: str | None) -> list[str]:
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

    def _extend_query(self, base_query: str, *extra_terms: str | None) -> str:
        return self._build_term_query(base_query, " ".join(term for term in extra_terms if term))

    _NUMERIC_PERCENT_RE = re.compile(r"\d+(?:\.\d+)?%?")

    def _build_numeric_fuzzy_query(self, query: str) -> str:
        """Strip specific numbers/percentages from the query to catch same-event
        articles that cite different figures (e.g. refutation says 50% when rumor
        says 30%). Returns empty string if stripping leaves nothing useful or
        nothing was stripped.
        """
        stripped = self._NUMERIC_PERCENT_RE.sub("", query)
        terms = [t for t in stripped.split() if len(t) >= 2]
        if not terms or terms == query.split():
            return ""
        result = " ".join(terms)
        if len(result) < 4:
            return ""
        return result

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

    def _combine_cache_keys(self, bundles: list[RetrievalBundle]) -> str | None:
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
        query_plan: list[RetrievalQuerySpec] | None = None,
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

    def _summarize_query_failures(self, failures: list[str]) -> str | None:
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


# How many per-query hits to stream to the trace. The goal is full observability of
# what each search returned, so this is generous; a query rarely yields more.
_RETRIEVAL_RESULTS_LIMIT = 12


def _retrieval_result_items(bundle: RetrievalBundle) -> list[dict[str, Any]]:
    """Structured per-hit records for the trace so the frontend can show exactly
    what a search returned — title, snippet, url, source, tier — not just a count."""
    items: list[dict[str, Any]] = []
    for result in bundle.canonical_results[:_RETRIEVAL_RESULTS_LIMIT]:
        items.append(
            {
                "title": result.title,
                "url": result.url,
                "snippet": result.snippet,
                "source_name": result.source_name,
                "source_tier": result.source_tier,
                "published_at": result.published_at,
                "category": result.effective_source_category,
            }
        )
    return items
