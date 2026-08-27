"""Inspect retrieval source readiness without making network requests."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.services.source_registry import source_capability_snapshot  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect configured retrieval providers and local prerequisites.",
    )
    parser.add_argument("--json", action="store_true", help="print the machine-readable snapshot")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="fail when any configured source is unavailable",
    )
    return parser


def _format_snapshot(snapshot: dict) -> str:
    summary = snapshot["summary"]
    lines = [
        f"Provider Doctor: {str(summary['status']).upper()}",
        f"Active primary: {summary['active_primary'] or 'none'}",
        (
            "Sources: "
            f"{summary['enabled']} enabled, "
            f"{summary['unavailable']} configured but unavailable"
        ),
        "",
    ]
    for source in snapshot["sources"]:
        if source["enabled"]:
            marker = "ready"
            detail = ", ".join(source["capabilities"])
        elif source["configured"]:
            marker = "missing"
            detail = source["unavailable_reason"] or "runtime prerequisite unavailable"
        else:
            marker = "off"
            detail = source["unavailable_reason"] or "not configured"
        lines.append(f"[{marker:7}] {source['id']:<16} {detail}")
    return "\n".join(lines)


def exit_code(snapshot: dict, *, strict: bool) -> int:
    summary = snapshot["summary"]
    if summary["active_primary"] is None:
        return 1
    if strict and summary["unavailable"] > 0:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    snapshot = source_capability_snapshot()
    if args.json:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    else:
        print(_format_snapshot(snapshot))
    return exit_code(snapshot, strict=args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
