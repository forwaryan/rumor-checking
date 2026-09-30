from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256

from backend.app.agent.verdict_cache import fingerprint

_fresh_evidence: ContextVar[bool] = ContextVar("fresh_evidence", default=False)
_VERDICT_SETTING_FIELDS = (
    "analysis_provider", "retrieval_provider", "llm_model", "llm_models", "llm_search_model",
    "llm_synthesis_model", "llm_fast_model", "llm_temperature", "llm_max_tokens",
    "llm_query_extraction_enabled", "agent_orchestrator_enabled", "multi_agent_enabled",
    "multi_agent_retrieval_mode", "lightweight_agent_enabled",
    "llm_enabled", "llm_base_url", "llm_model_base_urls", "llm_reasoning_models", "llm_reasoning_max_tokens",
    "llm_reasoning_timeout_seconds", "llm_reasoning_retries", "provider_timeout_seconds",
    "xhs_search_enabled", "toutiao_search_enabled", "sogou_weixin_search_enabled", "piyao_search_enabled",
    "searxng_search_enabled", "searxng_base_url", "retrieval_max_results", "retrieval_timeout_seconds",
    "retrieval_fallback_to_mock", "retrieval_gdelt_base_url", "retrieval_google_news_endpoint",
    "url_fetch_cache_enabled", "url_fetch_max_chars", "url_fetch_max_retries", "url_fetch_timeout_seconds",
    "rendered_fetch_enabled", "evidence_rerank_enabled", "evidence_embed_model", "evidence_rerank_ready",
    "agent_max_extra_rounds", "agent_max_url_fetches", "agent_max_token_budget", "agent_synthesis_critic_enabled",
    "agent_context_max_tokens", "agent_layered_context_enabled", "agent_playbooks_enabled", "version",
)


def requires_fresh_evidence(request_context: dict | None = None) -> bool:
    claims = (request_context or {}).get("review_claim_texts", [])
    return _fresh_evidence.get() or (
        isinstance(claims, list) and any(isinstance(claim, str) and claim.strip() for claim in claims)
    )


@contextmanager
def evidence_cache_policy(request_context: dict):
    token = _fresh_evidence.set(requires_fresh_evidence(request_context))
    try:
        yield
    finally:
        _fresh_evidence.reset(token)


def verdict_cache_fingerprint(request, settings) -> str | None:
    policy = {key: value for key, value in request.request_context.items() if key != "run_id"}
    payload = {
        "version": 2, "input": fingerprint(request.raw_input), "input_type": request.input_type,
        "policy": policy, "settings": {field: getattr(settings, field, None) for field in _VERDICT_SETTING_FIELDS},
    }
    try:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        return None
    return sha256(encoded.encode()).hexdigest()[:32]
