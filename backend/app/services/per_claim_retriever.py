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
from dataclasses import replace
from typing import List, Optional, Tuple

from backend.app.models.schemas import ClaimItem, NormalizedEvent
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

logger = logging.getLogger(__name__)

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


def enrich_retrieval_for_claims(
    claims: List[ClaimItem],
    retrieval_bundle: RetrievalBundle,
    retrieval_service: "RetrievalService",  # noqa: F821 — forward ref to avoid circular import
    resolved_event: NormalizedEvent,
    iteration: int = 0,
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
    if not candidates:
        emit_stage(
            stage_key="per_claim_retrieval",
            title="逐 Claim 补充检索",
            status="skipped",
            summary="初始证据质量充足或无事实型 claim，跳过逐条检索。",
            details=[f"evidence_grade={retrieval_bundle.evidence_grade}"],
        )
        return retrieval_bundle

    # Cap the number of per-claim queries.
    candidates = candidates[:MAX_PER_CLAIM_QUERIES]

    emit_stage(
        stage_key="per_claim_retrieval",
        title="逐 Claim 补充检索",
        status="running",
        summary=f"正在为 {len(candidates)} 条弱证据 claim 执行定向检索。",
        details=[f"claim_{i}={c.claim[:40]}" for i, c in enumerate(candidates)],
    )

    new_results: List[SearchResult] = []
    queries_executed = 0
    queries_failed = 0

    # Each per-claim query is an independent network round-trip, so fan them out
    # concurrently instead of summing their latencies. ContextVar-based progress
    # callbacks and the retrieval stage key don't cross threads, so rebind both
    # inside each worker (mirrors RetrievalService._run_fetch). Results are keyed
    # by candidate index and reassembled in order below so the merge stays
    # deterministic regardless of completion order.
    parent_callback = get_progress_callback()

    def _run_claim_query(index: int, claim: ClaimItem) -> Tuple[int, Optional[List[SearchResult]], Optional[Exception]]:
        callback_token = set_progress_callback(parent_callback) if parent_callback is not None else None
        stage_token = set_retrieval_stage_key("per_claim_retrieval")
        try:
            focused_query = _build_focused_query(claim.claim, iteration=iteration)
            emit_log(
                stage_key="per_claim_retrieval",
                title="Per-claim query",
                summary=f"执行定向检索: {focused_query[:60]}",
                details=[f"original_claim={claim.claim[:60]}"],
            )
            per_claim_context = {
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

    outcomes: dict[int, Tuple[Optional[List[SearchResult]], Optional[Exception]]] = {}
    with ThreadPoolExecutor(max_workers=len(candidates)) as executor:
        futures = [executor.submit(_run_claim_query, i, c) for i, c in enumerate(candidates)]
        for future in futures:
            index, results, exc = future.result()
            outcomes[index] = (results, exc)

    # Reassemble in candidate order for a deterministic merge.
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
            new_results.extend(results)

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

    # Merge new results with existing canonical results, deduplicated.
    all_results = list(retrieval_bundle.canonical_results) + new_results
    merged_canonical = merge_search_results(all_results)

    enriched_bundle = replace(
        retrieval_bundle,
        canonical_results=merged_canonical,
        raw_results=tuple(list(retrieval_bundle.raw_results) + new_results),
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
