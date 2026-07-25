"""Fetch page content for top search results to provide richer grounding
for claim correction. Never crashes the pipeline — returns {} on any failure."""

from __future__ import annotations

import logging
import re
from typing import Dict, List

import httpx

from backend.app.services.retrieval_models import SearchResult, TIER_WEIGHTS

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_tags(html: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    text = _TAG_RE.sub(" ", html)
    return _WHITESPACE_RE.sub(" ", text).strip()


def fetch_page_snippets(
    results: List[SearchResult],
    max_results: int = 3,
) -> Dict[str, str]:
    """Fetch page body text for the top search results sorted by source tier.

    Returns a dict of {result_id: extracted_text} with at most 500 chars per page.
    Silently returns empty dict on any failure (never crashes the pipeline).
    """
    if not results:
        return {}
    # Only fetch pages for real search results (not mock/test data)
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
                resp = httpx.get(
                    result.url,
                    timeout=10.0,
                    follow_redirects=True,
                    headers={
                        "User-Agent": "Mozilla/5.0 (compatible; RumorCheck/1.0)",
                    },
                )
                if resp.status_code != 200:
                    continue
                text = _strip_tags(resp.text)
                if text:
                    bodies[result.result_id] = text[:500]
            except Exception:
                # Silently skip individual page failures
                continue

        return bodies

    except Exception as exc:
        logger.debug("fetch_page_snippets failed: %s", exc)
        return {}
