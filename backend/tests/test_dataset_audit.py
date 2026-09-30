from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from backend.scripts.audit_datasets import REPO_ROOT, audit_datasets, format_summary, main


def _snapshot(case_id: str, *, split: str | None = None, topic: str | None = None,
              url: str | None = None, quarantined: bool = False, public: bool = False) -> dict:
    metadata = {"provenance": "synthetic"}
    if split is not None:
        metadata["evaluation_split"] = split
    if topic is not None:
        metadata["topic_group"] = topic
    if quarantined:
        metadata.update(review_status="quarantined", review_reason="source excerpt needs review")
    if public:
        metadata.update(provenance="public_dataset", source_case_id=0, source_revision="fixed-revision",
                        annotation_source="upstream_label", original_label="NOT ENOUGH INFO", original_claim="原始断言")
    return {
        "case_id": case_id, "recorded_at": "2026-09-13T00:00:00Z", "raw_input": "待核查的断言",
        "retrieval_results": [] if url is None else [{"result_id": "source_1", "url": url, "published_at": ""}],
        "expected_claims": [{"claim": "待核查的断言", "verdict": "insufficient", "confidence": "low", "evidence": []}],
        "metadata": metadata,
    }


def _write(root: Path, group: str, snapshot: dict, filename: str | None = None) -> Path:
    directory = root / group
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (filename or f"{snapshot['case_id']}.json")
    path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
    return path


def _codes(report: dict) -> set[str]:
    return {error["code"] for error in report["errors"]}


def test_audit_accepts_dateless_evidence_and_empty_nei(tmp_path):
    _write(tmp_path, "fixture", _snapshot("dateless", url="https://example.org/evidence"))
    _write(tmp_path, "fixture", _snapshot("empty"))
    report = audit_datasets(tmp_path)
    assert report["status"] == "passed"
    assert not report["errors"]
    assert report["groups"]["fixture"]["nonempty_insufficient_claims"] == 1
    assert report["groups"]["fixture"]["label_counts"] == {"insufficient": 2}
    assert {warning["code"] for warning in report["warnings"]} >= {"small_sample", "label_imbalance"}


def test_audit_rejects_topic_leakage_across_directories(tmp_path):
    _write(tmp_path, "first", _snapshot("first", split="development", topic="same-topic"))
    _write(tmp_path, "second", _snapshot("second", split="holdout", topic="same-topic"))
    report = audit_datasets(tmp_path)
    assert report["status"] == "invalid"
    assert "topic_split_leakage" in _codes(report)


def test_audit_rejects_evidence_url_leakage_even_for_quarantine(tmp_path):
    _write(tmp_path, "first", _snapshot("first", split="development", topic="one",
                                       url="https://EXAMPLE.org/evidence/#section"))
    _write(tmp_path, "second", _snapshot("second", split="holdout", topic="two",
                                        url="https://example.org/evidence", quarantined=True))
    assert "evidence_split_leakage" in _codes(audit_datasets(tmp_path))


def test_same_topic_and_url_within_one_split_are_allowed(tmp_path):
    for case_id in ("first", "second"):
        _write(tmp_path, "group", _snapshot(case_id, split="development", topic="same-topic",
                                           url="https://example.org/same"))
    assert not audit_datasets(tmp_path)["errors"]


def test_audit_rejects_global_duplicate_ids(tmp_path):
    _write(tmp_path, "first", _snapshot("duplicate"))
    _write(tmp_path, "second", _snapshot("duplicate"))
    assert "duplicate_case_id" in _codes(audit_datasets(tmp_path))


def test_audit_reports_duplicate_and_filename_error_within_one_group(tmp_path):
    _write(tmp_path, "group", _snapshot("duplicate"))
    _write(tmp_path, "group", _snapshot("duplicate"), filename="wrong_name.json")
    assert _codes(audit_datasets(tmp_path)) >= {"duplicate_case_id", "filename_mismatch"}


@pytest.mark.parametrize("split,topic,code", [
    ("test", "topic", "invalid_evaluation_split"),
    ("development", None, "missing_topic_group"),
    ("holdout", " ", "missing_topic_group"),
])
def test_audit_requires_valid_split_and_topic(tmp_path, split, topic, code):
    _write(tmp_path, "group", _snapshot("case", split=split, topic=topic))
    assert code in _codes(audit_datasets(tmp_path))


@pytest.mark.parametrize("missing", ["source_case_id", "source_revision", "annotation_source", "original_label", "original_claim"])
def test_audit_rejects_missing_public_provenance(tmp_path, missing):
    snapshot = _snapshot("public", public=True)
    del snapshot["metadata"][missing]
    _write(tmp_path, "group", snapshot)
    assert "missing_public_provenance" in _codes(audit_datasets(tmp_path))


def test_audit_accepts_public_case_zero_and_extra_provenance_keys(tmp_path):
    snapshot = _snapshot("public", public=True)
    snapshot["metadata"].update(original_source_record={"id": 0}, source_record_line=1)
    _write(tmp_path, "group", snapshot)
    assert not audit_datasets(tmp_path)["errors"]


