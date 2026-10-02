"""Per-claim focused retrieval.

After the claim extractor produces atomic claims, this module fires targeted
search queries for fact-type claims whose initial evidence is weak (grade C/D).
Results are merged back into the main retrieval bundle so the verdict engine
has richer, more focused evidence.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import replace

from backend.app.models.schemas import ClaimItem, ClaimResult, NormalizedEvent
from backend.app.services.evidence_goals import evidence_gaps_for_claim
from backend.app.services.progress import (
    emit_log,
    emit_stage,
    get_progress_callback,
    reset_progress_callback,
    reset_retrieval_stage_key,
    set_progress_callback,
    set_retrieval_stage_key,
)
from backend.app.services.retrieval_deduper import merge_search_results
from backend.app.services.retrieval_models import RetrievalBundle, SearchResult
from backend.app.services.run_control import check_run_control

logger = logging.getLogger(__name__)


def needs_focused_retrieval(claim: ClaimResult) -> bool:
    return claim.claim_type == "fact" and (claim.verdict == "insufficient" or bool(claim.evidence_gaps))


def refine_evidence_gaps(*, request, event, verdict, bundle, retriever, verdict_engine,
                         max_iterations=3, should_stop=None, completion_fn=None):
    iterations = 0
    searched_claims: set[str] = set()
    for iteration in range(max_iterations):
        affected = [index for index, claim in enumerate(verdict.claim_results) if needs_focused_retrieval(claim)]
        if not affected or bundle is None or (should_stop is not None and should_stop()):
            break
        check_run_control()
        claims = [ClaimItem(claim=verdict.claim_results[index].claim,
                            claim_type=verdict.claim_results[index].claim_type) for index in affected]
        enriched = enrich_retrieval_for_claims(
            claims, bundle, retriever, event, iteration=iteration, claim_results=verdict.claim_results,
            request_context=request.request_context if request is not None else None,
            searched_claims=searched_claims,
        )
        iterations += 1
        if enriched is bundle:
            if any(verdict.claim_results[index].claim not in searched_claims for index in affected):
                continue
            break
        bundle = enriched
        judged = verdict_engine.evaluate_with_source(request=request, event=event, claims=claims,
                                                     retrieval_bundle=bundle, completion_fn=completion_fn)
        results = list(verdict.claim_results)
        for index, update in zip(affected, judged.claim_results, strict=False):
            previous = results[index]
            if (previous.claim, previous.claim_type) == (update.claim, update.claim_type):
                if (update.truth_probability is None and previous.verdict == update.verdict
                        and previous.confidence == update.confidence and previous.evidence == update.evidence):
                    update = update.model_copy(update={
                        "truth_probability": previous.truth_probability,
                        "probability_basis": previous.probability_basis,
                    })
                results[index] = update
        evidence = list(verdict.evidence)
        for item in judged.evidence:
            if item not in evidence:
                evidence.append(item)
        grade = max((verdict.evidence_grade, judged.evidence_grade, bundle.evidence_grade),
                    key=lambda value: {"D": 0, "C": 1, "B": 2, "A": 3}.get(value, -1))
        verdict = replace(judged, claim_results=results, evidence=evidence, evidence_grade=grade)
    return bundle, verdict, iterations

# Maximum number of per-claim queries to avoid excessive latency.
MAX_PER_CLAIM_QUERIES = 3

# Chinese filler / question words to strip when building focused queries.
_FILLER_RE = re.compile(
    r"(据称|据悉|据说|据了解|有人说|有消息称|网传|传闻|疑似|可能|或许|大概|"
    r"已经|正在|即将|是否|是不是|有没有|请问|想问|听说|"
    r"一个|这个|那个|某个|的话|来说|而言|其实|确实|当然)"
)
# Keep entities, actions, numbers by stripping only pure filler.
_WHITESPACE_RE = re.compile(r"\s+")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?[万亿千百十人名个条栋]?")

# Query variant suffixes for multi-round diversification.
# Each iteration appends different angle-keywords to avoid searching the same
# terms repeatedly and surface different source types.
_QUERY_ANGLES = [
    [],                                    # Round 1: plain subject+number
    ["真实数量", "实际", "官方数据"],       # Round 2: look for official/real numbers
    ["官方回应", "辟谣", "通报"],           # Round 3: look for official denials/responses
]


def _build_focused_query(claim_text: str, iteration: int = 0) -> str:
    """Strip filler words from claim text to produce a focused search query.

    Keeps entities, actions, and numbers — strips hedging/question language
    that dilutes SERP relevance. For claims with numbers, constructs a
    number-focused query to find the real figure.

    Different iterations produce different query angles to avoid repeating the
    same search and surface diverse sources.
    """
    query = _FILLER_RE.sub(" ", claim_text)
    query = _WHITESPACE_RE.sub(" ", query).strip()

    # If claim contains numbers, build a number-verification query:
    # extract the subject + action + "多少/人数/数量" to find the actual number
    numbers = _NUMBER_RE.findall(claim_text)
    if numbers:
        import re as _re
        # Subject: leading entity before first structural word (在/买/招...)
        subject_m = _re.match(r"([一-鿿]+?)(?=在|[买购租建招设开裁投收持])", claim_text)
        subject = subject_m.group(1) if subject_m else ""
        places = _re.findall(r"在([一-鿿]{2,4}?)(?=[买购租建招设开裁投收持了]|$)", claim_text)
        terms = [t for t in [subject] + places + numbers if t and len(t) >= 2]
        terms = list(dict.fromkeys(terms))
        if len(terms) >= 2:
            base = " ".join(terms[:4])
            # Add angle suffix for later iterations
            angle_idx = min(iteration, len(_QUERY_ANGLES) - 1)
            angle_terms = _QUERY_ANGLES[angle_idx]
            if angle_terms:
                base = f"{base} {angle_terms[0]}"
            return base

    if len(query) < 6:
        query = claim_text.strip()
    if len(query) > 80:
        query = query[:80].rsplit(" ", 1)[0] or query[:80]

    # Add angle suffix for later iterations (non-number claims)
    angle_idx = min(iteration, len(_QUERY_ANGLES) - 1)
    angle_terms = _QUERY_ANGLES[angle_idx]
    if angle_terms and len(query) < 70:
        query = f"{query} {angle_terms[0]}"

    return query


def _claim_needs_retrieval(
    claim: ClaimItem,
    bundle: RetrievalBundle,
) -> bool:
    """Decide whether a claim warrants its own retrieval round.

    Only fact-type claims qualify. We rely on the caller (pipeline) to gate
    on whether there are actually weak verdicts — here we just filter to facts.
    """
    return claim.claim_type == "fact"


def _namespace_batch(results: list[SearchResult], batch: int) -> list[SearchResult]:
    """Prefix every result_id in one batch with b{batch}- so ids are unique
    across batches that were each numbered from q0- independently.

    duplicate_of is rewritten with the same prefix so intra-batch references stay
    consistent; cross-batch dedup then relies on the URL/title relation, which is
    exactly what result_id collisions were suppressing.
    """
    prefix = f"b{batch}-"
    namespaced: list[SearchResult] = []
    for item in results:
        namespaced.append(
            replace(
                item,
                result_id=f"{prefix}{item.result_id}",
                canonical_result_id=f"{prefix}{item.canonical_result_id}" if item.canonical_result_id else None,
                duplicate_of=f"{prefix}{item.duplicate_of}" if item.duplicate_of else None,
                merged_result_ids=tuple(f"{prefix}{result_id}" for result_id in item.merged_result_ids),
            )
        )
    return namespaced


def enrich_retrieval_for_claims(
    claims: list[ClaimItem],
    retrieval_bundle: RetrievalBundle,
    retrieval_service: RetrievalService,  # noqa: F821 — forward ref to avoid circular import
    resolved_event: NormalizedEvent,
    iteration: int = 0,
    claim_results: list[ClaimResult] | None = None,
    request_context: dict | None = None,
    searched_claims: set[str] | None = None,
) -> RetrievalBundle:
    """Run per-claim focused retrieval and merge results into the bundle.

    Parameters
    ----------
    claims:
        The full claim list from the extractor (all types).
    retrieval_bundle:
        The current best retrieval bundle (after initial + follow-up).
    retrieval_service:
        The RetrievalService instance used to execute queries.
    resolved_event:
        The resolved event needed by retrieve_for_event.
    iteration:
        The current iteration index (0-based). Later iterations use different
        query angles to avoid repeating the same searches.

    Returns
    -------
    RetrievalBundle with any newly found results merged in. If nothing new was
    found or all per-claim retrievals fail, the original bundle is returned.
    """
    # Filter to fact claims that need focused retrieval.
    candidates = [c for c in claims if _claim_needs_retrieval(c, retrieval_bundle)]
    check_run_control()
    outcomes_by_claim = {item.claim: item for item in (claim_results or [])}
    if claim_results is not None:
        candidates = [claim for claim in candidates if claim.claim in outcomes_by_claim
                      and needs_focused_retrieval(outcomes_by_claim[claim.claim])]
        candidates.sort(key=lambda claim: (
            claim.claim in (searched_claims or set()),
            not (outcomes_by_claim[claim.claim].verdict == "insufficient"),
            not bool(outcomes_by_claim[claim.claim].evidence_gaps),
        ))
    if not candidates:
        emit_stage(
            stage_key="per_claim_retrieval",
            title="逐 Claim 补充检索",
            status="skipped",
            summary="无证据不足或属性缺口的事实型 claim，跳过逐条检索。",
            details=[f"evidence_grade={retrieval_bundle.evidence_grade}"],
        )
        return retrieval_bundle

    # Cap the number of per-claim queries.
    candidates = candidates[:MAX_PER_CLAIM_QUERIES]
    if searched_claims is not None:
        searched_claims.update(claim.claim for claim in candidates)

    emit_stage(
        stage_key="per_claim_retrieval",
        title="逐 Claim 补充检索",
        status="running",
        summary=f"正在为 {len(candidates)} 条待补证 claim 执行定向检索。",
        details=[f"claim_{i}={c.claim[:40]}" for i, c in enumerate(candidates)],
    )

    new_results: list[SearchResult] = []
    queries_executed = 0
    queries_failed = 0

    # Deduplicate identical focused queries across candidates. Two claims that
    # share subject + numbers (e.g. "A 招了 5000 人" and "A 招聘 5000 员工")
    # produce the same _build_focused_query output; running the SERP fetch
    # twice would waste a full network round-trip and burn provider budget.
    # Compute the query for every candidate up front, keep the first candidate
    # that owns each unique query as the executor, and reuse its results for
    # subsequent duplicates so the merge below still sees per-candidate output.
    candidate_queries = []
    for claim in candidates:
        outcome = outcomes_by_claim.get(claim.claim)
        gaps = outcome.evidence_gaps if outcome else evidence_gaps_for_claim(claim.claim, list(retrieval_bundle.canonical_results))
        suggestions = [query for gap in gaps for query in gap.suggested_queries]
        candidate_queries.append(suggestions[min(iteration, len(suggestions) - 1)] if suggestions
                                 else _build_focused_query(claim.claim, iteration=iteration))
    query_owner: dict[str, int] = {}
    duplicate_of: dict[int, int] = {}
    for i, q in enumerate(candidate_queries):
        if q in query_owner:
            duplicate_of[i] = query_owner[q]
        else:
            query_owner[q] = i
    if duplicate_of:
        emit_log(
            stage_key="per_claim_retrieval",
            title="Per-claim query 去重",
            summary=f"发现 {len(duplicate_of)} 条 claim 的定向 query 与前面重复，跳过重复请求。",
            details=[f"dup_index={k}->owner_index={v}" for k, v in sorted(duplicate_of.items())],
        )
        candidate_queries_effective = [i for i in range(len(candidates)) if i not in duplicate_of]
    else:
        candidate_queries_effective = list(range(len(candidates)))

    # Each per-claim query is an independent network round-trip, so fan them out
    # concurrently instead of summing their latencies. ContextVar-based progress
    # callbacks and the retrieval stage key don't cross threads, so rebind both
    # inside each worker (mirrors RetrievalService._run_fetch). Results are keyed
    # by candidate index and reassembled in order below so the merge stays
    # deterministic regardless of completion order.
    parent_callback = get_progress_callback()

    def _run_claim_query(index: int, claim: ClaimItem) -> tuple[int, list[SearchResult] | None, Exception | None]:
        check_run_control()
        callback_token = set_progress_callback(parent_callback) if parent_callback is not None else None
        stage_token = set_retrieval_stage_key("per_claim_retrieval")
        try:
            focused_query = candidate_queries[index]
            emit_log(
                stage_key="per_claim_retrieval",
                title="Per-claim query",
                summary=f"执行定向检索: {focused_query[:60]}",
                details=[f"original_claim={claim.claim[:60]}"],
            )
            per_claim_context = {
                **(request_context or {}),
                "force_retrieval_query": focused_query,
                "retrieval_stage_key": "per_claim_retrieval",
            }
            per_claim_bundle = retrieval_service.retrieve_for_event(
                resolved_event, request_context=per_claim_context
            )
            return index, list(per_claim_bundle.canonical_results), None
        except Exception as exc:  # noqa: BLE001 - degraded per-query, surfaced below
            return index, None, exc
        finally:
            reset_retrieval_stage_key(stage_token)
            if callback_token is not None:
                reset_progress_callback(callback_token)

    outcomes: dict[int, tuple[list[SearchResult] | None, Exception | None]] = {}
    with ThreadPoolExecutor(max_workers=max(1, len(candidate_queries_effective))) as executor:
        futures = [executor.submit(copy_context().run, _run_claim_query, i, candidates[i]) for i in candidate_queries_effective]
        for future in futures:
            index, results, exc = future.result()
            outcomes[index] = (results, exc)
    # Fill in results for candidates whose query was a duplicate — reuse the
    # owner's outcome so downstream merge/attribution still sees per-candidate
    # data. We copy the list so per-candidate namespacing below doesn't mutate
    # a shared reference (each _namespace_batch call rebuilds SearchResults).
    for dup_idx, owner_idx in duplicate_of.items():
        owner_results, owner_exc = outcomes.get(owner_idx, (None, None))
        outcomes[dup_idx] = (list(owner_results) if owner_results else owner_results, owner_exc)

    # Keep existing canonical IDs stable: fetched bodies and checkpoint state use
    # them as keys. Prefix only incoming batches and avoid collisions even if a
    # previous enrichment already introduced the same prefixed ID.
    existing = list(retrieval_bundle.canonical_results)
    used_ids = {item.result_id for item in existing}
    for index, claim in enumerate(candidates):
        results, exc = outcomes[index]
        if exc is not None:
            queries_failed += 1
            logger.warning(
                "Per-claim retrieval failed for claim=%s: %s",
                claim.claim[:40],
                exc,
            )
            continue
        queries_executed += 1
        if results:
            batch = index + 1
            while any(f"b{batch}-{item.result_id}" in used_ids for item in results):
                batch += len(candidates)
            namespaced = _namespace_batch(results, batch)
            new_results.extend(namespaced)
            used_ids.update(item.result_id for item in namespaced)

    if not new_results:
        emit_stage(
            stage_key="per_claim_retrieval",
            title="逐 Claim 补充检索",
            status="completed",
            summary="定向检索未发现新结果。",
            details=[
                f"queries_executed={queries_executed}",
                f"queries_failed={queries_failed}",
            ],
        )
        return retrieval_bundle

    # Only reuse an existing ID when it still identifies the exact same URL.
    # Different URLs can be copies of one article, but keeping the old ID while
    # replacing its URL would attach any checkpointed page body to a new source.
    merged_canonical = merge_search_results(existing + new_results)
    existing_ids = {item.result_id for item in existing}
    stable_canonical = []
    for item in merged_canonical:
        previous = next((result for result in existing
                         if result.url == item.url and result.result_id in item.merged_result_ids), None)
        if previous and item.result_id not in existing_ids:
            stable_canonical.append(replace(
                item, result_id=previous.result_id, canonical_result_id=previous.result_id,
                merged_result_ids=tuple(dict.fromkeys(
                    [*(value for value in item.merged_result_ids if value != previous.result_id), item.result_id]
                )),
            ))
        else:
            stable_canonical.append(item)
    merged_canonical = tuple(stable_canonical)

    # If an incoming original wins over an earlier repost at a different URL,
    # keep the repost's raw provenance even when its canonical slot is replaced.
    raw_results = list(retrieval_bundle.raw_results)
    raw_ids = {item.result_id for item in raw_results}
    raw_results.extend(item for item in existing if item.result_id not in raw_ids)
    raw_results.extend(new_results)

    enriched_bundle = replace(
        retrieval_bundle,
        canonical_results=merged_canonical,
        raw_results=tuple(raw_results),
    )

    emit_stage(
        stage_key="per_claim_retrieval",
        title="逐 Claim 补充检索",
        status="completed",
        summary=f"定向检索补充了 {len(new_results)} 条新结果，合并去重后共 {len(merged_canonical)} 条。",
        details=[
            f"queries_executed={queries_executed}",
            f"queries_failed={queries_failed}",
            f"new_results={len(new_results)}",
            f"merged_total={len(merged_canonical)}",
            f"evidence_grade_before={retrieval_bundle.evidence_grade}",
            f"evidence_grade_after={enriched_bundle.evidence_grade}",
        ],
    )

    return enriched_bundle
