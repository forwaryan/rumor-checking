"""Lightweight evidence reranker for synthesis prompt ordering.

Scores each SearchResult's relevance to the claim/query by combining:
- Chinese character n-gram overlap (unigram + bigram)
- Keyword / entity overlap
- Source tier weight bonus

No external model needed — pure token arithmetic. The synthesis LLM reads
evidence top-to-bottom, so higher-ranked hits get more attention.

When EVIDENCE_RERANK is configured, rank_results instead orders by embedding
cosine similarity (see embedding_ranker) — semantic-dominant, which fixes
shared-word false matches. That path is best-effort: any failure falls back to
the token scorer below, so this module's behavior is never worse than baseline.
"""
from __future__ import annotations

import logging
import re
from collections import Counter

from backend.app.core.config import get_settings
from backend.app.services.retrieval_models import TIER_WEIGHTS, SearchResult

logger = logging.getLogger(__name__)

_CJK_RE = re.compile(r"[一-鿿]+")
_WORD_RE = re.compile(r"[\w一-鿿]{2,}")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def _tokenize_chinese(text: str) -> list[str]:
    """Extract overlapping bigrams from CJK runs + Latin/number words."""
    tokens: list[str] = []
    for segment in _CJK_RE.findall(text):
        for i in range(len(segment)):
            tokens.append(segment[i])
            if i + 1 < len(segment):
                tokens.append(segment[i : i + 2])
    tokens.extend(_WORD_RE.findall(text))
    return tokens


def _extract_numbers(text: str) -> set[str]:
    return set(_NUMBER_RE.findall(text))


def score_result(result: SearchResult, query_text: str, event_title: str = "") -> float:
    """Score a single result's relevance to the query/event context.

    Returns a float ≥ 0; higher = more relevant.
    """
    reference = f"{query_text} {event_title}"
    ref_tokens = Counter(_tokenize_chinese(reference))
    ref_numbers = _extract_numbers(reference)

    hit_text = f"{result.title} {result.snippet}"
    hit_tokens = Counter(_tokenize_chinese(hit_text))
    hit_numbers = _extract_numbers(hit_text)

    if not ref_tokens:
        return 0.0

    # Token overlap (Jaccard-like, weighted by frequency in reference)
    overlap = sum(min(ref_tokens[t], hit_tokens[t]) for t in ref_tokens if t in hit_tokens)
    token_score = overlap / max(sum(ref_tokens.values()), 1)

    # Number match bonus (exact match on key figures is strong signal)
    number_bonus = 0.0
    if ref_numbers:
        matched = ref_numbers & hit_numbers
        number_bonus = len(matched) / len(ref_numbers) * 0.3

    # Authority signal. Prefer the continuous 0–100 authority_score when the
    # provider computed one (0.5 max nudge); fall back to the coarse tier
    # weight so fixtures / historical replays that never set the field still
    # get the traditional tier bump.
    if result.authority_score > 0:
        authority_bonus = result.authority_score * 0.005
    else:
        authority_bonus = TIER_WEIGHTS.get(result.source_tier, 0) * 0.05

    return token_score + number_bonus + authority_bonus


def _rank_by_tokens(
    results: list[SearchResult],
    query_text: str,
    event_title: str,
    limit: int,
) -> list[SearchResult]:
    scored = [(score_result(r, query_text, event_title), r) for r in results]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:limit]]


def rank_results(
    results: list[SearchResult],
    query_text: str,
    event_title: str = "",
    limit: int = 8,
) -> list[SearchResult]:
    """Return results sorted by relevance score, limited to top N.

    Uses semantic embedding reranking when configured (EVIDENCE_RERANK_ENABLED +
    model + key), else the token-overlap scorer. The semantic path is best-effort:
    any failure logs a warning and falls back to tokens, so output is never worse
    than the token baseline."""
    if get_settings().evidence_rerank_ready:
        try:
            from backend.app.services.embedding_ranker import rank_by_embedding

            return rank_by_embedding(
                results, query_text=query_text, event_title=event_title, limit=limit
            )
        except Exception as exc:  # noqa: BLE001 — any failure must fall back, never raise
            logger.warning(
                "semantic rerank failed (%s: %s); falling back to token scorer",
                type(exc).__name__,
                exc,
            )
    return _rank_by_tokens(results, query_text, event_title, limit)
