"""Semantic evidence reranker backed by a gateway embedding model.

Orders SearchResults by embedding cosine similarity to the claim/query, with a
small authority_score nudge so genuine near-ties break toward higher-trust
sources. This is the semantic upgrade to evidence_ranker's token-overlap scorer:
it compares *meaning* rather than shared characters, which stops a story that
merely shares a word (e.g. a common verb or a city name) from ranking as if it
were on-topic.

Every public entry point RAISES on any failure (unconfigured, HTTP error,
timeout, malformed response, dimension mismatch). The caller in evidence_ranker
catches and falls back to the token scorer, so a flaky embedding gateway can
never degrade output below the previous baseline.
"""
from __future__ import annotations

import math

import httpx

from backend.app.core.config import Settings, get_settings
from backend.app.services.retrieval_models import SearchResult

# Additive authority term: authority_score is 0–100, so this maxes at +0.1.
# Cosine similarities from the embedding model cluster roughly in 0.3–0.9, and
# on-topic vs off-topic gaps observed are ~0.3. Capping the nudge at 0.1 keeps
# ranking semantic-dominant — authority can only reorder results whose semantic
# scores are within 0.1 of each other, i.e. real near-ties.
_AUTHORITY_NUDGE = 0.001

# Embeddings are a single fast forward pass; no need for the long reasoning-model
# budget. Keep it short so a stalled gateway trips fallback quickly.
_EMBED_TIMEOUT = httpx.Timeout(15.0, connect=5.0)

_SHARED_HTTPX_CLIENT: httpx.Client | None = None


def _get_shared_client() -> httpx.Client:
    global _SHARED_HTTPX_CLIENT
    if _SHARED_HTTPX_CLIENT is None:
        _SHARED_HTTPX_CLIENT = httpx.Client()
    return _SHARED_HTTPX_CLIENT


def _embed(texts: list[str], settings: Settings) -> list[list[float]]:
    """Call the gateway /embeddings endpoint for a batch of texts.

    Returns vectors in the same order as `texts`. Raises on any transport,
    status, or shape problem."""
    if not settings.evidence_embed_api_key:
        raise RuntimeError("embedding api key not configured")
    model = settings.evidence_embed_model
    base_url = settings.base_url_for_model(model)
    response = _get_shared_client().post(
        f"{base_url}/embeddings",
        headers={
            "Authorization": f"Bearer {settings.evidence_embed_api_key}",
            "Content-Type": "application/json",
        },
        json={"model": model, "input": texts},
        timeout=_EMBED_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("data")
    if not isinstance(rows, list) or len(rows) != len(texts):
        raise ValueError(
            f"embedding response returned {len(rows) if isinstance(rows, list) else 'no'} "
            f"vectors for {len(texts)} inputs"
        )
    # OpenAI-compatible responses carry an explicit index; sort by it rather than
    # trusting positional order, then drop back to a plain list.
    ordered = sorted(rows, key=lambda r: r.get("index", 0))
    vectors = [r.get("embedding") for r in ordered]
    if any(not isinstance(v, list) or not v for v in vectors):
        raise ValueError("embedding response missing vector data")
    return vectors


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise ValueError("cosine on vectors of unequal length")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def semantic_score(
    result_vector: list[float],
    query_vector: list[float],
    authority_score: float,
) -> float:
    """Combine semantic similarity (dominant) with a small authority nudge."""
    return _cosine(result_vector, query_vector) + authority_score * _AUTHORITY_NUDGE


def rank_by_embedding(
    results: list[SearchResult],
    query_text: str,
    event_title: str = "",
    limit: int = 8,
    settings: Settings | None = None,
) -> list[SearchResult]:
    """Return results ordered by semantic relevance to the query, top `limit`.

    Embeds the query and every result in ONE batch call. Raises on any failure;
    evidence_ranker.rank_results is responsible for catching and falling back."""
    settings = settings or get_settings()
    if not results:
        return []

    reference = f"{query_text} {event_title}".strip()
    texts = [reference] + [f"{r.title} {r.snippet}" for r in results]
    vectors = _embed(texts, settings)
    query_vector, result_vectors = vectors[0], vectors[1:]

    scored = [
        (semantic_score(vec, query_vector, r.authority_score), r)
        for vec, r in zip(result_vectors, results, strict=True)
    ]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:limit]]
