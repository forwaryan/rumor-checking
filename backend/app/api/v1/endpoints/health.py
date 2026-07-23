from __future__ import annotations

from fastapi import APIRouter

from backend.app.core.config import get_settings

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
