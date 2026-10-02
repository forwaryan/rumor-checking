from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
from hashlib import sha256
from urllib.parse import urlparse

import httpx

from backend.app.services.evidence_snapshots import capture_evidence_text
from backend.app.services.http_reliability import reliable_get
from backend.app.services.progress import emit_log
from backend.app.services.retrieval_deduper import merge_search_results
from backend.app.services.retrieval_models import MAINSTREAM_HOST_MARKERS, RetrievalBundle, SearchResult
from backend.app.services.run_control import check_run_control
from backend.app.services.url_content_extractor import USER_AGENT, UrlContentExtractor

_LOADED: ContextVar[dict[tuple[str, ...], tuple[list[SearchResult], list[str]]] | None] = ContextVar(
    "supplemental_evidence", default=None,
)


class SupplementalUrlExtractor(UrlContentExtractor):
    def _fetch(self, url: str) -> httpx.Response:
        response = reliable_get(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
                                timeout=self.settings.url_fetch_timeout_seconds, max_retries=0)
        response.raise_for_status()
        return response


def _source_tier(host: str) -> str:
    if host.endswith((".gov.cn", ".gov", ".edu.cn")):
        return "S"
    if any(host == domain or host.endswith(f".{domain}") for domain in MAINSTREAM_HOST_MARKERS):
        return "A"
    return "C"


@contextmanager
def supplemental_evidence_scope() -> Iterator[None]:
    """Fetch the reviewer-supplied links once per request.

    ``merge_supplemental_evidence`` is called from retrieval, synthesis and the
    verdict engine, each of which may run several times in one analysis. Without
    a request-scoped cache every one of those calls would re-fetch up to five
    external pages, so the scope — not the request object — owns the result.
    """
    token = _LOADED.set({})
    try:
        yield
    finally:
        _LOADED.reset(token)


def load_supplemental_evidence(request) -> tuple[list[SearchResult], list[str]]:
    results: list[SearchResult] = []
    failures: list[str] = []
    urls = request.request_context.get("supplemental_urls", [])
    if not isinstance(urls, list):
        urls = []
    unique_urls = list(dict.fromkeys(url.strip() for url in urls if isinstance(url, str) and url.strip()))
    loaded = _LOADED.get()
    if loaded is not None and tuple(unique_urls) in loaded:
        return loaded[tuple(unique_urls)]
    if len(unique_urls) > 5:
        failures.append("补充证据最多读取5个链接，其余链接未读取。")
    extractor = SupplementalUrlExtractor()
    for index, url in enumerate(unique_urls[:5]):
        check_run_control()
        try:
            fetched = extractor.extract(url)
        except Exception:
            fetched = None
        body = (fetched.body or fetched.snippet or "").strip() if fetched else ""
        if not fetched or fetched.status != "ok" or not body:
            failure = f"补充证据链接{index + 1}未能安全读取正文，未作为本轮证据。"
            failures.append(failure)
            emit_log(stage_key="retrieval_initial", title="补充证据未读取", summary=failure,
                     level="warning", details=[f"link_index={index + 1}"])
            continue
        final_url = fetched.final_url or url
        capture_evidence_text(url=final_url, text=body, kind="page_text", acquisition="fetched", extractor="article-v1")
        host = (urlparse(final_url).hostname or "").lower()
        result = SearchResult(
            case_id="supplemental", query=request.raw_input, result_id=f"supp-{sha256(final_url.encode()).hexdigest()[:16]}",
            title=fetched.title or host, url=final_url, source_name=host,
            published_at=fetched.published_at or "", snippet=body,
            source_tier=_source_tier(host), provider_name="supplemental_url",
        )
        results.append(result)
        emit_log(stage_key="retrieval_initial", title="已读取补充证据", summary=f"已读取补充链接{index + 1}的正文。",
                 details=[f"result_id={result.result_id}", f"body_chars={len(body)}"])
    cached = (results, failures)
    if loaded is not None:
        loaded[tuple(unique_urls)] = cached
    return cached


def merge_supplemental_evidence(request, bundle: RetrievalBundle | None) -> RetrievalBundle | None:
    results, _failures = load_supplemental_evidence(request)
    if not results:
        return bundle
    if bundle is not None and bundle.provider_name == "mock":
        bundle = RetrievalBundle(query=bundle.query, provider_name="supplemental_url",
                                 fallback_used=bundle.fallback_used, fallback_reason=bundle.fallback_reason)
    bundle = bundle or RetrievalBundle(query=request.raw_input, provider_name="supplemental_url")
    known = {item.result_id for item in bundle.canonical_results}
    additions = [item for item in results if item.result_id not in known]
    if not additions:
        return bundle
    canonical = merge_search_results([*additions, *bundle.canonical_results])
    return replace(bundle, raw_results=(*bundle.raw_results, *additions), canonical_results=canonical)


def annotate_review_report(request, report):
    from backend.app.services.review_scope import review_claim_items

    _results, failures = load_supplemental_evidence(request)
    selected = review_claim_items(request)
    if not failures and not selected:
        return report
    risks = list(report.risks)
    risks.extend(failure for failure in failures if failure not in risks)
    if selected:
        risks.append("本轮复核范围：" + "；".join(item.claim for item in selected))
    return report.model_copy(update={"risks": risks})
