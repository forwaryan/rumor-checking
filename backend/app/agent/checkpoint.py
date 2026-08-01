"""Checkpoint / Resume support for the agent runner.

After each successful dispatch step, the runner can snapshot AgentState into a
CheckpointStore. On resume (e.g. after timeout, crash, or SSE disconnect), the
runner rebuilds state from the last checkpoint and re-enters the loop from the
next planned action — skipping all steps that already completed.

Serialization strategy:
- Pydantic models: model_dump(mode="python") → model_validate()
- Dataclasses: dataclasses.asdict() → constructor(**dict)
- Primitives/containers: stored directly

The store is pluggable: in-memory (default, for tests / single-process) or
disk-backed (for durability across process restarts).
"""
from __future__ import annotations

import dataclasses
import json
import logging
import time
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any, Protocol

from backend.app.agent.state import AgentState

logger = logging.getLogger(__name__)


# --- Serialization helpers ---


def _is_pydantic(obj: Any) -> bool:
    return hasattr(obj, "model_dump") and hasattr(obj, "model_validate")


def _serialize_value(value: Any) -> Any:
    """Recursively serialize a value for JSON storage."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        serialized = [_serialize_value(v) for v in value]
        if isinstance(value, tuple):
            return {"__tuple__": True, "items": serialized}
        return serialized
    if isinstance(value, set):
        return {"__set__": True, "items": [_serialize_value(v) for v in value]}
    if isinstance(value, frozenset):
        return {"__frozenset__": True, "items": [_serialize_value(v) for v in value]}
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    if _is_pydantic(value):
        return {
            "__pydantic__": type(value).__module__ + "." + type(value).__qualname__,
            "data": value.model_dump(mode="python"),
        }
    if is_dataclass(value) and not isinstance(value, type):
        return {
            "__dataclass__": type(value).__module__ + "." + type(value).__qualname__,
            "data": {f.name: _serialize_value(getattr(value, f.name)) for f in fields(value)},
        }
    return str(value)


def _deserialize_value(raw: Any) -> Any:
    """Recursively deserialize from JSON-compatible form."""
    if raw is None:
        return None
    if isinstance(raw, (str, int, float, bool)):
        return raw
    if isinstance(raw, list):
        return [_deserialize_value(v) for v in raw]
    if isinstance(raw, dict):
        if raw.get("__tuple__"):
            return tuple(_deserialize_value(v) for v in raw["items"])
        if raw.get("__set__"):
            return set(_deserialize_value(v) for v in raw["items"])
        if raw.get("__frozenset__"):
            return frozenset(_deserialize_value(v) for v in raw["items"])
        if "__pydantic__" in raw:
            cls = _resolve_class(raw["__pydantic__"])
            if cls is not None:
                return cls.model_validate(raw["data"])
            return raw["data"]
        if "__dataclass__" in raw:
            cls = _resolve_class(raw["__dataclass__"])
            if cls is not None:
                deserialized_fields = {k: _deserialize_value(v) for k, v in raw["data"].items()}
                return cls(**deserialized_fields)
            return raw["data"]
        return {k: _deserialize_value(v) for k, v in raw.items()}
    return raw


def _resolve_class(qualified_name: str) -> Any:
    """Import and return a class from its qualified module.ClassName path.

    Handles nested classes (Outer.Inner) by trying progressively shorter module
    paths until the import succeeds, then traversing attributes for the rest.
    """
    try:
        import importlib
        parts = qualified_name.split(".")
        # Try importing progressively longer module paths
        for i in range(len(parts) - 1, 0, -1):
            module_path = ".".join(parts[:i])
            try:
                module = importlib.import_module(module_path)
                obj = module
                for attr in parts[i:]:
                    obj = getattr(obj, attr)
                return obj
            except (ImportError, AttributeError):
                continue
        return None
    except Exception:
        return None


# --- Checkpoint data ---


@dataclasses.dataclass(frozen=True)
class Checkpoint:
    """A frozen snapshot of AgentState at a particular step."""

    step_index: int
    action: str
    timestamp: float
    state_data: dict[str, Any]

    def to_json(self) -> str:
        return json.dumps(
            {"step_index": self.step_index, "action": self.action,
             "timestamp": self.timestamp, "state_data": self.state_data},
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, raw: str) -> Checkpoint:
        data = json.loads(raw)
        return cls(
            step_index=data["step_index"],
            action=data["action"],
            timestamp=data["timestamp"],
            state_data=data["state_data"],
        )


# --- Store protocol and implementations ---


class CheckpointStore(Protocol):
    def save(self, run_id: str, checkpoint: Checkpoint) -> None:
        ...

    def latest(self, run_id: str) -> Checkpoint | None:
        ...

    def all_checkpoints(self, run_id: str) -> list[Checkpoint]:
        ...

    def clear(self, run_id: str) -> None:
        ...


class MemoryCheckpointStore:
    """In-memory store — fast, suitable for tests and single-request lifetime."""

    def __init__(self) -> None:
        self._store: dict[str, list[Checkpoint]] = {}

    def save(self, run_id: str, checkpoint: Checkpoint) -> None:
        self._store.setdefault(run_id, []).append(checkpoint)

    def latest(self, run_id: str) -> Checkpoint | None:
        checkpoints = self._store.get(run_id)
        return checkpoints[-1] if checkpoints else None

    def all_checkpoints(self, run_id: str) -> list[Checkpoint]:
        return list(self._store.get(run_id, []))

    def clear(self, run_id: str) -> None:
        self._store.pop(run_id, None)


class DiskCheckpointStore:
    """File-backed store — survives process restarts. One JSON file per checkpoint."""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir

    def _run_dir(self, run_id: str) -> Path:
        import re
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", run_id)
        return self._base_dir / safe_id

    def save(self, run_id: str, checkpoint: Checkpoint) -> None:
        run_dir = self._run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{checkpoint.step_index:04d}_{checkpoint.action}.json"
        (run_dir / filename).write_text(checkpoint.to_json(), encoding="utf-8")

    def latest(self, run_id: str) -> Checkpoint | None:
        all_cp = self.all_checkpoints(run_id)
        return all_cp[-1] if all_cp else None

    def all_checkpoints(self, run_id: str) -> list[Checkpoint]:
        run_dir = self._run_dir(run_id)
        if not run_dir.exists():
            return []
        checkpoints = []
        for path in sorted(run_dir.glob("*.json")):
            try:
                checkpoints.append(Checkpoint.from_json(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, KeyError):
                logger.warning("checkpoint_corrupted path=%s", path)
        return checkpoints

    def clear(self, run_id: str) -> None:
        run_dir = self._run_dir(run_id)
        if run_dir.exists():
            for path in run_dir.glob("*.json"):
                path.unlink(missing_ok=True)
            try:
                run_dir.rmdir()
            except OSError:
                pass


# --- Snapshot / Restore logic ---


def snapshot_state(state: AgentState, action: str, step_index: int) -> Checkpoint:
    """Create a checkpoint from current AgentState."""
    state_data = {}
    for f in fields(AgentState):
        value = getattr(state, f.name)
        state_data[f.name] = _serialize_value(value)
    return Checkpoint(
        step_index=step_index,
        action=action,
        timestamp=time.time(),
        state_data=state_data,
    )


def restore_state(checkpoint: Checkpoint) -> AgentState:
    """Rebuild AgentState from a checkpoint's serialized data."""
    kwargs: dict[str, Any] = {}
    for f in fields(AgentState):
        if f.name in checkpoint.state_data:
            kwargs[f.name] = _deserialize_value(checkpoint.state_data[f.name])
    return AgentState(**kwargs)
