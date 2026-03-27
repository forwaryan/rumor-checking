from __future__ import annotations

from fastapi import APIRouter

from backend.app.api.v1.endpoints.analyze import router as analyze_router
from backend.app.api.v1.endpoints.health import router as health_router

router = APIRouter()
router.include_router(health_router, tags=["health"])
router.include_router(analyze_router, tags=["analyze"])
