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
from datetime import UTC, date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

COMPARABLE_METRICS = (
    "label_accuracy",
    "evidence_accuracy",
    "fever_score",
    "confidence_accuracy",
    "citation_precision",
    "source_independence_score",
    "high_trust_evidence_rate",
    "dated_evidence_rate",
    "fresh_evidence_rate",
)
CATEGORY_COMPARABLE_METRICS = (
    "label_accuracy",
    "evidence_accuracy",
    "fever_score",
)


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
    confidence_accuracy: float
    citation_precision: float
    source_independence_score: float
    high_trust_evidence_rate: float
    dated_evidence_rate: float
    fresh_evidence_rate: float
    category_metrics: dict[str, dict]
    per_case: list[dict]


def _ratio(values: list[bool | float]) -> float:
    return sum(float(value) for value in values) / len(values) if values else 0.0


def metric_deltas(current: dict, baseline: dict) -> dict[str, float]:
    """Return comparable metric deltas between two serialized eval reports."""
    return {
        metric: float(current.get(metric, 0.0)) - float(baseline.get(metric, 0.0))
        for metric in COMPARABLE_METRICS
    }


def category_metric_deltas(
    current: dict[str, dict],
    baseline: dict[str, dict],
) -> dict[str, dict[str, float | int]]:
    """Return per-category deltas, including categories absent from one run."""
    deltas: dict[str, dict[str, float | int]] = {}
    for category in sorted(set(current) | set(baseline)):
        current_metrics = current.get(category, {})
        baseline_metrics = baseline.get(category, {})
        deltas[category] = {
            "total_claims": int(current_metrics.get("total_claims", 0))
            - int(baseline_metrics.get("total_claims", 0)),
            **{
                metric: float(current_metrics.get(metric, 0.0))
                - float(baseline_metrics.get(metric, 0.0))
                for metric in CATEGORY_COMPARABLE_METRICS
            },
        }
    return deltas


def _categories(snapshot: EvalSnapshot) -> list[str]:
    categories = snapshot.metadata.get("categories")
    if isinstance(categories, list):
        normalized = [str(category).strip() for category in categories if str(category).strip()]
        if normalized:
            return normalized
    category = str(snapshot.metadata.get("category", "")).strip()
    return [category] if category else ["uncategorized"]


def _parse_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _evidence_details(snapshot: EvalSnapshot, actual: dict) -> list[dict]:
    by_url = {
        item.get("url", ""): item
        for item in snapshot.retrieval_results
        if item.get("url")
    }
    details = []
    for item in actual.get("evidence", []):
        url = item.get("url", "")
        details.append({**by_url.get(url, {}), **item})
    return details


def _category_report(scores: list[FeverScore]) -> dict[str, float | int]:
    return {
        "total_claims": len(scores),
        "label_accuracy": _ratio([score.label_correct for score in scores]),
        "evidence_accuracy": _ratio([score.evidence_correct for score in scores]),
        "fever_score": _ratio([score.fever_pass for score in scores]),
    }


