from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import FastAPI, Request

from backend.app.api.router import router as api_router
from backend.app.core.config import get_settings
from backend.app.core.exceptions import install_exception_handlers
from backend.app.core.logging import configure_logging

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    app = FastAPI(title=settings.app_name, version=settings.version, debug=settings.debug)

    @app.middleware("http")
    async def attach_request_id(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.get("/")
    def root() -> dict:
        return {
            "service": settings.app_name,
            "version": settings.version,
            "docs": "/docs",
            "health": f"{settings.api_v1_prefix}/health",
        }

    install_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    logger.info("application_created env=%s version=%s", settings.environment, settings.version)
    return app


app = create_app()
