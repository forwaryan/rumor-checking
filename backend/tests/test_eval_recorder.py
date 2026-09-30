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
    iter_snapshots,
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
            retrieval_results=[{"result_id": "r1", "title": "test", "url": "https://a.com"}],
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
    assert report.confidence_scored_claims == 1
    assert report.source_independence_scored_claims == 1
    assert report.freshness_scored_evidence == 2
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
    assert report.per_case[0]["failure_reasons"] == ["missing_expected_evidence", "missing_claim"]
    assert report.category_metrics["coverage"]["fever_score"] == 0.0


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


def test_fever_requires_the_complete_gold_evidence_group():
    score = fever_score_claim(
        expected_verdict="conflicting",
        actual_verdict="conflicting",
        expected_evidence_urls={"https://a.com", "https://b.com"},
        actual_evidence_urls={"https://a.com"},
    )
    assert score.evidence_correct is False
    assert score.fever_pass is False


@pytest.mark.parametrize("verdict", ["supported", "refuted", "conflicting"])
def test_non_nei_empty_gold_does_not_receive_full_credit(verdict):
    score = fever_score_claim(
        expected_verdict=verdict,
        actual_verdict=verdict,
        expected_evidence_urls=set(),
        actual_evidence_urls=set(),
    )
    assert score.fever_pass is False


def _scoring_snapshot(claims):
    return EvalSnapshot(
        case_id="scoring", recorded_at="2026-09-01T00:00:00Z", raw_input="example",
        retrieval_results=[], expected_claims=claims, metadata={},
    )


@pytest.mark.parametrize("urls, expected_pass", [
    (["https://a.com"], False),
    (["https://b.com", "https://a.com"], True),
    (["https://c.com"], True),
])
def test_alternative_evidence_sets_accept_any_complete_group(urls, expected_pass):
    expected = {
        "claim": "A", "verdict": "supported", "evidence": [{"url": "https://a.com"}],
        "evidence_sets": [
            [{"url": "https://a.com"}, {"url": "https://b.com"}],
            [{"url": "https://c.com"}],
        ],
    }
    actual = {"claim": "A", "verdict": "supported", "evidence": [{"url": url} for url in urls]}
    report = evaluate_batch([_scoring_snapshot([expected])], [[actual]])
    assert report.fever_score == float(expected_pass)
    assert report.citation_precision == 1.0


def test_claim_alignment_handles_reordering_and_normalized_text():
    expected = [
        {"claim": "Ａ  B", "claim_type": "fact", "verdict": "insufficient", "evidence": []},
        {"claim": "C", "claim_type": "prediction", "verdict": "refuted", "evidence": [{"url": "https://c.com"}]},
    ]
    actual = [expected[1], {**expected[0], "claim": "A B"}]
    report = evaluate_batch([_scoring_snapshot(expected)], [actual])
    assert report.fever_score == 1.0
    assert report.per_case[0]["failure_reasons"] == []


@pytest.mark.parametrize("actual_claim, actual_type", [("unrelated", "fact"), ("A", "opinion")])
def test_unrelated_or_wrong_type_claim_is_missing_and_extra(actual_claim, actual_type):
    expected = {"claim": "A", "claim_type": "fact", "verdict": "insufficient", "evidence": []}
    actual = {**expected, "claim": actual_claim, "claim_type": actual_type}
    report = evaluate_batch([_scoring_snapshot([expected])], [[actual]])
    assert report.label_accuracy == 0.0
    assert report.per_case[0]["failure_reasons"] == ["missing_claim", "unexpected_claim"]
    assert report.per_case[0]["unexpected_claims"] == [{"claim": actual_claim, "claim_type": actual_type}]


def test_annotator_confidence_can_be_excluded_from_gold_metric():
    expected = {
        "claim": "A", "verdict": "insufficient", "evidence": [], "confidence": "high",
        "evaluation": {"score_confidence": False},
    }
    other = {**expected, "claim": "B", "evaluation": {}}
    actual = [{**expected, "confidence": "low"}, other]
    report = evaluate_batch([_scoring_snapshot([expected, other])], [actual])
    assert report.confidence_accuracy == 1.0
    assert "confidence_mismatch" not in report.per_case[0]["failure_reasons"]


def test_origin_identity_prevents_repost_source_inflation():
    evidence = [{"url": "https://a.com"}, {"url": "https://b.com"}]
    expected = {"claim": "A", "verdict": "supported", "evidence": evidence,
                "evaluation": {"min_independent_sources": 2}}
    snapshot = _scoring_snapshot([expected])
    snapshot.retrieval_results = [
        {**evidence[0], "origin_id": "wire-1", "source_name": "Paper A"},
        {**evidence[1], "origin_id": "wire-1", "source_name": "Paper B"},
    ]
    actual = {**expected, "evidence": [
        {**evidence[0], "origin_id": "fake-one"},
        {**evidence[1], "origin_id": "fake-two"},
    ]}
    report = evaluate_batch([snapshot], [[actual]])
    assert report.source_independence_score == 0.5
    assert "low_source_diversity" in report.per_case[0]["failure_reasons"]


