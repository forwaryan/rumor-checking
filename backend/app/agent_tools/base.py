from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class ToolContext:
    """Shared service instances the tools operate through.

    Built from an AnalyzePipeline's own service objects so that anything the
    caller monkeypatches (tests swap pipeline.agent_reasoner, .provider_enricher,
    .retriever, ...) is the exact instance the tools use.
    """

    settings: object
    input_normalizer: object
    retriever: object
    url_content_extractor: object
    question_resolver: object
    agent_reasoner: object
    provider_enricher: object
    claim_extractor: object
    verdict_engine: object
    timeline_builder: object
    report_builder: object
    content_check_builder: object
    pipeline_trace_builder: object
    url_fetch_cache: object | None = None


@dataclass(frozen=True)
class ToolSpec:
    """Self-describing tool metadata for the registry.

    Each tool declares its properties so the runner and LLM planner can reason
    about them without hard-coded knowledge of every tool function."""

    name: str
    description: str
    critical: bool = False
    retries: int = 0
    parallelizable: bool = False


# Global registry populated by the @tool decorator.
_TOOL_REGISTRY: dict[str, tuple[ToolSpec, Callable]] = {}


def tool(
    name: str,
    *,
    description: str = "",
    critical: bool = False,
    retries: int = 0,
    parallelizable: bool = False,
) -> Callable:
    """Decorator that registers a tool function with metadata."""

    def decorator(fn: Callable) -> Callable:
        spec = ToolSpec(
            name=name,
            description=description,
            critical=critical,
            retries=retries,
            parallelizable=parallelizable,
        )
        _TOOL_REGISTRY[name] = (spec, fn)
        fn._tool_spec = spec
        return fn

    return decorator


def get_tool_spec(name: str) -> Optional[ToolSpec]:
    """Look up a tool's metadata by action name."""
    entry = _TOOL_REGISTRY.get(name)
    return entry[0] if entry else None


def get_all_tool_specs() -> list[ToolSpec]:
    """Return all registered tool specs (for LLM planner context)."""
    return [spec for spec, _ in _TOOL_REGISTRY.values()]


# --- Hook system ---


@dataclass
class HookContext:
    """Context passed to pre/post hooks."""

    action: str
    state: Any
    ctx: Any
    outcome: Optional[Any] = None
    error: Optional[Exception] = None


PreHook = Callable[[HookContext], None]
PostHook = Callable[[HookContext], None]


@dataclass
class HookRegistry:
    """Pre/post dispatch hooks for cross-cutting concerns."""

    pre_hooks: list[PreHook] = field(default_factory=list)
    post_hooks: list[PostHook] = field(default_factory=list)

    def add_pre(self, hook: PreHook) -> None:
        self.pre_hooks.append(hook)

    def add_post(self, hook: PostHook) -> None:
        self.post_hooks.append(hook)

    def fire_pre(self, context: HookContext) -> None:
        for hook in self.pre_hooks:
            try:
                hook(context)
            except Exception:
                pass

    def fire_post(self, context: HookContext) -> None:
        for hook in self.post_hooks:
            try:
                hook(context)
            except Exception:
                pass
