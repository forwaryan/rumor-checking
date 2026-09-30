"""Replay test: run seed snapshots through the rule verdict engine and score.

Loads every JSON snapshot under evals/live_replay/seed/, injects the recorded
retrieval bundle deterministically (no live search), runs the verdict engine
against the expected claim text, then scores labels plus complete URL groups.

The threshold is intentionally lenient — the rule engine is not the primary
verdict path, so this guards regressions rather than tracking absolute accuracy.
When the LLM verdict path is available in CI, a companion test can raise the bar.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path

import pytest

from backend.app.core.config import get_settings
from backend.app.models.schemas import AnalyzeRequest, ClaimItem, NormalizedEvent
from backend.app.services.eval_recorder import (
    bundle_from_snapshot,
    evaluate_batch,
    fever_score_claim,
    iter_snapshots,
)
from backend.app.services.verdict_engine import VerdictEngine
from backend.scripts.convert_cfever import to_simplified

REPLAY_ROOT = Path(__file__).resolve().parents[2] / "evals" / "live_replay"
SEED_DIR = REPLAY_ROOT / "seed"
CFEVER_CURATED_DIR = REPLAY_ROOT / "cfever_curated"
COVID19_HEALTH_RUMOR_CURATED_DIR = REPLAY_ROOT / "covid19_health_rumor_curated"
HARD_DIR = REPLAY_ROOT / "hard"
CONTEXT_CHALLENGE_DIR = REPLAY_ROOT / "context_challenge"


def _replay_one(snapshot) -> list[dict]:
    """Run one snapshot through the verdict engine with the recorded bundle."""
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
    claims = [ClaimItem(claim=c["claim"], claim_type=c.get("claim_type", "fact"))
              for c in snapshot.expected_claims]

    bundle = bundle_from_snapshot(snapshot)
    claim_results, _evidence, _grade = engine.evaluate(
        request=request, event=event, claims=claims, retrieval_bundle=bundle,
    )
    return [
        {
            "claim": cr.claim,
            "claim_type": cr.claim_type,
            "verdict": cr.verdict,
            "confidence": cr.confidence,
            "evidence": [e.model_dump() for e in cr.evidence],
        }
        for cr in claim_results
    ]


@pytest.fixture(scope="module")
def snapshots():
    if not SEED_DIR.exists():
        pytest.skip(f"seed dir missing: {SEED_DIR}")
    loaded = iter_snapshots(SEED_DIR)
    if not loaded:
        pytest.skip("no snapshots found in seed dir")
    return loaded


@pytest.fixture(scope="module")
def cfever_snapshots():
    loaded = iter_snapshots(CFEVER_CURATED_DIR)
    if not loaded:
        pytest.skip("no curated CFEVER snapshots found")
    return loaded


@pytest.fixture(scope="module")
def covid19_health_rumor_snapshots():
    loaded = iter_snapshots(COVID19_HEALTH_RUMOR_CURATED_DIR)
    if not loaded:
        pytest.skip("no curated COVID-19 health-rumor snapshots found")
    return loaded


def test_seed_snapshots_load(snapshots):
    """Sanity: the corpus loads and covers multiple verdict types."""
    assert len(snapshots) >= 8
    assert all(snapshot.metadata.get("provenance") == "synthetic" for snapshot in snapshots)
    verdicts = {c["verdict"] for s in snapshots for c in s.expected_claims}
    assert {"supported", "refuted", "conflicting", "insufficient"} <= verdicts
    categories = {
        category
        for snapshot in snapshots
        for category in snapshot.metadata.get("categories", [])
    }
    assert {
        "time_sensitive",
        "stale_news",
        "subject_mismatch",
        "conflicting_sources",
        "dateless_evidence",
        "source_independence",
        "insufficient_evidence",
    } <= categories


def test_curated_cfever_snapshots_are_traceable_and_balanced(cfever_snapshots):
    assert len(cfever_snapshots) == 24
    verdicts = [snapshot.expected_claims[0]["verdict"] for snapshot in cfever_snapshots]
    assert {verdict: verdicts.count(verdict) for verdict in set(verdicts)} == {
        "supported": 8,
        "refuted": 8,
        "insufficient": 8,
    }
    for snapshot in cfever_snapshots:
        assert snapshot.metadata["provenance"] == "public_dataset"
        assert snapshot.metadata["source_revision"]
        assert snapshot.metadata["dataset_license"] == "Apache-2.0"
        assert snapshot.metadata["text_variant"] == "zh-Hans"
        assert snapshot.metadata["annotation_source"] == "upstream_label"
        assert snapshot.metadata["source_verified"] is True
        assert snapshot.metadata["original_claim"]
        assert len(snapshot.metadata["source_file_sha256"]) == 64
        assert snapshot.metadata["source_record_line"] > 0
        assert snapshot.expected_claims[0]["evaluation"]["score_confidence"] is False
        assert all(".example" not in result["url"] for result in snapshot.retrieval_results)
        texts = [snapshot.raw_input]
        for result in snapshot.retrieval_results:
            texts.extend([result["title"], result["source_name"], result["snippet"]])
        for claim in snapshot.expected_claims:
            texts.append(claim["claim"])
            texts.extend(evidence["title"] for evidence in claim["evidence"])
        assert all(to_simplified(text) == text for text in texts)


def test_curated_cfever_replay_meets_initial_baseline(cfever_snapshots):
    development = [snapshot for snapshot in cfever_snapshots if snapshot.metadata["evaluation_split"] == "development"]
    actuals = [_replay_one(snapshot) for snapshot in development]
    report = evaluate_batch(development, actuals)

    assert report.total_claims == 12
    assert report.evidence_accuracy == 1.0
    assert report.fever_score >= 1 / 3


def test_curated_covid19_health_rumors_are_traceable_simplified_chinese(
    covid19_health_rumor_snapshots,
):
    assert len(covid19_health_rumor_snapshots) == 8
    assert {
        snapshot.expected_claims[0]["verdict"]
        for snapshot in covid19_health_rumor_snapshots
    } == {"refuted", "insufficient"}
    for snapshot in covid19_health_rumor_snapshots:
        assert snapshot.metadata["provenance"] == "public_dataset"
        assert snapshot.metadata["source_revision"]
        assert snapshot.metadata["dataset_license"] == "MIT"
        assert snapshot.metadata["evidence_license"].startswith("third-party source terms")
        assert snapshot.metadata["annotation_source"] == "project_review"
        assert snapshot.metadata["original_label_field"] == "rumor_type"
        assert snapshot.metadata["original_label"] == snapshot.metadata["original_source_record"]["rumor_type"]
        assert snapshot.metadata["original_claim"] == snapshot.metadata["original_source_record"]["article_title"]
        assert snapshot.metadata["annotation_rationale"]
        assert snapshot.metadata["claim_transformation"]
        assert snapshot.metadata["evidence_transformation"]
        assert len(snapshot.metadata["source_file_sha256"]) == 64
        assert snapshot.expected_claims[0]["evaluation"]["score_confidence"] is False
        assert snapshot.metadata["text_variant"] == "zh-Hans"
        assert len(snapshot.expected_claims) == 1
        assert len(snapshot.retrieval_results) == 1
        result = snapshot.retrieval_results[0]
        assert result["url"].startswith("https://")
        texts = [
            snapshot.raw_input,
            result["title"],
            result["source_name"],
            result["snippet"],
            snapshot.expected_claims[0]["claim"],
        ]
        assert all(to_simplified(text) == text for text in texts)


def test_curated_covid19_health_rumor_replay_meets_initial_baseline(
    covid19_health_rumor_snapshots,
):
    actuals = [_replay_one(snapshot) for snapshot in covid19_health_rumor_snapshots]
    report = evaluate_batch(covid19_health_rumor_snapshots, actuals)

    assert report.total_claims == 8
    assert report.evidence_accuracy == 1.0
    assert report.fever_score >= 0.125


def test_behavior_fixtures_are_explicitly_marked_synthetic(snapshots):
    hard_snapshots = iter_snapshots(HARD_DIR)
    assert len(hard_snapshots) == 8
    for snapshot in [*snapshots, *hard_snapshots]:
        assert snapshot.metadata["provenance"] == "synthetic"
        assert snapshot.metadata["fixture_purpose"].endswith("regression")


def test_public_development_and_holdout_use_disjoint_topics(cfever_snapshots):
    groups = {}
    for partition in ("development", "holdout"):
        selected = [snapshot for snapshot in cfever_snapshots if snapshot.metadata["evaluation_split"] == partition]
        assert len(selected) == 12
        assert Counter(snapshot.expected_claims[0]["verdict"] for snapshot in selected) == {
            "supported": 4, "refuted": 4, "insufficient": 4,
        }
        groups[partition] = {snapshot.metadata["topic_group"] for snapshot in selected}
        assert len(groups[partition]) == 4
    assert groups["development"].isdisjoint(groups["holdout"])


def test_health_source_repairs_preserve_scope_and_historical_uncertainty(covid19_health_rumor_snapshots):
    by_id = {str(snapshot.metadata["source_case_id"]): snapshot for snapshot in covid19_health_rumor_snapshots}
    assert by_id["80840"].metadata["original_label"] == "dread"
    assert by_id["81017"].metadata["original_label"] == "wish"
    pending = by_id["80840"].expected_claims[0]
    assert pending["verdict"] == "insufficient"
    assert pending["evidence"][0]["url"] == by_id["80840"].retrieval_results[0]["url"]
    alcohol = by_id["80401"]
    assert "对细菌消毒时" in alcohol.raw_input
    assert "效果不如75%" in alcohol.retrieval_results[0]["snippet"]
    assert "……" not in alcohol.retrieval_results[0]["snippet"]
    assert alcohol.metadata["snapshot_kind"] == "live_page_with_declared_historical_dates"
    assert datetime.fromisoformat(alcohol.recorded_at.replace("Z", "+00:00")) >= datetime.fromisoformat(
        alcohol.metadata["source_updated_at"].replace("Z", "+00:00"),
    )


def test_conflict_fixture_requires_both_sources_and_reposts_share_one_origin():
    quantity = next(snapshot for snapshot in iter_snapshots(HARD_DIR) if snapshot.case_id.startswith("hard_005"))
    expected = quantity.expected_claims[0]
    urls = {evidence["url"] for evidence in expected["evidence"]}
    assert len(urls) == 2
    for url in urls:
        assert not fever_score_claim(
            expected_verdict="conflicting", actual_verdict="conflicting",
            expected_evidence_urls=urls, actual_evidence_urls={url},
        ).fever_pass
    reposts = next(snapshot for snapshot in iter_snapshots(SEED_DIR) if snapshot.case_id.startswith("seed_016"))
    official = {result["origin_id"] for result in reposts.retrieval_results if result["source_tier"] in {"A", "S"}}
    assert len(official) == 1
    assert reposts.expected_claims[0]["evaluation"]["min_independent_sources"] == len(official)


def test_context_challenges_cover_all_labels_and_nonempty_uncertainty():
    snapshots = iter_snapshots(CONTEXT_CHALLENGE_DIR)
    assert len(snapshots) == 8
    for partition in ("development", "holdout"):
        selected = [snapshot for snapshot in snapshots if snapshot.metadata["evaluation_split"] == partition]
        assert Counter(snapshot.expected_claims[0]["verdict"] for snapshot in selected) == {
            "supported": 1, "refuted": 1, "conflicting": 1, "insufficient": 1,
        }
    unknown = [snapshot for snapshot in snapshots if snapshot.expected_claims[0]["verdict"] == "insufficient"]
    assert len(unknown) == 2
    assert all(snapshot.retrieval_results for snapshot in unknown)
    assert all(snapshot.metadata["provenance"] == "synthetic" for snapshot in snapshots)
    assert all(snapshot.metadata["annotation_rationale"] for snapshot in snapshots)


def test_context_challenge_development_baseline():
    selected = [snapshot for snapshot in iter_snapshots(CONTEXT_CHALLENGE_DIR) if snapshot.metadata["evaluation_split"] == "development"]
    report = evaluate_batch(selected, [_replay_one(snapshot) for snapshot in selected])
    assert report.total_claims == 4
    assert report.fever_score >= 0.75


def test_replay_produces_deterministic_metrics(snapshots):
    """Two replays of the same corpus should produce identical FEVER metrics."""
    actuals_a = [_replay_one(s) for s in snapshots]
    actuals_b = [_replay_one(s) for s in snapshots]
    report_a = evaluate_batch(snapshots, actuals_a)
    report_b = evaluate_batch(snapshots, actuals_b)
    assert report_a.label_accuracy == report_b.label_accuracy
    assert report_a.fever_score == report_b.fever_score


def test_fever_score_meets_baseline(snapshots):
    """Overall FEVER score meets the rule-engine baseline.

    The threshold leaves room for future corpus expansion because:
    - The rule engine relies on keyword/subject overlap, not semantic understanding
    - Some seed cases test LLM-only strengths (conflicting verdicts)
    The deterministic seed baseline is locked at 0.75 to prevent silent collapse.
    """
    actuals = [_replay_one(s) for s in snapshots]
    report = evaluate_batch(snapshots, actuals)
    settings = get_settings()
    # Emit a summary line for CI logs
    print(
        f"\nREPLAY FEVER label={report.label_accuracy:.2%} "
        f"evidence={report.evidence_accuracy:.2%} fever={report.fever_score:.2%} "
        f"total_claims={report.total_claims}"
    )
    # Sanity floor — no negative or NaN
    assert 0.0 <= report.fever_score <= 1.0
    assert report.fever_score >= 0.75
    assert report.total_claims == sum(len(s.expected_claims) for s in snapshots)
    assert settings is not None  # unused but keeps get_settings warm for CI


def test_replay_bundle_preserves_urls(snapshots):
    """bundle_from_snapshot must faithfully reproduce the recorded URLs so
    FEVER evidence scoring compares apples to apples."""
    for s in snapshots:
        bundle = bundle_from_snapshot(s)
        recorded_urls = {r["url"] for r in s.retrieval_results if r.get("url")}
        bundle_urls = {r.url for r in bundle.canonical_results if r.url}
        assert recorded_urls == bundle_urls, f"URL drift in {s.case_id}"