def test_recorded_model_output_is_quarantined_until_review(tmp_path):
    path = record_snapshot(
        case_id="recorded", raw_input="A", retrieval_results=[],
        claim_results=[{"claim": "A", "verdict": "insufficient", "evidence": []}],
        output_dir=tmp_path,
    )
    snapshot = load_snapshot(path)
    assert snapshot.metadata["review_status"] == "quarantined"
    assert snapshot.metadata["review_reason"] == "unreviewed_model_output"
    assert iter_snapshots(tmp_path) == []
    assert iter_snapshots(tmp_path, include_quarantined=True) == [snapshot]


def test_quarantined_expected_outputs_do_not_affect_batch_denominator():
    active = _scoring_snapshot([{"claim": "A", "verdict": "insufficient", "evidence": []}])
    excluded = _scoring_snapshot([{"claim": "B", "verdict": "refuted", "evidence": []}])
    excluded.case_id = "quarantined"
    excluded.metadata = {"review_status": "quarantined", "review_reason": "unreviewed_model_output"}
    report = evaluate_batch([excluded, active], [[], active.expected_claims])
    assert report.total_claims == 1
    assert report.fever_score == 1.0
    assert report.total_snapshot_count == 2
    assert report.scored_snapshot_count == 1
    assert report.excluded_snapshots == [{"case_id": "quarantined", "reason": "unreviewed_model_output"}]


def test_unrecorded_source_metadata_does_not_create_independence():
    expected = {"claim": "A", "verdict": "insufficient", "evidence": [],
                "evaluation": {"min_independent_sources": 1}}
    actual = {**expected, "evidence": [{"url": "https://invented.com", "source_name": "Invented source"}]}
    report = evaluate_batch([_scoring_snapshot([expected])], [[actual]])
    assert report.source_independence_score == 0.0


def test_recording_invalid_structure_does_not_poison_the_corpus(tmp_path):
    with pytest.raises(ValueError, match="verdict"):
        record_snapshot(
            case_id="broken", raw_input="A", retrieval_results=[],
            claim_results=[{"claim": "A", "verdict": "typo", "evidence": []}],
            output_dir=tmp_path,
        )
    assert not (tmp_path / "broken.json").exists()


def test_all_confidence_disabled_retains_legacy_zero_with_zero_observations():
    expected = {"claim": "A", "verdict": "insufficient", "evidence": [], "confidence": "high",
                "evaluation": {"score_confidence": False}}
    report = evaluate_batch([_scoring_snapshot([expected])], [[{**expected, "confidence": "low"}]])
    assert report.confidence_accuracy == 0.0
    assert report.confidence_scored_claims == 0
    assert report.source_independence_scored_claims == 0
    assert report.freshness_scored_evidence == 0
    assert "confidence_mismatch" not in report.per_case[0]["failure_reasons"]


@pytest.mark.parametrize("case_id", ["../escaped", "..", ".", "folder/case", "folder\\case", "", "/absolute", "bad\x00id"])
def test_recording_rejects_unsafe_case_ids_before_writing(tmp_path, case_id, monkeypatch):
    monkeypatch.setattr(Path, "write_text", lambda *_args, **_kwargs: pytest.fail("unsafe write attempted"))
    with pytest.raises(ValueError, match="case_id"):
        record_snapshot(
            case_id=case_id, raw_input="A", retrieval_results=[],
            claim_results=[{"claim": "A", "verdict": "insufficient", "evidence": []}],
            output_dir=tmp_path,
        )
    assert not list(tmp_path.iterdir())


def test_nei_empty_alternatives_cannot_bypass_nonempty_legacy_gold():
    score = fever_score_claim(
        expected_verdict="insufficient", actual_verdict="insufficient",
        expected_evidence_urls={"https://a.com"}, actual_evidence_urls=set(), expected_evidence_sets=[],
    )
    assert not score.evidence_correct
    assert not score.fever_pass
    expected = {"claim": "A", "verdict": "insufficient", "evidence": [{"url": "https://a.com"}],
                "evidence_sets": []}
    actual = {"claim": "A", "verdict": "insufficient", "evidence": []}
    report = evaluate_batch([_scoring_snapshot([expected])], [[actual]])
    assert report.fever_score == 0.0
    assert report.citation_precision == 0.0


def test_actual_citations_cannot_forge_unrecorded_trust_or_dates():
    expected = {"claim": "A", "verdict": "supported", "evidence": [{"url": "https://known.com"}],
                "evaluation": {"require_high_trust": True, "require_dated_evidence": True,
                               "fresh_after": "2026-01-01", "min_independent_sources": 2}}
    snapshot = _scoring_snapshot([expected])
    snapshot.retrieval_results = [{"url": "https://known.com"}]
    actual = {**expected, "evidence": [
        {"url": url, "source_tier": "S", "published_at": "2026-09-01", "origin_id": url,
         "source_name": url}
        for url in ("https://known.com", "https://unknown.com")
    ]}
    report = evaluate_batch([snapshot], [[actual]])
    assert report.high_trust_evidence_rate == 0.0
    assert report.dated_evidence_rate == 0.0
    assert report.fresh_evidence_rate == 0.0
    assert report.source_independence_score == 0.0
    assert {"no_high_trust_evidence", "undated_evidence", "stale_evidence"} <= set(report.per_case[0]["failure_reasons"])
