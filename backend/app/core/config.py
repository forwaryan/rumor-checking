from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str
    environment: str
    api_v1_prefix: str
    log_level: str
    debug: bool
    version: str
    project_root: Path
    evals_root: Path


@lru_cache()
def get_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[3]
    return Settings(
        app_name=os.getenv("APP_NAME", "rumor-checking-backend"),
        environment=os.getenv("APP_ENV", "development"),
        api_v1_prefix=os.getenv("API_V1_PREFIX", "/api/v1"),
        log_level=os.getenv("APP_LOG_LEVEL", "INFO").upper(),
        debug=_as_bool(os.getenv("APP_DEBUG"), default=False),
        version=os.getenv("APP_VERSION", "0.1.0"),
        project_root=project_root,
        evals_root=project_root / "evals" / "minimal_v1",
    )
