from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from hashlib import sha256
from ipaddress import ip_address
from threading import Lock
from urllib.parse import urlsplit

from backend.app.models.schemas import EvidenceItem, EvidenceSnapshot, Report

_MAX_TEXT = 24000
_MAX_CAPTURE_CHARS = 1000000
_MAX_REPORT_CHARS = 120000
_CAPTURE: ContextVar[EvidenceCapture | None] = ContextVar("evidence_capture", default=None)


def _public_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if parsed.scheme not in {"https", "http"} or not host or parsed.username or parsed.password:
            return False
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            return False
        try:
            address = ip_address(host)
        except ValueError:
            return "." in host
        return address.is_global and not address.is_multicast
    except ValueError:
        return False


class EvidenceCapture:
    def __init__(self) -> None:
        self._snapshots: dict[str, EvidenceSnapshot] = {}
        self._chars = 0
        self._lock = Lock()

    def restore(self, report: Report) -> None:
        with self._lock:
            for snapshot in report.evidence_snapshots:
                if snapshot.snapshot_id in self._snapshots:
                    continue
                if not _public_url(snapshot.url) or (snapshot.final_url and not _public_url(snapshot.final_url)):
                    continue
                if len(self._snapshots) >= 128 or self._chars + len(snapshot.text) > _MAX_CAPTURE_CHARS:
                    break
                self._snapshots[snapshot.snapshot_id] = snapshot
                self._chars += len(snapshot.text)

    def record(self, *, url: str, text: str, kind: str, acquisition: str, extractor: str,
               final_url: str | None = None, truncated: bool = False, only_if_missing: bool = False) -> None:
        url = url.strip()
        if not text.strip() or not _public_url(url) or (final_url and not _public_url(final_url)):
            return
        retained = text[:_MAX_TEXT]
        truncated = truncated or len(text) > len(retained)
        digest = sha256(retained.encode()).hexdigest()
        identity = json.dumps([url, final_url, kind, extractor, digest, truncated], separators=(",", ":"))
        snapshot_id = sha256(identity.encode()).hexdigest()
        with self._lock:
            if snapshot_id in self._snapshots:
                return
            if only_if_missing and any(snapshot.url == url and snapshot.kind == kind for snapshot in self._snapshots.values()):
                return
            if len(self._snapshots) >= 128 or self._chars + len(retained) > _MAX_CAPTURE_CHARS:
                return
            self._snapshots[snapshot_id] = EvidenceSnapshot(
                snapshot_id=snapshot_id, url=url, final_url=final_url, kind=kind, text=retained,
                text_sha256=digest, captured_at=datetime.now(UTC).isoformat(), acquisition=acquisition,
                extractor=extractor, truncated=truncated,
            )
            self._chars += len(retained)

    def bind_report(self, report: Report) -> Report:
        with self._lock:
            captured = list(self._snapshots.values())
        cited = [item for claim in report.claim_results for item in claim.evidence] + list(report.sources)
        if not cited and not report.retrieval_hits and not report.evidence_snapshots:
            return report
        selected: dict[str, EvidenceSnapshot] = {}
        chars = 0

        def retain(snapshot: EvidenceSnapshot | None) -> bool:
            nonlocal chars
            if snapshot is None:
                return False
            if snapshot.snapshot_id in selected:
                return True
            if len(selected) >= 24 or chars + len(snapshot.text) > _MAX_REPORT_CHARS:
                return False
            selected[snapshot.snapshot_id] = snapshot
            chars += len(snapshot.text)
            return True

        candidates_by_url = {
            url: sorted((snapshot for snapshot in reversed(captured) if snapshot.url == url),
                        key=lambda snapshot: snapshot.kind != "page_text")
            for url in dict.fromkeys(item.url for item in cited)
        }
        bindings: dict[tuple[str, str | None], EvidenceItem] = {}
        for item in cited:
            candidates = candidates_by_url[item.url]
            quote = item.stance_quote
            matched = next((snapshot for snapshot in candidates if quote and quote in snapshot.text), None)
            preferred = matched or next(iter(candidates), None)
            retained = retain(preferred)
            updates = {"snapshot_id": preferred.snapshot_id if retained else None,
                       "quote_status": "not_provided" if not quote else "unavailable",
                       "quote_start": None, "quote_end": None}
            if quote and retained:
                updates["quote_status"] = "matched" if matched else "unmatched"
                if matched:
                    updates["quote_start"] = matched.text.index(quote)
                    updates["quote_end"] = updates["quote_start"] + len(quote)
            bindings[item.url, quote] = item.model_copy(update=updates)
        for candidates in candidates_by_url.values():
            for snapshot in candidates:
                if snapshot.kind == "page_text":
                    retain(snapshot)

        def bind(item: EvidenceItem) -> EvidenceItem:
            reference = bindings.get((item.url, item.stance_quote))
            if reference is None:
                return item.model_copy(update={"snapshot_id": None, "quote_status": "unavailable" if item.stance_quote else "not_provided",
                                               "quote_start": None, "quote_end": None})
            return item.model_copy(update={key: getattr(reference, key) for key in
                                           ("snapshot_id", "quote_status", "quote_start", "quote_end")})

        return report.model_copy(update={
            "claim_results": [claim.model_copy(update={"evidence": [bind(item) for item in claim.evidence]})
                              for claim in report.claim_results],
            "sources": [bind(item) for item in report.sources],
            "retrieval_hits": [bind(item) for item in report.retrieval_hits],
            "evidence_snapshots": list(selected.values()),
        })


@contextmanager
def evidence_capture():
    capture = EvidenceCapture()
    token = _CAPTURE.set(capture)
    try:
        yield capture
    finally:
        _CAPTURE.reset(token)


def capture_evidence_text(**kwargs) -> None:
    capture = _CAPTURE.get()
    if capture is not None:
        from backend.app.services.run_control import check_run_control
        check_run_control()
        capture.record(**kwargs)


def bind_captured_report(report: Report) -> Report:
    capture = _CAPTURE.get()
    return capture.bind_report(report) if capture is not None else report


def capture_retrieval_bundle(bundle) -> None:
    if _CAPTURE.get() is None or bundle is None:
        return
    for result in bundle.canonical_results:
        if result.case_id == "real_search":
            capture_evidence_text(url=result.url, text=result.snippet, kind="search_snippet",
                                  acquisition="retrieved", extractor="search-snippet-v1")


def restore_captured_evidence(bundle, bodies: dict[str, str], report: Report | None = None) -> None:
    capture = _CAPTURE.get()
    if capture is None:
        return
    if report is not None:
        capture.restore(report)
    capture_retrieval_bundle(bundle)
    if bundle is None:
        return
    for result in bundle.canonical_results:
        body = result.snippet if result.case_id == "supplemental" else bodies.get(result.result_id)
        if body and result.case_id in {"real_search", "supplemental"}:
            capture_evidence_text(url=result.url, text=body, kind="page_text", acquisition="restored",
                                  extractor="article-v1" if result.case_id == "supplemental" else "checkpoint-text-v1",
                                  truncated=result.case_id != "supplemental", only_if_missing=True)
