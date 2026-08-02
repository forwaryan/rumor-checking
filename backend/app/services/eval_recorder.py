"""Live replay evaluation framework.

Records real pipeline runs (input + retrieval snapshot + output) and replays
them deterministically by injecting the saved retrieval results. Supports
FEVER-style scoring: a case passes ONLY when both the verdict label AND the
cited evidence are correct.

Usage:
  # Record a run:
    from backend.app.services.eval_recorder import record_run
    snapshot = record_run(request, retrieval_bundle, claim_results)
    # Saves to evals/live_replay/<date>/<case_id>.json

  # Replay + score:
    pytest backend/tests/test_live_replay.py
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class EvalSnapshot:
    """A recorded pipeline run for replay evaluation."""

    case_id: str
    recorded_at: str
    raw_input: str
    retrieval_results: list[dict]
    expected_claims: list[dict]
    metadata: dict


@dataclass
class FeverScore:
    """FEVER-style evaluation result for a single claim."""

    claim: str
    label_correct: bool
    evidence_correct: bool
    fever_pass: bool  # True only when BOTH label AND evidence are correct


def record_snapshot(
    *,
    case_id: str,
    raw_input: str,
    retrieval_results: list[dict],
    claim_results: list[dict],
    output_dir: Path | None = None,
    metadata: dict | None = None,
) -> Path:
    """Record a pipeline run as a replay-able eval snapshot.

    Returns the path to the saved JSON file.
    """
    if output_dir is None:
        from backend.app.core.config import get_settings
        settings = get_settings()
        output_dir = settings.project_root / "evals" / "live_replay" / datetime.now(UTC).strftime("%Y-%m-%d")

    output_dir.mkdir(parents=True, exist_ok=True)

    snapshot = EvalSnapshot(
        case_id=case_id,
        recorded_at=datetime.now(UTC).isoformat(),
        raw_input=raw_input,
        retrieval_results=retrieval_results,
        expected_claims=claim_results,
        metadata=metadata or {},
    )

    path = output_dir / f"{case_id}.json"
    path.write_text(json.dumps(asdict(snapshot), ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("eval_snapshot_recorded case_id=%s path=%s", case_id, path)
    return path


def load_snapshot(path: Path) -> EvalSnapshot:
    """Load a previously recorded eval snapshot."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return EvalSnapshot(**data)


def iter_snapshots(directory: Path) -> list[EvalSnapshot]:
    """Load every *.json snapshot in a directory (skips aggregate cases.json).

    Ordered by filename so replay runs are deterministic across machines."""
    if not directory.exists():
        return []
    paths = sorted(p for p in directory.glob("*.json") if p.name != "cases.json")
    snapshots: list[EvalSnapshot] = []
    for p in paths:
        try:
            snapshots.append(load_snapshot(p))
        except Exception as exc:
            logger.warning("eval_snapshot_load_failed path=%s error=%s", p, exc)
    return snapshots


def bundle_from_snapshot(snapshot: EvalSnapshot):
    """Rehydrate stored retrieval_results into a RetrievalBundle for replay.

    Imported lazily so the module has no runtime dependency on retrieval_models
    when only scoring is used (e.g. in a CI job that reads pre-computed outputs).
    """
    from backend.app.services.retrieval_models import RetrievalBundle, SearchResult

    results = []
    for i, r in enumerate(snapshot.retrieval_results):
        results.append(
            SearchResult(
                case_id="replay",
                query=snapshot.raw_input,
                result_id=r.get("result_id", f"r{i}"),
                title=r.get("title", ""),
                url=r.get("url", ""),
                source_name=r.get("source_name", ""),
                published_at=r.get("published_at", ""),
                snippet=r.get("snippet", ""),
                source_tier=r.get("source_tier", "C"),
                provider_name="replay",
            )
        )
    return RetrievalBundle(
        query=snapshot.raw_input,
        matched_case_id="replay",
        canonical_results=tuple(results),
        raw_results=tuple(results),
        provider_name="replay",
    )


def fever_score_claim(
    *,
    expected_verdict: str,
    actual_verdict: str,
    expected_evidence_urls: set[str],
    actual_evidence_urls: set[str],
) -> FeverScore:
    """Score a single claim using FEVER methodology.

    FEVER requires BOTH:
    1. Label correct: predicted verdict matches expected
    2. Evidence correct: predicted evidence set covers at least one expected URL
       (relaxed from strict set equality — following FEVER "at least one" rule)
    """
    label_correct = actual_verdict == expected_verdict

    # Evidence is correct if the actual set contains at least one expected URL
    evidence_correct = bool(expected_evidence_urls & actual_evidence_urls) if expected_evidence_urls else True

    return FeverScore(
        claim="",
        label_correct=label_correct,
        evidence_correct=evidence_correct,
        fever_pass=label_correct and evidence_correct,
    )


@dataclass
class EvalReport:
    """Aggregate evaluation metrics across a batch of snapshots."""

    total_claims: int
    label_accuracy: float
    evidence_accuracy: float
    fever_score: float  # strict: both label AND evidence correct
    per_case: list[dict]


def evaluate_batch(snapshots: list[EvalSnapshot], actual_results: list[list[dict]]) -> EvalReport:
    """Evaluate a batch of replayed snapshots against their expected outputs.

    Parameters
    ----------
    snapshots: List of recorded snapshots (ground truth)
    actual_results: List of claim_results from replaying each snapshot
    """
    all_scores: list[FeverScore] = []
    per_case: list[dict] = []

    for snapshot, actuals in zip(snapshots, actual_results, strict=False):
        case_scores: list[FeverScore] = []
        for expected, actual in zip(snapshot.expected_claims, actuals, strict=False):
            expected_urls = {e.get("url", "") for e in expected.get("evidence", []) if e.get("url")}
            actual_urls = {e.get("url", "") for e in actual.get("evidence", []) if e.get("url")}

            score = fever_score_claim(
                expected_verdict=expected.get("verdict", ""),
                actual_verdict=actual.get("verdict", ""),
                expected_evidence_urls=expected_urls,
                actual_evidence_urls=actual_urls,
            )
            score = FeverScore(
                claim=expected.get("claim", ""),
                label_correct=score.label_correct,
                evidence_correct=score.evidence_correct,
                fever_pass=score.fever_pass,
            )
            case_scores.append(score)
            all_scores.append(score)

        per_case.append({
            "case_id": snapshot.case_id,
            "claims": len(case_scores),
            "fever_pass": sum(1 for s in case_scores if s.fever_pass),
            "label_correct": sum(1 for s in case_scores if s.label_correct),
        })

    total = len(all_scores)
    if total == 0:
        return EvalReport(total_claims=0, label_accuracy=0, evidence_accuracy=0, fever_score=0, per_case=[])

    return EvalReport(
        total_claims=total,
        label_accuracy=sum(1 for s in all_scores if s.label_correct) / total,
        evidence_accuracy=sum(1 for s in all_scores if s.evidence_correct) / total,
        fever_score=sum(1 for s in all_scores if s.fever_pass) / total,
        per_case=per_case,
    )
