from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


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
    requires_permission: bool = False


# Global registry populated by the @tool decorator.
_TOOL_REGISTRY: dict[str, tuple[ToolSpec, Callable]] = {}


def tool(
    name: str,
    *,
    description: str = "",
    critical: bool = False,
    retries: int = 0,
    parallelizable: bool = False,
    requires_permission: bool = False,
) -> Callable:
    """Decorator that registers a tool function with metadata."""

    def decorator(fn: Callable) -> Callable:
        spec = ToolSpec(
            name=name,
            description=description,
            critical=critical,
            retries=retries,
            parallelizable=parallelizable,
            requires_permission=requires_permission,
        )
        _TOOL_REGISTRY[name] = (spec, fn)
        fn._tool_spec = spec
        return fn

    return decorator


def get_tool_spec(name: str) -> ToolSpec | None:
    """Look up a tool's metadata by action name."""
    entry = _TOOL_REGISTRY.get(name)
    return entry[0] if entry else None


def get_tool_fn(name: str) -> Callable | None:
    """Look up a tool's callable by action name."""
    entry = _TOOL_REGISTRY.get(name)
    return entry[1] if entry else None


def get_all_tool_specs() -> list[ToolSpec]:
    """Return all registered tool specs (for LLM planner context)."""
    return [spec for spec, _ in _TOOL_REGISTRY.values()]


# --- Permission system ---


PermissionCallback = Callable[[str, ToolSpec], bool]


class PermissionGate:
    """Gates tool execution on first-use permission.

    When a tool has `requires_permission=True`, the first time it's dispatched
    in a run the gate checks with the registered callback. If denied, the tool
    is skipped. Once approved, it's remembered for the rest of the run.
    """

    def __init__(self, callback: PermissionCallback | None = None):
        self._callback = callback
        self._approved: set[str] = set()
        self._denied: set[str] = set()
        self._lock = threading.Lock()

    def check(self, spec: ToolSpec) -> bool:
        """Returns True if the tool is allowed to execute."""
        if not spec.requires_permission:
            return True
        with self._lock:
            if spec.name in self._approved:
                return True
            if spec.name in self._denied:
                return False
            if self._callback is None:
                return True
            try:
                allowed = self._callback(spec.name, spec)
            except Exception:
                allowed = True
            if allowed:
                self._approved.add(spec.name)
            else:
                self._denied.add(spec.name)
            return allowed

    def reset(self) -> None:
        with self._lock:
            self._approved.clear()
            self._denied.clear()


@dataclass
class HookContext:
    """Context passed to pre/post hooks."""

    action: str
    state: Any
    ctx: Any
    outcome: Any | None = None
    error: Exception | None = None


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
