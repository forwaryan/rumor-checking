"""Tests for the eval recorder and FEVER scoring framework."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from backend.app.services.eval_recorder import (
    EvalSnapshot,
    evaluate_batch,
    fever_score_claim,
    load_snapshot,
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
