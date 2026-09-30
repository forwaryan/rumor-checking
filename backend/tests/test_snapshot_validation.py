import copy
import json
from pathlib import Path

import pytest

from backend.app.services.eval_recorder import evaluate_batch, fever_score_claim, iter_snapshots, load_snapshot


@pytest.fixture
def snapshot_payload():
    return {
        "case_id": "valid", "recorded_at": "2026-08-01T00:00:00Z", "raw_input": "A",
        "retrieval_results": [{"result_id": "r1", "url": "https://a.com", "published_at": ""}],
        "expected_claims": [{"claim": "A", "claim_type": "fact", "verdict": "supported",
                             "evidence": [{"url": "https://a.com"}]}],
        "metadata": {"provenance": "synthetic"},
    }


def _write_snapshot(directory, payload, name="case.json"):
    path = directory / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.mark.parametrize("mutation, reason", [
    (lambda value: value.update(metadata=[]), "metadata"),
    (lambda value: value.update(recorded_at="not-a-date"), "recorded_at"),
    (lambda value: value["metadata"].update(review_status="quaratined"), "review_status"),
    (lambda value: value["metadata"].update(review_status="quarantined"), "review_reason"),
    (lambda value: value.update(expected_claims=[]), "expected_claims"),
    (lambda value: value["expected_claims"][0].update(verdict="unknown"), "verdict"),
    (lambda value: value["expected_claims"][0].update(claim_type="unknown"), "claim_type"),
    (lambda value: value["retrieval_results"].append(copy.deepcopy(value["retrieval_results"][0])), "result_id"),
    (lambda value: value["retrieval_results"][0].update(source_tier=[]), "source_tier"),
    (lambda value: value["retrieval_results"][0].update(published_at="yesterday"), "published_at"),
    (lambda value: value["expected_claims"][0]["evidence"][0].update(published_at="yesterday"), "published_at"),
    (lambda value: value["expected_claims"][0].update(evidence=[{"url": "https://absent.com"}]), "retrieval"),
    (lambda value: value["expected_claims"][0].update(evidence_sets=[[{"url": "https://absent.com"}]]), "retrieval"),
    (lambda value: value["expected_claims"][0].update(evidence_sets=[[]]), "evidence_sets"),
    (lambda value: value["expected_claims"][0].update(evidence=[]), "evidence"),
    (lambda value: value["expected_claims"][0].update(verdict="insufficient", evidence_sets=[]), "evidence_sets"),
    (lambda value: value["expected_claims"][0].update(evaluation={"score_confidence": "false"}), "score_confidence"),
    (lambda value: value["expected_claims"][0].update(evaluation={"fresh_after": "invalid"}), "fresh_after"),
])
def test_malformed_snapshots_fail_with_file_and_field(tmp_path, snapshot_payload, mutation, reason):
    mutation(snapshot_payload)
    path = _write_snapshot(tmp_path, snapshot_payload)
    with pytest.raises(ValueError, match=reason) as error:
        iter_snapshots(tmp_path)
    assert str(path) in str(error.value)


def test_bad_json_is_not_silently_dropped(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError, match="broken.json"):
        iter_snapshots(tmp_path)


def test_duplicate_case_id_fails_even_when_one_is_quarantined(tmp_path, snapshot_payload):
    _write_snapshot(tmp_path, snapshot_payload)
    snapshot_payload["metadata"].update(review_status="quarantined", review_reason="needs_review")
    _write_snapshot(tmp_path, snapshot_payload, "other.json")
    with pytest.raises(ValueError, match="duplicate case_id"):
        iter_snapshots(tmp_path)


def test_quarantine_excludes_only_after_structure_validation(tmp_path, snapshot_payload):
    snapshot_payload["metadata"].update(review_status="quarantined", review_reason="needs_review")
    snapshot_payload["expected_claims"][0]["verdict"] = "invalid"
    _write_snapshot(tmp_path, snapshot_payload)
    with pytest.raises(ValueError, match="verdict"):
        iter_snapshots(tmp_path)


def test_dateless_counterexample_remains_valid():
    path = Path(__file__).resolve().parents[2] / "evals/live_replay/seed/seed_015_dateless_evidence.json"
    snapshot = load_snapshot(path)
    assert snapshot.retrieval_results[0]["published_at"] == ""
    assert snapshot.expected_claims[0]["verdict"] == "insufficient"


@pytest.mark.parametrize("review_status", ["approved", "reviewed"])
def test_approved_and_legacy_reviewed_snapshots_are_scored(tmp_path, snapshot_payload, review_status):
    snapshot_payload["metadata"]["review_status"] = review_status
    _write_snapshot(tmp_path, snapshot_payload)
    snapshots = iter_snapshots(tmp_path)
    assert len(snapshots) == 1
    assert evaluate_batch(snapshots, [snapshots[0].expected_claims]).fever_score == 1.0


@pytest.mark.parametrize("label, evidence, pages", [
    ("supports", [[[7, 8, "頁面", 2]]], {"頁面": {2: "原始證據"}}),
    ("NOT ENOUGH INFO", [[None, None, None, None]], {}),
])
def test_converter_output_loads_and_scores_under_snapshot_contract(tmp_path, label, evidence, pages):
    from backend.scripts.convert_cfever import build_snapshot

    payload = build_snapshot(
        {"id": 1, "label": label, "claim": "待核查主張", "evidence": evidence, "domain": "測試"},
        pages, split="dev", recorded_at="2026-09-01T00:00:00Z", source_verified=True,
    )
    assert payload["metadata"]["review_status"] == "approved"
    snapshot = load_snapshot(_write_snapshot(tmp_path, payload))
    if label == "NOT ENOUGH INFO":
        assert snapshot.expected_claims[0]["evidence_sets"] == []
    report = evaluate_batch([snapshot], [snapshot.expected_claims])
    assert report.fever_score == 1.0
    assert report.confidence_scored_claims == 0


@pytest.mark.parametrize("verdict", ["supported", "refuted", "conflicting"])
def test_non_nei_empty_outer_evidence_groups_are_rejected(tmp_path, snapshot_payload, verdict):
    snapshot_payload["expected_claims"][0].update(verdict=verdict, evidence_sets=[])
    with pytest.raises(ValueError, match="evidence_sets"):
        load_snapshot(_write_snapshot(tmp_path, snapshot_payload))
    assert not fever_score_claim(
        expected_verdict=verdict, actual_verdict=verdict,
        expected_evidence_urls={"https://a.com"}, actual_evidence_urls={"https://a.com"},
        expected_evidence_sets=[],
    ).fever_pass


@pytest.mark.parametrize("published_at", ["", "2026-08-01", "2026-08-01T12:30:00Z", "2026-08-01T12:30:00+08:00"])
def test_published_at_accepts_empty_date_or_iso_timestamp(tmp_path, snapshot_payload, published_at):
    snapshot_payload["retrieval_results"][0]["published_at"] = published_at
    snapshot = load_snapshot(_write_snapshot(tmp_path, snapshot_payload))
    assert snapshot.retrieval_results[0]["published_at"] == published_at
