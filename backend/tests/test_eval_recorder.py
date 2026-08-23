"""Tests for the eval recorder and FEVER scoring framework."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from backend.app.services.eval_recorder import (
    EvalSnapshot,
    category_metric_deltas,
    evaluate_batch,
    fever_score_claim,
    load_snapshot,
    metric_deltas,
    record_snapshot,
)


def test_fever_score_both_correct():
    score = fever_score_claim(
        expected_verdict="supported",
        actual_verdict="supported",
        expected_evidence_urls={"https://a.com/1"},
        actual_evidence_urls={"https://a.com/1", "https://b.com/2"},
    )
    assert score.label_correct is True
    assert score.evidence_correct is True
    assert score.fever_pass is True


def test_fever_score_label_wrong():
    score = fever_score_claim(
        expected_verdict="refuted",
        actual_verdict="supported",
        expected_evidence_urls={"https://a.com/1"},
        actual_evidence_urls={"https://a.com/1"},
    )
    assert score.label_correct is False
    assert score.evidence_correct is True
    assert score.fever_pass is False


def test_fever_score_evidence_wrong():
    score = fever_score_claim(
        expected_verdict="supported",
        actual_verdict="supported",
        expected_evidence_urls={"https://a.com/1"},
        actual_evidence_urls={"https://other.com/2"},
    )
    assert score.label_correct is True
    assert score.evidence_correct is False
    assert score.fever_pass is False


def test_fever_score_no_expected_evidence():
    score = fever_score_claim(
        expected_verdict="insufficient",
        actual_verdict="insufficient",
        expected_evidence_urls=set(),
        actual_evidence_urls=set(),
    )
    assert score.fever_pass is True


def test_record_and_load_snapshot():
    with tempfile.TemporaryDirectory() as tmp:
        path = record_snapshot(
            case_id="test_001",
            raw_input="樊振东回归国家队了吗",
            retrieval_results=[{"result_id": "r1", "title": "test"}],
            claim_results=[{"claim": "樊振东回归", "verdict": "supported", "evidence": []}],
            output_dir=Path(tmp),
            metadata={"source": "test"},
        )
        assert path.exists()
        snapshot = load_snapshot(path)
        assert snapshot.case_id == "test_001"
        assert snapshot.raw_input == "樊振东回归国家队了吗"
        assert len(snapshot.retrieval_results) == 1
        assert len(snapshot.expected_claims) == 1


def test_evaluate_batch_computes_metrics():
    snapshot = EvalSnapshot(
        case_id="batch_test",
        recorded_at="2026-08-01T00:00:00Z",
        raw_input="test",
        retrieval_results=[],
        expected_claims=[
            {"claim": "A", "verdict": "supported", "evidence": [{"url": "https://a.com"}]},
            {"claim": "B", "verdict": "refuted", "evidence": [{"url": "https://b.com"}]},
        ],
        metadata={},
    )
    actual = [
        {"claim": "A", "verdict": "supported", "evidence": [{"url": "https://a.com"}]},
        {"claim": "B", "verdict": "supported", "evidence": [{"url": "https://b.com"}]},  # wrong label
    ]
    report = evaluate_batch([snapshot], [actual])
    assert report.total_claims == 2
    assert report.label_accuracy == 0.5
    assert report.evidence_accuracy == 1.0
    assert report.fever_score == 0.5
    assert report.per_case[0]["fever_pass"] == 1


def test_evaluate_batch_reports_fact_check_quality_metrics():
    snapshot = EvalSnapshot(
        case_id="quality_test",
        recorded_at="2026-08-01T00:00:00Z",
        raw_input="test",
        retrieval_results=[
            {
                "url": "https://official.example/current",
                "source_name": "Official Agency",
                "source_tier": "S",
                "published_at": "2026-07-20",
            },
            {
                "url": "https://media.example/report",
                "source_name": "Independent Media",
                "source_tier": "A",
                "published_at": "2026-07-21",
            },
            {
                "url": "https://repost.example/copy",
                "source_name": "Official Agency",
                "source_tier": "C",
                "published_at": "",
            },
        ],
        expected_claims=[
            {
                "claim": "A",
                "verdict": "refuted",
                "confidence": "high",
                "evidence": [{"url": "https://official.example/current"}],
                "evaluation": {
                    "min_independent_sources": 2,
                    "require_high_trust": True,
                    "require_dated_evidence": True,
                    "fresh_after": "2026-07-01",
                },
            }
        ],
        metadata={"categories": ["time_sensitive", "subject_mismatch"]},
    )
    actual = [{
        "claim": "A",
        "verdict": "supported",
        "confidence": "medium",
        "evidence": [
            {"url": "https://official.example/current"},
            {"url": "https://repost.example/copy"},
        ],
    }]

    report = evaluate_batch([snapshot], [actual])

    assert report.confidence_accuracy == 0.0
    assert report.citation_precision == 0.5
    assert report.source_independence_score == 0.5
    assert report.high_trust_evidence_rate == 0.5
    assert report.dated_evidence_rate == 0.5
    assert report.fresh_evidence_rate == 0.5
    assert report.category_metrics["time_sensitive"]["label_accuracy"] == 0.0
    assert report.category_metrics["subject_mismatch"]["total_claims"] == 1
    assert report.per_case[0]["failure_reasons"] == [
        "wrong_label",
        "confidence_mismatch",
        "low_source_diversity",
        "undated_evidence",
        "stale_evidence",
    ]


def test_evaluate_batch_counts_missing_actual_claim_as_failure():
    snapshot = EvalSnapshot(
        case_id="missing_claim",
        recorded_at="2026-08-01T00:00:00Z",
        raw_input="test",
        retrieval_results=[],
        expected_claims=[
            {"claim": "A", "verdict": "supported", "evidence": []},
            {"claim": "B", "verdict": "refuted", "evidence": []},
        ],
        metadata={"category": "coverage"},
    )

    report = evaluate_batch(
        [snapshot],
        [[{"claim": "A", "verdict": "supported", "evidence": []}]],
    )

    assert report.total_claims == 2
    assert report.label_accuracy == 0.5
    assert report.per_case[0]["failure_reasons"] == ["missing_claim"]
    assert report.category_metrics["coverage"]["fever_score"] == 0.5


def test_metric_deltas_compare_rule_or_model_runs():
    deltas = metric_deltas(
        {"label_accuracy": 0.8, "fever_score": 0.7},
        {"label_accuracy": 0.5, "fever_score": 0.6},
    )

    assert deltas["label_accuracy"] == pytest.approx(0.3)
    assert deltas["fever_score"] == pytest.approx(0.1)


def test_freshness_requirement_does_not_call_empty_evidence_stale():
    snapshot = EvalSnapshot(
        case_id="no_evidence",
        recorded_at="2026-08-01T00:00:00Z",
        raw_input="test",
        retrieval_results=[],
        expected_claims=[{
            "claim": "A",
            "verdict": "insufficient",
            "evidence": [],
            "evaluation": {"fresh_after": "2026-07-01"},
        }],
        metadata={},
    )

    report = evaluate_batch(
        [snapshot],
        [[{"claim": "A", "verdict": "insufficient", "evidence": []}]],
    )

    assert "stale_evidence" not in report.per_case[0]["failure_reasons"]


def test_category_metric_deltas_expose_local_regressions():
    deltas = category_metric_deltas(
        {"time_sensitive": {"total_claims": 2, "fever_score": 0.5}},
        {
            "time_sensitive": {"total_claims": 2, "fever_score": 1.0},
            "subject_mismatch": {"total_claims": 1, "fever_score": 1.0},
        },
    )

    assert deltas["time_sensitive"]["fever_score"] == -0.5
    assert deltas["subject_mismatch"]["fever_score"] == -1.0
