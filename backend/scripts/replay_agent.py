from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.services.agent_replay import replay_directory  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Strictly offline scripted deep-Agent replay")
    parser.add_argument("--dir", type=Path, default=ROOT / "evals" / "agent_replay")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true", help="Print the full deterministic result")
    args = parser.parse_args()
    try:
        result = replay_directory(args.dir)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        result = {"passed": False, "error": type(exc).__name__}
    serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    if args.json:
        print(serialized, end="")
    else:
        print(f"Agent replay: {result.get('passed_count', 0)}/{result.get('case_count', 0)} passed")
        for case in result.get("cases", []):
            print(f"  {case['case_id']}: {'PASS' if case['passed'] else 'FAIL'} {','.join(case['failures'])}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
