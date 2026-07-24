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


def _parse_model_base_urls(value: str | None) -> dict[str, str]:
    """Parse per-model base-URL overrides from a `model=url,model2=url2` string.

    Most models share the global LLM_BASE_URL, but some live on a different gateway
    path (e.g. a model only served under /v2). Entries here override the default for
    the named model only. Malformed entries (no `=`, blank name/url) are skipped."""
    overrides: dict[str, str] = {}
    if not value:
        return overrides
    for entry in value.split(","):
        name, sep, url = entry.partition("=")
        name, url = name.strip(), url.strip()
        if sep and name and url:
            overrides[name] = url.rstrip("/")
    return overrides


def _normalize_retrieval_provider(value: str | None, default: str = "mock") -> str:
    normalized = (value or default).strip().lower()
    if normalized == "agent":
        return "kimi"
    return normalized


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
    lightweight_agent_enabled: bool
    agent_max_extra_rounds: int
    agent_orchestrator_enabled: bool
    agent_max_url_fetches: int
    llm_api_key: str | None
    llm_base_url: str
    llm_model_base_urls: dict[str, str]
    llm_model: str
    llm_search_model: str
    llm_models: tuple[str, ...]
    llm_temperature: float
    llm_max_tokens: int
    llm_reasoning_models: tuple[str, ...]
    llm_reasoning_max_tokens: int
    llm_reasoning_timeout_seconds: float
    llm_reasoning_retries: int
    llm_synthesis_timeout_multiplier: float
    llm_query_extraction_enabled: bool
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
    url_fetch_cache_enabled: bool
    url_fetch_cache_dir: Path
    url_fetch_cache_ttl_seconds: float
    cors_allow_origin_regex: str

    @property
    def llm_enabled(self) -> bool:
        return self.analysis_provider == "kimi" and bool(self.llm_api_key)

    @property
    def available_models(self) -> tuple[str, ...]:
        """Whitelist of selectable models; always includes the default."""
        models = list(self.llm_models)
        if self.llm_model and self.llm_model not in models:
            models.insert(0, self.llm_model)
        return tuple(models)

    def resolve_model(self, requested: str | None) -> str:
        """Return the requested model only if it is in the whitelist; otherwise
        fall back to the configured default. Prevents a client from pointing the
        gateway at an arbitrary model name."""
        if requested:
            candidate = requested.strip()
            if candidate and candidate in self.available_models:
                return candidate
        return self.llm_model.strip()

    def base_url_for_model(self, model: str) -> str:
        """Gateway base URL for a model: its per-model override if declared, else
        the global default. Lets a model served on a different path (e.g. /v2)
        coexist with the rest without a second global setting."""
        return self.llm_model_base_urls.get(model.strip(), self.llm_base_url)

    def is_reasoning_model(self, model: str) -> bool:
        """Whether a model is a reasoning model (emits a chain-of-thought before its
        answer). These need a large token budget and a long timeout — the CoT can
        run 2+ minutes before the first answer token — and must NOT be pinned to
        response_format=json_object, which makes some of them stall indefinitely.
        Declared via LLM_REASONING_MODELS (.env, never committed) rather than
        pattern-matched on the name, so a rename never silently flips the path."""
        return bool(model) and model.strip() in self.llm_reasoning_models

    @property
    def lightweight_agent_ready(self) -> bool:
        return self.lightweight_agent_enabled and self.agent_max_extra_rounds > 0 and self.llm_enabled

    @property
    def uses_agent_retrieval(self) -> bool:
        return self.retrieval_provider == "kimi"

    @property
    def llm_ready(self) -> bool:
        return not self.llm_required or bool(self.llm_api_key)

    @property
    def llm_required(self) -> bool:
        return self.analysis_provider == "kimi" or self.uses_agent_retrieval


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
        lightweight_agent_enabled=_as_bool(os.getenv("LIGHTWEIGHT_AGENT_ENABLED"), default=False),
        agent_max_extra_rounds=max(_as_int(os.getenv("AGENT_MAX_EXTRA_ROUNDS"), 1), 0),
        agent_orchestrator_enabled=_as_bool(os.getenv("AGENT_ORCHESTRATOR_ENABLED"), default=False),
        agent_max_url_fetches=max(_as_int(os.getenv("AGENT_MAX_URL_FETCHES"), 1), 0),
        llm_api_key=os.getenv("LLM_API_KEY") or os.getenv("KIMI_API_KEY"),
        llm_base_url=(os.getenv("LLM_BASE_URL") or os.getenv("KIMI_BASE_URL") or "https://api.openai.com/v1").rstrip("/"),
        llm_model_base_urls=_parse_model_base_urls(os.getenv("LLM_MODEL_BASE_URLS")),
        llm_model=(os.getenv("LLM_MODEL") or os.getenv("KIMI_MODEL") or "").strip(),
        llm_search_model=(os.getenv("LLM_SEARCH_MODEL") or os.getenv("KIMI_SEARCH_MODEL") or "").strip(),
        llm_models=tuple(
            m.strip() for m in (os.getenv("LLM_MODELS") or "").split(",") if m.strip()
        ),
        llm_temperature=_as_float(os.getenv("LLM_TEMPERATURE") or os.getenv("KIMI_TEMPERATURE"), 0.1),
        llm_max_tokens=max(_as_int(os.getenv("LLM_MAX_TOKENS"), 4096), 256),
        llm_reasoning_models=tuple(
            m.strip() for m in (os.getenv("LLM_REASONING_MODELS") or "").split(",") if m.strip()
        ),
        llm_reasoning_max_tokens=max(_as_int(os.getenv("LLM_REASONING_MAX_TOKENS"), 16000), 2048),
        llm_reasoning_timeout_seconds=_as_float(os.getenv("LLM_REASONING_TIMEOUT_SECONDS"), 200.0),
        llm_reasoning_retries=max(_as_int(os.getenv("LLM_REASONING_RETRIES"), 2), 0),
        llm_synthesis_timeout_multiplier=max(_as_float(os.getenv("LLM_SYNTHESIS_TIMEOUT_MULTIPLIER"), 1.5), 1.0),
        llm_query_extraction_enabled=_as_bool(os.getenv("LLM_QUERY_EXTRACTION_ENABLED"), default=False),
        provider_timeout_seconds=_as_float(os.getenv("PROVIDER_TIMEOUT_SECONDS"), 20.0),
        retrieval_provider=_normalize_retrieval_provider(os.getenv("RETRIEVAL_PROVIDER"), default="mock"),
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
        url_fetch_cache_enabled=_as_bool(os.getenv("URL_FETCH_CACHE_ENABLED"), default=True),
        url_fetch_cache_dir=Path(os.getenv("URL_FETCH_CACHE_DIR", str(project_root / "data" / "cache" / "url_fetch"))),
        url_fetch_cache_ttl_seconds=_as_float(os.getenv("URL_FETCH_CACHE_TTL_SECONDS"), 43200.0),
        cors_allow_origin_regex=os.getenv(
            "CORS_ALLOW_ORIGIN_REGEX",
            r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        ),
    )




