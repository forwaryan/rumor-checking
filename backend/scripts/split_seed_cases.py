"""Utility to split the aggregated seed cases.json into per-case JSON files.

The eval framework's load_snapshot works on single files; this script splits
the seed corpus so each case lives at seed/<case_id>.json for easy diffing,
per-case iteration, and future additions."""
from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    seed_dir = Path(__file__).resolve().parents[2] / "evals" / "live_replay" / "seed"
    aggregate = seed_dir / "cases.json"
    if not aggregate.exists():
        raise SystemExit(f"aggregate file missing: {aggregate}")
    cases = json.loads(aggregate.read_text(encoding="utf-8"))
    for case in cases:
        path = seed_dir / f"{case['case_id']}.json"
        path.write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {path.name}")
    print(f"total: {len(cases)}")


if __name__ == "__main__":
    main()
