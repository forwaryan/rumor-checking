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
import hashlib
import json
import os
import platform
import subprocess
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

# Pin the eval to the pure rule verdict path by default — no live LLM calls.
# The verdict engine's llm_judge_claims override is gated by ANALYSIS_PROVIDER=kimi
# + an API key, so clearing both keeps replay deterministic and offline. Set
# BEFORE any backend import so get_settings caches the offline config.
#
# Opt in to the live LLM judge with `--engine llm`: we peek at argv here (argparse
# runs later, inside main) and, in that mode, leave the ambient LLM settings
# intact so llm_judge_claims routes through the real gateway. This is
# non-deterministic and network-bound, so CI keeps the rule default.
_ENGINE = "rule"
for _i, _arg in enumerate(sys.argv[1:]):
    if _arg == "--engine" and _i + 2 <= len(sys.argv[1:]):
        _ENGINE = sys.argv[_i + 2]
    elif _arg.startswith("--engine="):
        _ENGINE = _arg.split("=", 1)[1]
if _ENGINE != "llm":
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
    category_metric_deltas,
    evaluate_batch,
    iter_snapshots,
    metric_deltas,
)
from backend.app.services.verdict_engine import VerdictEngine  # noqa: E402


def _sha256_files(paths: list[Path], *, base: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(base).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _git_value(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def build_run_manifest(*, snap_dir: Path, snapshots: list, run_name: str, engine: str = "rule") -> dict:
    """Describe the code, corpus, and configuration behind a run."""
    snapshot_paths = sorted(path for path in snap_dir.glob("*.json") if path.name != "cases.json")
    implementation_paths = [
        Path(__file__).resolve(),
        *(REPO_ROOT / "backend" / "app").rglob("*.py"),
    ]
    is_llm = engine == "llm"
    configuration = {
        "analysis_provider": "kimi" if is_llm else "off",
        "engine": engine,
        "network_access": is_llm,
        "temperature": None,
        "seed": None,
    }
    configuration_json = json.dumps(configuration, sort_keys=True, separators=(",", ":"))
    git_sha = os.getenv("GITHUB_SHA") or _git_value("rev-parse", "HEAD")
    dirty_output = _git_value("status", "--porcelain")

    try:
        corpus_path = snap_dir.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        corpus_path = f"external:{snap_dir.name}"

    return {
        "schema_version": 1,
        "name": run_name,
        "engine": engine,
        "snapshot_count": len(snapshots),
        "generated_at": datetime.now(UTC).isoformat(),
        "git": {
            "sha": git_sha,
            "dirty": bool(dirty_output) if dirty_output is not None else None,
        },
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "corpus": {
            "path": corpus_path,
            "sha256": _sha256_files(snapshot_paths, base=snap_dir),
            "snapshot_count": len(snapshots),
            "case_ids": [snapshot.case_id for snapshot in snapshots],
        },
        "implementation": {
            "engine": engine,
            "sha256": _sha256_files(implementation_paths, base=REPO_ROOT),
            "model": None,
            "prompt_version": None,
        },
        "configuration": configuration,
        "configuration_sha256": hashlib.sha256(configuration_json.encode("utf-8")).hexdigest(),
    }


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
    # In both engines the call path is identical; `evaluate` -> evaluate_with_source
    # -> llm_judge_claims, which self-gates on settings. `--engine llm` leaves the
    # ambient LLM settings intact (see the top-of-file guard) so the judge fires;
    # the default rule engine cleared them, so the same call stays offline.
    claim_results, _evidence, _grade = engine.evaluate(
        request=request, event=event, claims=claims, retrieval_bundle=bundle,
    )
    return [
        {
            "claim": cr.claim,
            "verdict": cr.verdict,
            "confidence": cr.confidence,
            "evidence": [
                {
                    "url": e.url,
                    "title": e.title,
                    "source_name": e.source_name,
                    "source_tier": e.source_tier,
                    "published_at": e.published_at,
                }
                for e in cr.evidence
            ],
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
    parser.add_argument("--run-name", default="rule-current", help="Label stored in JSON reports")
    parser.add_argument(
        "--engine",
        choices=["rule", "llm"],
        default="rule",
        help=(
            "rule (default): offline, deterministic rule verdict. "
            "llm: route through the live LLM judge via the gateway "
            "(non-deterministic, network-bound, needs a configured key)"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Also write the complete JSON report to this path",
    )
    parser.add_argument(
        "--compare-to",
        type=Path,
        help="Previous JSON report; emits metric deltas for model/rule comparisons",
    )
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
    report_payload = asdict(report)
    report_payload["run"] = build_run_manifest(
        snap_dir=snap_dir,
        snapshots=snapshots,
        run_name=args.run_name,
        engine=args.engine,
    )
    if args.compare_to:
        baseline = json.loads(args.compare_to.read_text(encoding="utf-8"))
        report_payload["comparison"] = {
            "baseline_run": baseline.get("run", {}).get("name", args.compare_to.stem),
            "metric_deltas": metric_deltas(report_payload, baseline),
            "category_metric_deltas": category_metric_deltas(
                report_payload.get("category_metrics", {}),
                baseline.get("category_metrics", {}),
            ),
        }

    serialized_report = json.dumps(report_payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized_report + "\n", encoding="utf-8")

    if args.json:
        print(serialized_report)
    else:
        print(f"Replayed {len(snapshots)} snapshots, {report.total_claims} claims total")
        print(f"  Label accuracy:    {report.label_accuracy:.2%}")
        print(f"  Evidence accuracy: {report.evidence_accuracy:.2%}")
        print(f"  FEVER score:       {report.fever_score:.2%}")
        print(f"  Confidence:        {report.confidence_accuracy:.2%}")
        print(f"  Citation precision:{report.citation_precision:>7.2%}")
        print(f"  Source independence:{report.source_independence_score:>6.2%}")
        print(f"  High-trust evidence:{report.high_trust_evidence_rate:>6.2%}")
        print(f"  Dated evidence:    {report.dated_evidence_rate:.2%}")
        print(f"  Fresh evidence:    {report.fresh_evidence_rate:.2%}")
        print("Category breakdown:")
        for category, metrics in report.category_metrics.items():
            print(
                f"  {category}: label={metrics['label_accuracy']:.2%} "
                f"evidence={metrics['evidence_accuracy']:.2%} "
                f"fever={metrics['fever_score']:.2%} n={metrics['total_claims']}"
            )
        if "comparison" in report_payload:
            print(f"Compared with: {report_payload['comparison']['baseline_run']}")
            for metric, delta in report_payload["comparison"]["metric_deltas"].items():
                print(f"  {metric}: {delta:+.2%}")
            print("Category FEVER deltas:")
            for category, deltas in report_payload["comparison"]["category_metric_deltas"].items():
                print(f"  {category}: {deltas['fever_score']:+.2%}")
        print("Per-case breakdown:")
        for case in report.per_case:
            marker = "PASS" if not case["failure_reasons"] else "FAIL"
            print(
                f"  [{marker}] {case['case_id']}: "
                f"fever={case['fever_pass']}/{case['claims']} "
                f"label={case['label_correct']}/{case['claims']} "
                f"failures={','.join(case['failure_reasons']) or '-'}"
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
