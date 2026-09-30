"""Content-free retrieval spans using the existing request trace context."""
from __future__ import annotations

import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from backend.app.agent.trace import get_current_trace
from backend.app.services.progress import get_retrieval_stage_key

_PROVIDERS = {"gdelt", "playwright", "kimi", "llm", "llm_web_search", "mock", "off", "skipped",
              "xhs", "xiaohongshu", "toutiao", "sogou_weixin", "piyao"}
_STAGES = {"retrieval_initial", "retrieval_follow_up", "per_claim_retrieval", "agent_retrieval"}
_CACHE_STATUSES = {"hit", "stale_hit", "miss", "bypassed", "not_used", "write_only", "mixed"}


@dataclass
class _Round:
    failures: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


_round: ContextVar[_Round | None] = ContextVar("retrieval_observation_round", default=None)


def bundle_counts(bundle) -> dict:
    return {
        "raw_result_count": len(bundle.raw_results),
        "canonical_result_count": len(bundle.canonical_results),
        "independent_source_count": bundle.independent_source_count,
        "high_trust_source_count": bundle.independent_high_trust_source_count,
        "evidence_grade": bundle.evidence_grade,
        "fallback_used": bundle.fallback_used,
        "cache_status": bundle.cache_status if bundle.cache_status in _CACHE_STATUSES else "other",
        "query_count": len(bundle.query_groups),
    }


@contextmanager
def observe_retrieval(operation: str, *, provider: str | None = None,
                      stage_key: str | None = None, **counts):
    """No input content or exception messages enter these spans.

    An activation boundary restores parent bindings even if an observability
    sink fails. Business exceptions (including cancellation) always propagate.
    Mutable metadata contains only counts and fixed labels supplied here/callers.
    """
    metadata = {"observability_type": "retrieval", "operation": operation,
                "span_kind": "CHAIN" if operation in {"round", "selection"} else "RETRIEVER",
                "status": "ok", **counts}
    if provider is not None:
        metadata["provider"] = provider if isinstance(provider, str) and provider in _PROVIDERS else "other"
    stage_key = stage_key or get_retrieval_stage_key()
    if stage_key is not None:
        metadata["stage_key"] = stage_key if isinstance(stage_key, str) and stage_key in _STAGES else "other"
    round_token = _round.set(_Round()) if operation == "round" else None
    exporter = get_current_trace()
    boundary = None
    span = None
    error_type = None
    try:
        if exporter is not None:
            try:
                boundary = exporter.activate()
                boundary.__enter__()
                span = exporter.begin_span(f"retrieval.{operation}", **metadata)
            except Exception:
                span = None
        try:
            yield metadata
        except BaseException as exc:
            metadata["status"] = "error"
            error_type = type(exc).__name__
            raise
        finally:
            current_round = _round.get()
            if current_round is not None:
                with current_round.lock:
                    if operation != "round" and metadata["status"] in {"error", "unavailable"}:
                        current_round.failures += 1
                    if operation == "round":
                        metadata["failure_count"] = current_round.failures
                        if current_round.failures and metadata["status"] != "error":
                            metadata["status"] = "partial"
            if span is not None:
                try:
                    span.metadata.update(metadata)
                    exporter.end_span(success=metadata["status"] not in {"error", "unavailable"},
                                      error_type=error_type)
                except Exception:
                    pass
    finally:
        if boundary is not None:
            try:
                boundary.__exit__(None, None, None)
            except Exception:
                pass
        if round_token is not None:
            _round.reset(round_token)
