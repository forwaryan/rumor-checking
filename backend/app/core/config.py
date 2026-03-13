from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


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
    analysis_provider: str
    kimi_api_key: str | None
    kimi_base_url: str
    kimi_model: str
    provider_timeout_seconds: float

    @property
    def kimi_enabled(self) -> bool:
        return self.analysis_provider == "kimi" and bool(self.kimi_api_key)


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
        analysis_provider=os.getenv("ANALYSIS_PROVIDER", "off").strip().lower(),
        kimi_api_key=os.getenv("KIMI_API_KEY"),
        kimi_base_url=os.getenv("KIMI_BASE_URL", "https://api.moonshot.cn/v1").rstrip("/"),
        kimi_model=os.getenv("KIMI_MODEL", "moonshot-v1-8k"),
        provider_timeout_seconds=_as_float(os.getenv("PROVIDER_TIMEOUT_SECONDS"), 20.0),
    )
