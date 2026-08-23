"""Fail when public contract field names drift across backend and frontend."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.models.schemas import (  # noqa: E402
    ClaimResult,
    Event,
    EvidenceItem,
    Report,
    TimelineNode,
)

type ModelType = type[BaseModel]

CONTRACTS: dict[str, tuple[str, ModelType, str]] = {
    "event.schema.json": ("Event", Event, "Event"),
    "timeline_node.schema.json": ("TimelineNode", TimelineNode, "TimelineNode"),
    "evidence.schema.json": ("Evidence", EvidenceItem, "Evidence"),
    "claim_result.schema.json": ("ClaimResult", ClaimResult, "ClaimResult"),
    "report.schema.json": ("Report", Report, "Report"),
}


def _typescript_fields(source: str, interface_name: str) -> set[str]:
    match = re.search(
        rf"^export interface {re.escape(interface_name)}\s*\{{(?P<body>.*?)^\}}",
        source,
        flags=re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise ValueError(f"TypeScript interface not found: {interface_name}")
    return set(re.findall(r"^\s*([A-Za-z_]\w*)\??\s*:", match.group("body"), re.MULTILINE))


def find_contract_drift() -> list[str]:
    contracts_dir = REPO_ROOT / "contracts"
    typescript = (REPO_ROOT / "frontend" / "types" / "report.ts").read_text(encoding="utf-8")
    failures: list[str] = []

    for filename, (schema_title, model, interface_name) in CONTRACTS.items():
        payload = json.loads((contracts_dir / filename).read_text(encoding="utf-8"))
        if payload.get("title") != schema_title:
            failures.append(f"{filename}: title must be {schema_title!r}")

        schema_fields = set(payload.get("properties", {}))
        backend_fields = set(model.model_fields)
        frontend_fields = _typescript_fields(typescript, interface_name)

        if schema_fields != backend_fields:
            failures.append(
                f"{filename}: backend drift "
                f"missing={sorted(backend_fields - schema_fields)} "
                f"extra={sorted(schema_fields - backend_fields)}"
            )
        if schema_fields != frontend_fields:
            failures.append(
                f"{filename}: frontend drift "
                f"missing={sorted(frontend_fields - schema_fields)} "
                f"extra={sorted(schema_fields - frontend_fields)}"
            )

    return failures


def main() -> int:
    failures = find_contract_drift()
    if failures:
        print("Contract drift detected:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(f"Contract fields aligned: {len(CONTRACTS)} public models")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
