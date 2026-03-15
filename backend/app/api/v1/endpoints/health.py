from __future__ import annotations

from fastapi import APIRouter

from backend.app.core.config import get_settings

router = APIRouter()


@router.get("/health")
def health_check() -> dict:
    settings = get_settings()
    if not settings.kimi_ready:
        return {
            "status": "degraded",
            "detail": "Kimi is not configured. Analyze requests will fail until KIMI_API_KEY is available.",
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