def test_quarantine_is_not_silently_scored_or_reported_as_success(tmp_path, capsys):
    _write(tmp_path, "group", _snapshot("pending", quarantined=True))
    report = audit_datasets(tmp_path)
    assert report["status"] == "unscorable"
    assert report["totals"]["total"] == 1
    assert report["totals"]["scored"] == 0
    assert report["totals"]["label_counts"] == {}
    assert report["totals"]["majority_label_baseline"]["accuracy"] is None
    assert report["totals"]["quarantined"] == [{"case_id": "pending", "reason": "source excerpt needs review"}]
    assert "N/A" in format_summary(report)
    assert main(["--root", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "unscorable"


def test_legacy_aggregate_is_reported_but_not_counted(tmp_path):
    path = _write(tmp_path, "group", _snapshot("case"))
    (path.parent / "cases.json").write_text(json.dumps([_snapshot("case")]), encoding="utf-8")
    report = audit_datasets(tmp_path)
    assert report["totals"]["total"] == 1
    assert not report["errors"]
    assert "legacy_aggregate" in {warning["code"] for warning in report["warnings"]}


@pytest.mark.parametrize("payload", ["{broken", "[]", '{"case_id":"missing-fields"}'])
def test_malformed_snapshot_cannot_disappear_from_audit(tmp_path, payload):
    path = _write(tmp_path, "group", _snapshot("valid"))
    (path.parent / "invalid.json").write_text(payload, encoding="utf-8")
    report = audit_datasets(tmp_path)
    assert "invalid_snapshot" in _codes(report)
    assert report["totals"]["total"] == 2
    assert report["totals"]["scored"] == 1
    assert report["totals"]["invalid"] == 1


def test_cli_fails_for_invalid_corpus(tmp_path, capsys):
    _write(tmp_path, "group", _snapshot("case", split="unknown"))
    assert main(["--root", str(tmp_path), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "invalid"


def test_missing_root_and_empty_corpus_are_errors(tmp_path):
    assert "missing_root" in _codes(audit_datasets(tmp_path / "missing"))
    assert "empty_corpus" in _codes(audit_datasets(tmp_path))


def test_real_five_corpora_pass_and_report_expected_coverage():
    report = audit_datasets(REPO_ROOT / "evals" / "live_replay")
    assert report["errors"] == []
    assert report["status"] == "passed"
    assert set(report["groups"]) == {"seed", "hard", "context_challenge", "cfever_curated", "covid19_health_rumor_curated"}
    assert report["totals"]["total"] == 56
    assert report["totals"]["scored"] == 56
    assert report["groups"]["cfever_curated"]["evaluation_split_counts"] == {"development": 12, "holdout": 12}
    assert report["groups"]["covid19_health_rumor_curated"]["majority_label_baseline"]["accuracy"] == 0.875


def test_cli_uses_only_standard_library(tmp_path):
    _write(tmp_path, "group", _snapshot("case"))
    result = subprocess.run(
        [sys.executable, "-S", str(REPO_ROOT / "backend/scripts/audit_datasets.py"), "--root", str(tmp_path), "--json"],
        check=True, capture_output=True, text=True, cwd=tmp_path,
    )
    assert json.loads(result.stdout)["status"] == "passed"


def test_audit_accepts_converter_default_adjacent_manifest(tmp_path):
    from backend.scripts.convert_cfever import DEFAULT_RECORDED_AT, convert_dataset

    root = tmp_path / "replay"
    _write(root, "seed", _snapshot("seed_case"))
    records = [
        {"id": 1, "claim": "支持断言", "label": "supports", "evidence": [[[1, 1, "页面", 0]]]},
        {"id": 2, "claim": "反驳断言", "label": "refutes", "evidence": [[[1, 1, "页面", 0]]]},
        {"id": 3, "claim": "不足断言", "label": "NOT ENOUGH INFO", "evidence": []},
    ]
    claims_path = tmp_path / "claims.jsonl"
    claims_path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
    (tmp_path / "wiki-001.jsonl").write_text(json.dumps({"id": "页面", "lines": "0\t证据句"}), encoding="utf-8")
    convert_dataset(claims_path=claims_path, wiki_dir=tmp_path, output_dir=root / "cfever",
                    per_label=1, split="dev", recorded_at=DEFAULT_RECORDED_AT, allow_unverified=True)
    report = audit_datasets(root)
    assert report["errors"] == []
    assert report["status"] == "passed"
    assert report["totals"]["total"] == 4
    assert report["totals"]["scored"] == 1
    assert set(report["groups"]) == {"seed", "cfever"}
    assert report["excluded_metadata_count"] == 1
    assert report["excluded_metadata"][0]["path"] == "cfever.manifest.json"
    assert "Excluded metadata: 1" in format_summary(report)


@pytest.mark.parametrize("payload", ["{broken", "{}", json.dumps(_snapshot("disguised"))])
def test_manifest_suffix_does_not_hide_invalid_or_disguised_snapshots(tmp_path, payload):
    _write(tmp_path, "seed", _snapshot("case"))
    (tmp_path / "bad.manifest.json").write_text(payload, encoding="utf-8")
    report = audit_datasets(tmp_path)
    assert "invalid_manifest" in _codes(report)
    assert report["status"] == "invalid"
    assert report["excluded_metadata_count"] == 0


def test_audit_does_not_ignore_plain_root_json(tmp_path):
    _write(tmp_path, "seed", _snapshot("case"))
    (tmp_path / "ordinary.json").write_text("{}", encoding="utf-8")
    report = audit_datasets(tmp_path)
    assert "invalid_snapshot" in _codes(report)
    assert report["totals"]["invalid"] == 1
