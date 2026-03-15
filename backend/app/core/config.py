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


def _as_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value

    return values


def _load_env_defaults(project_root: Path) -> None:
    merged_values: dict[str, str] = {}
    for candidate in (project_root / ".env", project_root / "backend" / ".env"):
        merged_values.update(_read_env_file(candidate))

    for key, value in merged_values.items():
        os.environ.setdefault(key, value)


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
    kimi_search_model: str
    kimi_temperature: float
    provider_timeout_seconds: float
    retrieval_provider: str
    retrieval_timeout_seconds: float
    retrieval_max_results: int
    retrieval_cache_enabled: bool
    retrieval_cache_dir: Path
    retrieval_cache_ttl_seconds: float
    retrieval_cache_allow_stale_on_error: bool
    retrieval_fallback_to_mock: bool
    retrieval_gdelt_base_url: str
    retrieval_google_news_endpoint: str
    url_fetch_timeout_seconds: float
    url_fetch_max_chars: int
    cors_allow_origin_regex: str

    @property
    def kimi_enabled(self) -> bool:
        return self.analysis_provider == "kimi" and bool(self.kimi_api_key)

    @property
    def kimi_ready(self) -> bool:
        return not self.kimi_required or bool(self.kimi_api_key)

    @property
    def kimi_required(self) -> bool:
        return self.analysis_provider == "kimi" or self.retrieval_provider == "kimi"


@lru_cache()
def get_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[3]
    _load_env_defaults(project_root)
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
        kimi_model=os.getenv("KIMI_MODEL", "moonshot-v1-8k").strip(),
        kimi_search_model=os.getenv("KIMI_SEARCH_MODEL", os.getenv("KIMI_MODEL", "kimi-k2-turbo-preview")).strip(),
        kimi_temperature=_as_float(os.getenv("KIMI_TEMPERATURE"), 0.1),
        provider_timeout_seconds=_as_float(os.getenv("PROVIDER_TIMEOUT_SECONDS"), 20.0),
        retrieval_provider=os.getenv("RETRIEVAL_PROVIDER", "mock").strip().lower(),
        retrieval_timeout_seconds=_as_float(os.getenv("RETRIEVAL_TIMEOUT_SECONDS"), 12.0),
        retrieval_max_results=max(_as_int(os.getenv("RETRIEVAL_MAX_RESULTS"), 8), 1),
        retrieval_cache_enabled=_as_bool(os.getenv("RETRIEVAL_CACHE_ENABLED"), default=True),
        retrieval_cache_dir=Path(os.getenv("RETRIEVAL_CACHE_DIR", str(project_root / "data" / "cache" / "retrieval"))),
        retrieval_cache_ttl_seconds=_as_float(os.getenv("RETRIEVAL_CACHE_TTL_SECONDS"), 43200.0),
        retrieval_cache_allow_stale_on_error=_as_bool(os.getenv("RETRIEVAL_CACHE_ALLOW_STALE_ON_ERROR"), default=True),
        retrieval_fallback_to_mock=_as_bool(os.getenv("RETRIEVAL_FALLBACK_TO_MOCK"), default=True),
        retrieval_gdelt_base_url=os.getenv(
            "RETRIEVAL_GDELT_BASE_URL",
            "https://api.gdeltproject.org/api/v2/doc/doc",
        ),
        retrieval_google_news_endpoint=os.getenv(
            "RETRIEVAL_GOOGLE_NEWS_ENDPOINT",
            "https://news.google.com/rss/search?q={query}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        ),
        url_fetch_timeout_seconds=_as_float(os.getenv("URL_FETCH_TIMEOUT_SECONDS"), 8.0),
        url_fetch_max_chars=max(_as_int(os.getenv("URL_FETCH_MAX_CHARS"), 12000), 1000),
        cors_allow_origin_regex=os.getenv(
            "CORS_ALLOW_ORIGIN_REGEX",
            r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        ),
    )




