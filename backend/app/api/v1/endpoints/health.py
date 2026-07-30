from __future__ import annotations

from fastapi import APIRouter

from backend.app.core.config import get_settings
from backend.app.services.model_health import get_model_health_registry

router = APIRouter()


@router.get("/health")
def health_check() -> dict:
    settings = get_settings()
    if not settings.llm_ready:
        return {
            "status": "degraded",
            "detail": (
                "LLM-backed analysis or retrieval is selected, "
                "but LLM_API_KEY is not configured."
            ),
            "service": settings.app_name,
            "environment": settings.environment,
            "version": settings.version,
        }
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.environment,
        "version": settings.version,
    }


@router.get("/models")
def list_models() -> dict:
    """Selectable analysis models (config-driven whitelist) + the default, so the
    frontend can offer a picker. Only names from LLM_MODELS/LLM_MODEL are exposed;
    the gateway endpoint and key are never returned."""
    settings = get_settings()
    return {
        "models": list(settings.available_models),
        "default": settings.llm_model,
    }


@router.get("/model-health")
def model_health_snapshot() -> dict:
    """Process-wide LLM model health, exposed for ops. Returns per-model lifetime
    counters (failures/successes/evictions) plus current health. Ops-only:

    - Never exposes the gateway host or the API key; only the model names that
      the whitelist would already reveal via /models.
    - A never-touched model is absent (fresh models start healthy by default),
      so the empty state is the correct "everything is fine" signal.
    - State is process-local and resets when the worker restarts — this is
      intentional (see model_health.py) and worth surfacing to whoever reads
      the dashboard so they aren't confused by post-restart empties.
    """
    return {
        "models": get_model_health_registry().snapshot(),
    }


@router.get("/search-sources")
def list_search_sources() -> dict:
    """Available search sources and their enabled state."""
    settings = get_settings()
    from shutil import which

    sources = [
        {
            "id": "baidu",
            "label": "百度",
            "description": "百度搜索引擎（主力源）",
            "enabled": settings.retrieval_provider == "playwright",
            "default_on": True,
        },
        {
            "id": "xiaohongshu",
            "label": "小红书",
            "description": "小红书社交笔记",
            "enabled": settings.xhs_search_enabled and which("xhs") is not None,
            "default_on": True,
        },
        {
            "id": "toutiao",
            "label": "今日头条",
            "description": "头条搜索（聚合辟谣/媒体）",
            "enabled": settings.toutiao_search_enabled,
            "default_on": True,
        },
        {
            "id": "sogou_weixin",
            "label": "微信公众号",
            "description": "搜狗微信（辟谣公众号：腾讯较真、科普中国等）",
            "enabled": settings.sogou_weixin_search_enabled,
            "default_on": True,
        },
    ]
    return {"sources": sources}
