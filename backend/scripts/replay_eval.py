"""Replay evaluation CLI.

Usage:
    python backend/scripts/replay_eval.py [--dir evals/live_replay/seed] [--json]

Loads every snapshot in the given dir, runs the rule verdict engine over
the recorded retrieval bundle, and reports label plus complete URL evidence groups.

Exit code is non-zero when the label-plus-URL-group score is below the pass threshold so
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
# Empty key values prevent dotenv setdefault from restoring live credentials.
# Set BEFORE any backend import so get_settings caches the offline config.
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
    os.environ["KIMI_API_KEY"] = ""
    os.environ["LLM_API_KEY"] = ""

# Make backend package importable when invoked from repo root or scripts dir.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.models.schemas import AnalyzeRequest, ClaimItem, NormalizedEvent  # noqa: E402
from backend.app.services.eval_recorder import (  # noqa: E402
    EVALUATION_PROTOCOL,
    EVIDENCE_GRANULARITY,
    SCORING_VERSION,
    SOURCE_INDEPENDENCE_BASIS,
    bundle_from_snapshot,
    category_metric_deltas,
    corpus_summary,
    evaluate_batch,
    is_quarantined,
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


def build_run_manifest(
    *, snap_dir: Path, snapshots: list, run_name: str, engine: str = "rule",
    evaluation_split: str = "all", corpus_snapshots: list | None = None,
) -> dict:
    """Describe the code, corpus, and configuration behind a run."""
    snapshot_paths = sorted(path for path in snap_dir.glob("*.json") if path.name != "cases.json")
    implementation_paths = [
        Path(__file__).resolve(),
        *(REPO_ROOT / "backend" / "app").rglob("*.py"),
    ]
    is_llm = engine == "llm"
    corpus_snapshots = snapshots if corpus_snapshots is None else corpus_snapshots
    selected_case_ids = {snapshot.case_id for snapshot in snapshots}
    selection = {
        "evaluation_split": evaluation_split,
        "total_snapshot_count": len(corpus_snapshots),
        "selected_snapshot_count": len(snapshots),
        "excluded_by_split": [
            snapshot.case_id for snapshot in corpus_snapshots if snapshot.case_id not in selected_case_ids
        ],
    }
    configuration = {
        "analysis_provider": "kimi" if is_llm else "off",
        "engine": engine,
        "network_access": is_llm,
        "temperature": None,
        "seed": None,
        "scoring_version": SCORING_VERSION,
        "evidence_granularity": EVIDENCE_GRANULARITY,
        "evaluation_protocol": EVALUATION_PROTOCOL,
        "source_independence_basis": SOURCE_INDEPENDENCE_BASIS,
        "evaluation_split": evaluation_split,
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
        "scoring_version": SCORING_VERSION,
        "evidence_granularity": EVIDENCE_GRANULARITY,
        "evaluation_protocol": EVALUATION_PROTOCOL,
        "source_independence_basis": SOURCE_INDEPENDENCE_BASIS,
        "evaluation_split": evaluation_split,
        "selection": selection,
        "name": run_name,
        "engine": engine,
        "snapshot_count": sum(not is_quarantined(snapshot) for snapshot in snapshots),
        **corpus_summary(snapshots),
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
            "snapshot_count": sum(not is_quarantined(snapshot) for snapshot in snapshots),
            "case_ids": [snapshot.case_id for snapshot in snapshots if not is_quarantined(snapshot)],
            "all_case_ids": [snapshot.case_id for snapshot in corpus_snapshots],
            "selection": selection,
            **corpus_summary(snapshots),
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
            "notes": cr.notes,
            "claim_type": cr.claim_type,
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


def _verdict_path_metrics(actuals: list[list[dict]], *, engine: str) -> dict:
    """Measure how often the LLM verdict path actually drove the answer vs fell
    back to the rule engine. A claim is an LLM-judge *candidate* when it is a fact
    claim carrying evidence (that is the gate in llm_judge_claims); it counts as
    LLM-judged when its notes carry the "[LLM判定]" marker the judge stamps. The
    rule-fallback rate is candidates that were NOT LLM-judged.

    Only meaningful under --engine llm (the rule engine never invokes the judge,
    so its fallback rate is trivially 100%). The <5% / >30% verdict encodes the
    goal's reliability bands: below 5% the LLM path is carrying the work, above
    30% reliability must be fixed before trusting LLM-primary verdicts."""
    candidates = 0
    llm_judged = 0
    for claim_list in actuals:
        for cr in claim_list:
            if cr.get("claim_type") != "fact" or not cr.get("evidence"):
                continue
            candidates += 1
            if "[LLM判定]" in (cr.get("notes") or ""):
                llm_judged += 1
    fallback = candidates - llm_judged
    rate = (fallback / candidates) if candidates else 0.0
    if engine != "llm":
        verdict = "n/a (rule engine never calls the LLM judge)"
    elif rate < 0.05:
        verdict = "LLM primary path reliable (<5%)"
    elif rate > 0.30:
        verdict = "fix reliability first (>30%)"
    else:
        verdict = "acceptable (5-30%)"
    return {
        "engine": engine,
        "llm_candidate_claims": candidates,
        "llm_judged_claims": llm_judged,
        "rule_fallback_claims": fallback,
        "rule_fallback_rate": round(rate, 4),
        "assessment": verdict,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay supplied evidence and score labels plus complete URL groups.")
    parser.add_argument(
        "--dir",
        default=str(REPO_ROOT / "evals" / "live_replay" / "seed"),
        help="Directory containing snapshot JSON files",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument("--run-name", default="rule-current", help="Label stored in JSON reports")
    parser.add_argument(
        "--evaluation-split", choices=["all", "development", "holdout"], default="all",
        help="Select metadata.evaluation_split; all includes every partition (default)",
    )
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
        help="Positive thresholds require this label-plus-URL-group score and no unexpected claims (default 0 = diagnostic)",
    )
    args = parser.parse_args()

    snap_dir = Path(args.dir)
    try:
        snapshots = iter_snapshots(snap_dir, include_quarantined=True)
    except (OSError, ValueError) as exc:
        print(f"invalid replay corpus: {exc}", file=sys.stderr)
        return 2
    if not snapshots:
        print(f"no snapshots in {snap_dir}", file=sys.stderr)
        return 2
    corpus_snapshots = snapshots
    if args.evaluation_split != "all":
        snapshots = [
            snapshot for snapshot in snapshots
            if snapshot.metadata.get("evaluation_split") == args.evaluation_split
        ]
        if not snapshots:
            print(f"no snapshots with evaluation_split={args.evaluation_split} in {snap_dir}", file=sys.stderr)
            return 2

    actuals = [[] if is_quarantined(snapshot) else _replay_one(snapshot) for snapshot in snapshots]
    report = evaluate_batch(snapshots, actuals)
    report_payload = asdict(report)
    report_payload["run"] = build_run_manifest(
        snap_dir=snap_dir,
        snapshots=snapshots,
        run_name=args.run_name,
        engine=args.engine,
        evaluation_split=args.evaluation_split,
        corpus_snapshots=corpus_snapshots,
    )
    report_payload["selection"] = report_payload["run"]["selection"]
    report_payload["verdict_path"] = _verdict_path_metrics(actuals, engine=args.engine)
    if args.compare_to:
        baseline = json.loads(args.compare_to.read_text(encoding="utf-8"))
        if any(baseline.get(key) != report_payload[key] for key in (
            "scoring_version", "evidence_granularity", "evaluation_protocol",
        )):
            print("cannot compare reports with different or missing scoring protocols", file=sys.stderr)
            return 2
        baseline_run = baseline.get("run", {})
        if (
            baseline_run.get("evaluation_split") != args.evaluation_split
            or baseline_run.get("corpus", {}).get("sha256") != report_payload["run"]["corpus"]["sha256"]
        ):
            print("cannot compare reports from different corpora or evaluation splits", file=sys.stderr)
            return 2
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
        print(
            f"Corpus: {report.total_snapshot_count} total, {report.scored_snapshot_count} scored, "
            f"{len(report.excluded_snapshots)} quarantined; {report.total_claims} scored claims"
        )
        print(f"Protocol: {report.evaluation_protocol}; {report.scoring_version} (URL groups)")
        print(f"Selection: {args.evaluation_split}; {len(snapshots)}/{len(corpus_snapshots)} snapshots selected")
        for excluded in report.excluded_snapshots:
            print(f"  Excluded {excluded['case_id']}: {excluded['reason']}")
        print(f"  Label accuracy:    {report.label_accuracy:.2%}")
        print(f"  Evidence accuracy: {report.evidence_accuracy:.2%}")
        print(f"  Label + URL group: {report.fever_score:.2%} (legacy fever_score)")
        confidence = (
            f"{report.confidence_accuracy:.2%} (n={report.confidence_scored_claims})"
            if report.confidence_scored_claims else "N/A (no scored claims)"
        )
        independence = (
            f"{report.source_independence_score:.2%} (n={report.source_independence_scored_claims})"
            if report.source_independence_scored_claims else "N/A (no scored claims)"
        )
        freshness = (
            f"{report.fresh_evidence_rate:.2%} (n={report.freshness_scored_evidence})"
            if report.freshness_scored_evidence else "N/A (no scored evidence)"
        )
        print(f"  Confidence:        {confidence}")
        print(f"  Citation precision:{report.citation_precision:>7.2%}")
        print(f"  Source independence: {independence}")
        print(f"  High-trust evidence:{report.high_trust_evidence_rate:>6.2%}")
        print(f"  Dated evidence:    {report.dated_evidence_rate:.2%}")
        print(f"  Fresh evidence:    {freshness}")
        vp = report_payload["verdict_path"]
        print(
            f"  Rule-fallback rate:{vp['rule_fallback_rate']:>7.2%} "
            f"({vp['rule_fallback_claims']}/{vp['llm_candidate_claims']} candidates) "
            f"— {vp['assessment']}"
        )
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

    if not report.scored_snapshot_count:
        print("no scoreable snapshots: all corpus snapshots are quarantined", file=sys.stderr)
        return 2
    if args.pass_threshold > 0 and report.unexpected_claim_count:
        print(f"acceptance failed: {report.unexpected_claim_count} unexpected claims", file=sys.stderr)
        return 1
    if args.pass_threshold and report.fever_score < args.pass_threshold:
        print(
            f"FEVER {report.fever_score:.2%} below threshold {args.pass_threshold:.2%}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
