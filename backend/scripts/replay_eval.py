"""Replay evaluation CLI.

Usage:
    python backend/scripts/replay_eval.py [--dir evals/live_replay/seed] [--json]

Loads every snapshot in the given dir, runs the rule verdict engine over
the recorded retrieval bundle, and prints a FEVER-scored report.

Exit code is non-zero when the FEVER score is below the pass threshold so
this can be wired into CI (`--pass-threshold 0.3`).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Pin the eval to the pure rule verdict path — no live LLM calls. The verdict
# engine's llm_judge_claims override is gated by ANALYSIS_PROVIDER=kimi + an API
# key, so clearing both keeps replay deterministic and offline. Set BEFORE any
# backend import so get_settings caches the offline config.
os.environ["ANALYSIS_PROVIDER"] = "off"
os.environ.pop("KIMI_API_KEY", None)
os.environ["LLM_API_KEY"] = ""

# Make backend package importable when invoked from repo root or scripts dir.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.models.schemas import AnalyzeRequest, ClaimItem, NormalizedEvent  # noqa: E402
from backend.app.services.eval_recorder import (  # noqa: E402
    bundle_from_snapshot,
    evaluate_batch,
    iter_snapshots,
)
from backend.app.services.verdict_engine import VerdictEngine  # noqa: E402


def _replay_one(snapshot) -> list[dict]:
    engine = VerdictEngine()
    request = AnalyzeRequest(raw_input=snapshot.raw_input)
    event = NormalizedEvent(
        title=snapshot.raw_input,
        summary=snapshot.raw_input,
        source_name="replay",
        source_url="",
        published_at="",
        input_type="text_news",
        event_source="input_normalized",
        raw_input=snapshot.raw_input,
    )
    claims = [
        ClaimItem(claim=c["claim"], claim_type=c.get("claim_type", "fact"))
        for c in snapshot.expected_claims
    ]
    bundle = bundle_from_snapshot(snapshot)
    claim_results, _evidence, _grade = engine.evaluate(
        request=request, event=event, claims=claims, retrieval_bundle=bundle,
    )
    return [
        {
            "claim": cr.claim,
            "verdict": cr.verdict,
            "evidence": [{"url": e.url, "title": e.title} for e in cr.evidence],
        }
        for cr in claim_results
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay eval snapshots and compute FEVER score.")
    parser.add_argument(
        "--dir",
        default=str(REPO_ROOT / "evals" / "live_replay" / "seed"),
        help="Directory containing snapshot JSON files",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument(
        "--pass-threshold",
        type=float,
        default=0.0,
        help="Exit non-zero when FEVER score falls below this (default 0 = never fail)",
    )
    args = parser.parse_args()

    snap_dir = Path(args.dir)
    snapshots = iter_snapshots(snap_dir)
    if not snapshots:
        print(f"no snapshots in {snap_dir}", file=sys.stderr)
        return 2

    actuals = [_replay_one(s) for s in snapshots]
    report = evaluate_batch(snapshots, actuals)

    if args.json:
        print(json.dumps({
            "total_claims": report.total_claims,
            "label_accuracy": report.label_accuracy,
            "evidence_accuracy": report.evidence_accuracy,
            "fever_score": report.fever_score,
            "per_case": report.per_case,
        }, ensure_ascii=False, indent=2))
    else:
        print(f"Replayed {len(snapshots)} snapshots, {report.total_claims} claims total")
        print(f"  Label accuracy:    {report.label_accuracy:.2%}")
        print(f"  Evidence accuracy: {report.evidence_accuracy:.2%}")
        print(f"  FEVER score:       {report.fever_score:.2%}")
        print("Per-case breakdown:")
        for case in report.per_case:
            marker = "PASS" if case["fever_pass"] == case["claims"] else "FAIL"
            print(
                f"  [{marker}] {case['case_id']}: "
                f"fever={case['fever_pass']}/{case['claims']} "
                f"label={case['label_correct']}/{case['claims']}"
            )

    if args.pass_threshold and report.fever_score < args.pass_threshold:
        print(
            f"FEVER {report.fever_score:.2%} below threshold {args.pass_threshold:.2%}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
