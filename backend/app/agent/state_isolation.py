"""Copy-on-write state isolation for parallel dispatch.

When multiple tools run concurrently, they must not corrupt each other's view of
AgentState. This module provides:
- `StateSlice`: a copy-on-write wrapper that gives each parallel tool an isolated
  view of the state, with writes going to a private buffer.
- `merge_slices`: a strategy to merge completed slices back into the parent state.
"""
from __future__ import annotations

import copy
from dataclasses import fields
from typing import Any

from backend.app.agent.state import AgentState


# Fields that are safe to merge additively (append/union semantics).
_ADDITIVE_FIELDS: frozenset[str] = frozenset({
    "done_actions",
    "fetched_bodies",
    "fetched_urls",
    "steps",
})

# Fields where only the last-writer-wins (scalar state changes).
_LAST_WRITER_WINS: frozenset[str] = frozenset({
    "last_step_outcome",
    "per_claim_searches",
    "per_claim_iterations",
    "investigation_rounds",
})

# Fields that should never be written by parallel tools.
_IMMUTABLE_DURING_PARALLEL: frozenset[str] = frozenset({
    "request",
    "max_url_fetches",
    "max_per_claim_iterations",
    "max_token_budget",
    "cancelled",
})


class StateSlice:
    """A copy-on-write view of AgentState for isolated parallel execution.

    Reads fall through to the snapshot; writes go to a private delta buffer.
    After execution, the caller merges the delta back into the parent.
    """

    def __init__(self, parent: AgentState):
        self._snapshot = parent
        self._delta: dict[str, Any] = {}
        self._written_fields: set[str] = set()
        self._read_copies: dict[str, Any] = {}

    def get(self, field_name: str) -> Any:
        """Read: return the local override if written, else a defensive copy of the snapshot.

        Mutable types (list, dict, set) are deep-copied on first read to prevent
        accidental mutation of the parent state.
        """
        if field_name in self._delta:
            return self._delta[field_name]
        if field_name in self._read_copies:
            return self._read_copies[field_name]
        value = getattr(self._snapshot, field_name)
        if isinstance(value, (list, dict, set)):
            copied = copy.deepcopy(value)
            self._read_copies[field_name] = copied
            return copied
        return value

    def set(self, field_name: str, value: Any) -> None:
        """Write: store in the private delta."""
        if field_name in _IMMUTABLE_DURING_PARALLEL:
            raise ValueError(f"Cannot write '{field_name}' during parallel execution")
        self._delta[field_name] = value
        self._written_fields.add(field_name)

    @property
    def written_fields(self) -> set[str]:
        return set(self._written_fields)

    def to_state(self) -> AgentState:
        """Materialize a full AgentState with delta applied (for testing/debugging)."""
        kwargs = {}
        for f in fields(AgentState):
            if f.name in self._delta:
                kwargs[f.name] = self._delta[f.name]
            else:
                kwargs[f.name] = copy.deepcopy(getattr(self._snapshot, f.name))
        return AgentState(**kwargs)


def create_slice(state: AgentState) -> StateSlice:
    """Create an isolated slice from the current state."""
    return StateSlice(state)


def merge_slices(parent: AgentState, slices: list[StateSlice]) -> None:
    """Merge completed slices back into the parent state.

    Strategy:
    - Additive fields (done_actions, fetched_bodies, etc.): union/extend
    - Last-writer-wins fields: take from the last slice that wrote them
    - Token usage: sum across all slices (additive by nature)
    - Other fields: last writer wins (arbitrary but deterministic)
    """
    for s in slices:
        for field_name in s.written_fields:
            value = s._delta[field_name]

            if field_name in _IMMUTABLE_DURING_PARALLEL:
                continue

            if field_name == "token_usage":
                # Token usage is always additive
                parent.token_usage.add(
                    prompt=value.prompt_tokens,
                    completion=value.completion_tokens,
                    total=value.total_tokens,
                )
                continue

            if field_name in _ADDITIVE_FIELDS:
                current = getattr(parent, field_name)
                if isinstance(current, list) and isinstance(value, list):
                    # Extend without duplicates for done_actions
                    if field_name == "done_actions":
                        for item in value:
                            if item not in current:
                                current.append(item)
                    else:
                        current.extend(value)
                elif isinstance(current, dict) and isinstance(value, dict):
                    current.update(value)
                elif isinstance(current, set) and isinstance(value, set):
                    current.update(value)
                continue

            # Default: last writer wins
            setattr(parent, field_name, value)
