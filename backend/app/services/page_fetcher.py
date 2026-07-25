"""Fetch page content for top search results to provide richer grounding
for claim correction. Never crashes the pipeline — returns {} on any failure."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Dict, List, Optional

import httpx

from backend.app.services.retrieval_models import SearchResult, TIER_WEIGHTS

if TYPE_CHECKING:
    from backend.app.services.url_fetch_cache import UrlFetchCache

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_DIGIT_RE = re.compile(r"\d")
_CHINESE_SEG_RE = re.compile(r"[一-鿿]{20,}")

# Module-level cache reference, set by the pipeline at startup so repeated
# calls within the same request don't re-fetch the same URLs.
_cache: Optional["UrlFetchCache"] = None


def set_page_fetch_cache(cache: Optional["UrlFetchCache"]) -> None:
    """Inject a UrlFetchCache instance so page fetches can be deduplicated."""
    global _cache
    _cache = cache


def _strip_tags(html: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    text = _TAG_RE.sub(" ", html)
    return _WHITESPACE_RE.sub(" ", text).strip()


def _extract_key_paragraphs(text: str, max_chars: int = 800) -> str:
    """Extract the most relevant paragraphs from page text.

    Strategy:
    - Split into paragraphs (segments > 40 chars separated by newlines/double-spaces)
    - Score by: contains digits, contains substantial Chinese text, not too short
    - Return top-2 paragraphs up to max_chars total
    """
    raw_segments = re.split(r"\n\n+|\n", text)
    paragraphs = [seg.strip() for seg in raw_segments if len(seg.strip()) > 40]

    if not paragraphs:
        raw_segments = re.split(r"\s{3,}", text)
        paragraphs = [seg.strip() for seg in raw_segments if len(seg.strip()) > 40]

    if not paragraphs:
        return text[:max_chars]

    def _score(para: str) -> float:
        score = 0.0
        if _DIGIT_RE.search(para):
            score += 3.0
        if _CHINESE_SEG_RE.search(para):
            score += 2.0
        score += min(len(para) / 200.0, 2.0)
        if len(para) < 60:
            score -= 1.0
        return score

    scored = sorted(paragraphs, key=_score, reverse=True)

    selected: list[str] = []
    total = 0
    for para in scored[:2]:
        if total + len(para) > max_chars:
            remaining = max_chars - total
            if remaining > 40:
                selected.append(para[:remaining])
            break
        selected.append(para)
        total += len(para)

    return "\n\n".join(selected) if selected else text[:max_chars]


def _fetch_single_page(url: str) -> Optional[str]:
    """Fetch one page, using the module-level cache when available."""
    # Check cache first
    if _cache is not None:
        try:
            cached = _cache.read(url=url)
            if cached is not None and cached.body:
                return _strip_tags(cached.body)
        except Exception:
            pass

    # Live fetch
    resp = httpx.get(
        url,
        timeout=10.0,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (compatible; RumorCheck/1.0)"},
    )
    if resp.status_code != 200:
        return None
    text = _strip_tags(resp.text)

    # Write to cache for deduplication within same request
    if _cache is not None and text:
        try:
            from backend.app.models.schemas import MockFetchResult
            _cache.write(url=url, result=MockFetchResult(status="ok", body=resp.text))
        except Exception:
            pass

    return text


def fetch_page_snippets(
    results: List[SearchResult],
    max_results: int = 5,
) -> Dict[str, str]:
    """Fetch page body text for the top search results sorted by source tier.

    Returns a dict of {result_id: key_paragraphs} with up to 800 chars per page.
    Silently returns empty dict on any failure (never crashes the pipeline).
    """
    if not results:
        return {}
    real_results = [
        r for r in results
        if r.url
        and r.url.startswith(("http://", "https://"))
        and r.case_id == "real_search"
    ]
    if not real_results:
        return {}

    try:
        sorted_results = sorted(
            real_results,
            key=lambda r: TIER_WEIGHTS.get(r.source_tier, 0),
            reverse=True,
        )
        top = sorted_results[:max_results]

        bodies: Dict[str, str] = {}
        for result in top:
            try:
                text = _fetch_single_page(result.url)
                if text:
                    bodies[result.result_id] = _extract_key_paragraphs(text)
            except Exception:
                continue

        return bodies

    except Exception as exc:
        logger.debug("fetch_page_snippets failed: %s", exc)
        return {}