def evaluate_batch(snapshots: list[EvalSnapshot], actual_results: list[list[dict]]) -> EvalReport:
    """Evaluate a batch of replayed snapshots against their expected outputs.

    Parameters
    ----------
    snapshots: List of recorded snapshots (ground truth)
    actual_results: List of claim_results from replaying each snapshot
    """
    all_scores: list[FeverScore] = []
    per_case: list[dict] = []
    confidence_scores: list[bool] = []
    citation_precisions: list[float] = []
    source_independence_scores: list[float] = []
    high_trust_scores: list[bool] = []
    dated_scores: list[bool] = []
    fresh_scores: list[bool] = []
    scores_by_category: dict[str, list[FeverScore]] = {}

    for snapshot_index, snapshot in enumerate(snapshots):
        actuals = actual_results[snapshot_index] if snapshot_index < len(actual_results) else []
        case_scores: list[FeverScore] = []
        failure_reasons: list[str] = []
        for index, expected in enumerate(snapshot.expected_claims):
            if index >= len(actuals):
                score = FeverScore(
                    claim=expected.get("claim", ""),
                    label_correct=False,
                    evidence_correct=False,
                    fever_pass=False,
                )
                case_scores.append(score)
                all_scores.append(score)
                failure_reasons.append("missing_claim")
                for category in _categories(snapshot):
                    scores_by_category.setdefault(category, []).append(score)
                continue

            actual = actuals[index]
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

            for category in _categories(snapshot):
                scores_by_category.setdefault(category, []).append(score)

            if not score.label_correct:
                failure_reasons.append("wrong_label")
            if not score.evidence_correct:
                failure_reasons.append("missing_expected_evidence")

            expected_confidence = str(expected.get("confidence", "")).strip()
            if expected_confidence:
                confidence_correct = str(actual.get("confidence", "")).strip() == expected_confidence
                confidence_scores.append(confidence_correct)
                if not confidence_correct:
                    failure_reasons.append("confidence_mismatch")

            if actual_urls:
                citation_precisions.append(len(expected_urls & actual_urls) / len(actual_urls))
            else:
                citation_precisions.append(1.0 if not expected_urls else 0.0)

            evidence_details = _evidence_details(snapshot, actual)
            evaluation = expected.get("evaluation", {})
            minimum_sources = int(evaluation.get("min_independent_sources", 0) or 0)
            if minimum_sources:
                source_names = {
                    str(item.get("source_name", "")).strip().lower()
                    for item in evidence_details
                    if str(item.get("source_name", "")).strip()
                }
                independence = min(len(source_names) / minimum_sources, 1.0)
                source_independence_scores.append(independence)
                if independence < 1.0:
                    failure_reasons.append("low_source_diversity")

            for item in evidence_details:
                high_trust_scores.append(str(item.get("source_tier", "")).upper() in {"S", "A"})
                dated_scores.append(_parse_date(item.get("published_at")) is not None)

            if evaluation.get("require_high_trust") and not any(
                str(item.get("source_tier", "")).upper() in {"S", "A"}
                for item in evidence_details
            ):
                failure_reasons.append("no_high_trust_evidence")
            if evaluation.get("require_dated_evidence") and any(
                _parse_date(item.get("published_at")) is None for item in evidence_details
            ):
                failure_reasons.append("undated_evidence")

            fresh_after = _parse_date(evaluation.get("fresh_after"))
            if fresh_after and evidence_details:
                claim_fresh_scores = [
                    bool(published_at and published_at >= fresh_after)
                    for item in evidence_details
                    if (published_at := _parse_date(item.get("published_at"))) is not None
                ]
                claim_fresh_scores.extend(
                    False
                    for item in evidence_details
                    if _parse_date(item.get("published_at")) is None
                )
                fresh_scores.extend(claim_fresh_scores)
                if not claim_fresh_scores or not all(claim_fresh_scores):
                    failure_reasons.append("stale_evidence")

        per_case.append({
            "case_id": snapshot.case_id,
            "categories": _categories(snapshot),
            "claims": len(case_scores),
            "fever_pass": sum(1 for s in case_scores if s.fever_pass),
            "label_correct": sum(1 for s in case_scores if s.label_correct),
            "failure_reasons": list(dict.fromkeys(failure_reasons)),
        })

    total = len(all_scores)
    if total == 0:
        return EvalReport(
            total_claims=0,
            label_accuracy=0,
            evidence_accuracy=0,
            fever_score=0,
            confidence_accuracy=0,
            citation_precision=0,
            source_independence_score=0,
            high_trust_evidence_rate=0,
            dated_evidence_rate=0,
            fresh_evidence_rate=0,
            category_metrics={},
            per_case=[],
        )

    return EvalReport(
        total_claims=total,
        label_accuracy=sum(1 for s in all_scores if s.label_correct) / total,
        evidence_accuracy=sum(1 for s in all_scores if s.evidence_correct) / total,
        fever_score=sum(1 for s in all_scores if s.fever_pass) / total,
        confidence_accuracy=_ratio(confidence_scores),
        citation_precision=_ratio(citation_precisions),
        source_independence_score=_ratio(source_independence_scores),
        high_trust_evidence_rate=_ratio(high_trust_scores),
        dated_evidence_rate=_ratio(dated_scores),
        fresh_evidence_rate=_ratio(fresh_scores),
        category_metrics={
            category: _category_report(scores)
            for category, scores in sorted(scores_by_category.items())
        },
        per_case=per_case,
    )
