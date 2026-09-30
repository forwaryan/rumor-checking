import json
from dataclasses import asdict
from pathlib import Path

import pytest

from backend.app.services.eval_recorder import EvalSnapshot
from backend.scripts.replay_eval import build_run_manifest


def test_run_manifest_fingerprints_corpus_code_and_configuration(tmp_path: Path, monkeypatch):
    snapshot_path = tmp_path / "case-1.json"
    snapshot_path.write_text('{"case_id":"case-1"}\n', encoding="utf-8")
    snapshot = EvalSnapshot(
        case_id="case-1",
        recorded_at="2026-01-01T00:00:00+00:00",
        raw_input="example",
        retrieval_results=[],
        expected_claims=[],
        metadata={},
    )
    monkeypatch.setenv("GITHUB_SHA", "abc123")

    manifest = build_run_manifest(
        snap_dir=tmp_path,
        snapshots=[snapshot],
        run_name="test-run",
    )

    assert manifest["schema_version"] == 1
    assert manifest["name"] == "test-run"
    assert manifest["engine"] == "rule"
    assert manifest["snapshot_count"] == 1
    assert manifest["git"]["sha"] == "abc123"
    assert manifest["corpus"]["snapshot_count"] == 1
    assert manifest["corpus"]["case_ids"] == ["case-1"]
    assert len(manifest["corpus"]["sha256"]) == 64
    assert len(manifest["implementation"]["sha256"]) == 64
    assert len(manifest["configuration_sha256"]) == 64
    assert manifest["configuration"]["network_access"] is False


def test_run_manifest_redacts_external_corpus_path(tmp_path: Path):
    manifest = build_run_manifest(snap_dir=tmp_path, snapshots=[], run_name="external")

    assert manifest["corpus"]["path"] == f"external:{tmp_path.name}"
    assert str(tmp_path.parent) not in manifest["corpus"]["path"]


def test_run_manifest_labels_llm_engine_as_network_bound(tmp_path: Path):
    manifest = build_run_manifest(
        snap_dir=tmp_path, snapshots=[], run_name="llm-run", engine="llm"
    )

    assert manifest["engine"] == "llm"
    assert manifest["implementation"]["engine"] == "llm"
    assert manifest["configuration"]["engine"] == "llm"
    assert manifest["configuration"]["analysis_provider"] == "kimi"
    assert manifest["configuration"]["network_access"] is True


def test_quarantine_denominators_and_scoring_protocol_are_explicit(tmp_path):
    snapshot = EvalSnapshot(
        case_id="excluded", recorded_at="2026-08-01T00:00:00Z", raw_input="A",
        retrieval_results=[],
        expected_claims=[{"claim": "A", "verdict": "insufficient", "evidence": []}],
        metadata={"review_status": "quarantined", "review_reason": "truncated_evidence"},
    )
    manifest = build_run_manifest(snap_dir=tmp_path, snapshots=[snapshot], run_name="quarantined")
    assert manifest["snapshot_count"] == 0
    assert manifest["total_snapshot_count"] == 1
    assert manifest["scored_snapshot_count"] == 0
    assert manifest["excluded_snapshots"] == [{"case_id": "excluded", "reason": "truncated_evidence"}]
    assert manifest["corpus"]["excluded_snapshots"] == manifest["excluded_snapshots"]
    assert manifest["scoring_version"] == "url-evidence-groups-v2"
    assert manifest["evaluation_protocol"] == "gold_claims_supplied_evidence"
    assert manifest["evidence_granularity"] == "url"


def test_cli_reports_quarantine_and_does_not_replay_it(tmp_path, monkeypatch, capsys):
    from backend.scripts import replay_eval

    snapshot = EvalSnapshot(
        case_id="excluded", recorded_at="2026-08-01T00:00:00Z", raw_input="A",
        retrieval_results=[],
        expected_claims=[{"claim": "A", "verdict": "insufficient", "evidence": []}],
        metadata={"review_status": "quarantined", "review_reason": "truncated_evidence"},
    )
    (tmp_path / "case.json").write_text(json.dumps(asdict(snapshot)), encoding="utf-8")
    monkeypatch.setattr(replay_eval.sys, "argv", ["replay_eval.py", "--dir", str(tmp_path), "--json"])
    monkeypatch.setattr(replay_eval, "_replay_one", lambda _: pytest.fail("quarantine was replayed"))
    assert replay_eval.main() == 2
    output = capsys.readouterr()
    assert "no scoreable snapshots" in output.err
    report = json.loads(output.out)
    assert report["total_snapshot_count"] == 1
    assert report["scored_snapshot_count"] == 0
    assert report["excluded_snapshots"] == [{"case_id": "excluded", "reason": "truncated_evidence"}]
    assert report["run"]["corpus"]["total_snapshot_count"] == 1


def test_cli_rejects_malformed_corpus(tmp_path, monkeypatch, capsys):
    from backend.scripts import replay_eval

    (tmp_path / "broken.json").write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(replay_eval.sys, "argv", ["replay_eval.py", "--dir", str(tmp_path)])
    assert replay_eval.main() == 2
    assert "broken.json" in capsys.readouterr().err


def test_cli_rejects_comparison_against_old_scoring_protocol(tmp_path, monkeypatch, capsys):
    from backend.scripts import replay_eval

    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    snapshot = EvalSnapshot(
        case_id="active", recorded_at="2026-08-01T00:00:00Z", raw_input="A",
        retrieval_results=[],
        expected_claims=[{"claim": "A", "verdict": "insufficient", "evidence": []}], metadata={},
    )
    (snapshot_dir / "active.json").write_text(json.dumps(asdict(snapshot)), encoding="utf-8")
    baseline = tmp_path / "old-report.json"
    baseline.write_text('{"fever_score": 1.0}', encoding="utf-8")
    monkeypatch.setattr(replay_eval.sys, "argv", [
        "replay_eval.py", "--dir", str(snapshot_dir), "--compare-to", str(baseline),
    ])
    monkeypatch.setattr(replay_eval, "_replay_one", lambda _: snapshot.expected_claims)
    assert replay_eval.main() == 2
    assert "scoring protocols" in capsys.readouterr().err


def test_cli_displays_unmeasured_quality_metrics_as_na(tmp_path, monkeypatch, capsys):
    from backend.scripts import replay_eval

    snapshot = EvalSnapshot(
        case_id="disabled-confidence", recorded_at="2026-08-01T00:00:00Z", raw_input="A",
        retrieval_results=[],
        expected_claims=[{
            "claim": "A", "verdict": "insufficient", "evidence": [], "confidence": "high",
            "evaluation": {"score_confidence": False},
        }], metadata={},
    )
    (tmp_path / "case.json").write_text(json.dumps(asdict(snapshot)), encoding="utf-8")
    monkeypatch.setattr(replay_eval.sys, "argv", ["replay_eval.py", "--dir", str(tmp_path)])
    monkeypatch.setattr(replay_eval, "_replay_one", lambda _: snapshot.expected_claims)
    assert replay_eval.main() == 0
    output = capsys.readouterr().out
    for label in ("Confidence:", "Source independence:", "Fresh evidence:"):
        line = next(line for line in output.splitlines() if label in line)
        assert "N/A" in line
        assert "0.00%" not in line


def _write_partitioned_corpus(directory):
    snapshots = []
    for split in ("development", "holdout"):
        snapshot = EvalSnapshot(
            case_id=split, recorded_at="2026-08-01T00:00:00Z", raw_input="A",
            retrieval_results=[],
            expected_claims=[{"claim": "A", "verdict": "insufficient", "evidence": []}],
            metadata={"evaluation_split": split},
        )
        (directory / f"{split}.json").write_text(json.dumps(asdict(snapshot)), encoding="utf-8")
        snapshots.append(snapshot)
    return snapshots


def test_cli_selects_holdout_and_records_full_corpus_selection(tmp_path, monkeypatch, capsys):
    from backend.scripts import replay_eval

    _write_partitioned_corpus(tmp_path)
    replayed = []

    def replay(snapshot):
        replayed.append(snapshot.case_id)
        return snapshot.expected_claims

    monkeypatch.setattr(replay_eval, "_replay_one", replay)
    monkeypatch.setattr(replay_eval.sys, "argv", [
        "replay_eval.py", "--dir", str(tmp_path), "--evaluation-split", "holdout", "--json",
    ])
    assert replay_eval.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert replayed == ["holdout"]
    assert report["scored_snapshot_count"] == 1
    assert report["selection"] == {
        "evaluation_split": "holdout", "total_snapshot_count": 2, "selected_snapshot_count": 1,
        "excluded_by_split": ["development"],
    }
    assert report["run"]["evaluation_split"] == "holdout"
    assert report["run"]["corpus"]["all_case_ids"] == ["development", "holdout"]


def test_cli_does_not_fallback_when_requested_partition_is_empty(tmp_path, monkeypatch, capsys):
    from backend.scripts import replay_eval

    _write_partitioned_corpus(tmp_path)
    (tmp_path / "holdout.json").unlink()
    monkeypatch.setattr(replay_eval, "_replay_one", lambda _: pytest.fail("unexpected fallback replay"))
    monkeypatch.setattr(replay_eval.sys, "argv", [
        "replay_eval.py", "--dir", str(tmp_path), "--evaluation-split", "holdout",
    ])
    assert replay_eval.main() == 2
    assert "no snapshots with evaluation_split=holdout" in capsys.readouterr().err


@pytest.mark.parametrize("mismatch", ["corpus", "split", "none"])
def test_cli_compares_only_matching_corpus_and_partition(tmp_path, monkeypatch, capsys, mismatch):
    from backend.scripts import replay_eval

    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    _write_partitioned_corpus(corpus_dir)
    monkeypatch.setattr(replay_eval, "_replay_one", lambda snapshot: snapshot.expected_claims)
    base_argv = ["replay_eval.py", "--dir", str(corpus_dir), "--evaluation-split", "holdout", "--json"]
    monkeypatch.setattr(replay_eval.sys, "argv", base_argv)
    assert replay_eval.main() == 0
    baseline = json.loads(capsys.readouterr().out)
    if mismatch == "corpus":
        baseline["run"]["corpus"]["sha256"] = "other-corpus"
    elif mismatch == "split":
        baseline["run"]["evaluation_split"] = "development"
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    monkeypatch.setattr(replay_eval.sys, "argv", base_argv + ["--compare-to", str(baseline_path)])
    assert replay_eval.main() == (0 if mismatch == "none" else 2)
    output = capsys.readouterr()
    if mismatch != "none":
        assert "different corpora or evaluation splits" in output.err
    else:
        assert json.loads(output.out)["comparison"]["metric_deltas"]["fever_score"] == 0.0


@pytest.mark.parametrize("threshold, exit_code", [("0", 0), ("1", 1)])
def test_cli_acceptance_gate_rejects_unexpected_claims_without_changing_gold_score(
    tmp_path, monkeypatch, capsys, threshold, exit_code,
):
    from backend.scripts import replay_eval

    _write_partitioned_corpus(tmp_path)
    monkeypatch.setattr(replay_eval.sys, "argv", [
        "replay_eval.py", "--dir", str(tmp_path), "--evaluation-split", "holdout",
        "--pass-threshold", threshold, "--json",
    ])
    monkeypatch.setattr(replay_eval, "_replay_one", lambda snapshot: [
        *snapshot.expected_claims, {"claim": "Unrelated assertion", "verdict": "supported", "evidence": []},
    ])
    assert replay_eval.main() == exit_code
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report["total_claims"] == 1
    assert report["fever_score"] == 1.0
    assert report["unexpected_claim_count"] == 1
    if exit_code:
        assert "unexpected claims" in output.err


def test_rule_cli_blocks_key_defaults_and_never_calls_llm_completion(monkeypatch):
    import runpy

    from backend.app.core import config
    from backend.app.services import claim_correction, llm_verdict
    from backend.scripts import replay_eval

    monkeypatch.setattr(config, "_read_env_file", lambda _: {
        "KIMI_API_KEY": "fake-dotenv-key", "LLM_API_KEY": "fake-dotenv-llm-key",
    })
    monkeypatch.setenv("KIMI_API_KEY", "fake-ambient-key")
    monkeypatch.setenv("LLM_API_KEY", "fake-ambient-llm-key")
    monkeypatch.setattr(replay_eval.sys, "argv", ["replay_eval.py", "--engine", "rule"])
    completion_calls = []

    def forbidden_completion(*_args, **_kwargs):
        completion_calls.append("attempted")
        raise AssertionError("rule replay attempted LLM completion")

    monkeypatch.setattr(llm_verdict, "complete_once", forbidden_completion)
    monkeypatch.setattr(claim_correction, "complete_once", forbidden_completion)
    config.get_settings.cache_clear()
    module = runpy.run_path(replay_eval.__file__, run_name="rule_replay_env_regression")
    snapshot = EvalSnapshot(
        case_id="offline-regression", recorded_at="2026-08-01T00:00:00Z",
        raw_input="青岚市图书馆新馆已于2026年8月1日开放",
        retrieval_results=[{
            "result_id": "r1", "url": "https://library.example/opening", "source_name": "青岚市图书馆",
            "title": "青岚市图书馆新馆2026年8月1日开放", "published_at": "2026-08-01",
            "snippet": "青岚市图书馆新馆已于2026年8月1日正式开放，读者可以入馆借阅。", "source_tier": "S",
        }],
        expected_claims=[{
            "claim": "青岚市图书馆新馆已于2026年8月1日开放", "claim_type": "fact", "verdict": "supported",
            "evidence": [{"url": "https://library.example/opening"}],
        }], metadata={},
    )
    actuals = module["_replay_one"](snapshot)
    assert actuals[0]["evidence"]
    assert completion_calls == []
    assert not config.get_settings().llm_api_key


def test_verdict_path_metrics_counts_llm_vs_rule_fallback():
    from backend.scripts.replay_eval import _verdict_path_metrics

    # Three fact claims with evidence (LLM-judge candidates); one carries the
    # "[LLM判定]" marker, one is a bare rule verdict, one has no evidence (not a
    # candidate). Expect 2 candidates, 1 judged, 50% fallback.
    actuals = [[
        {"claim_type": "fact", "evidence": [{"url": "u1"}], "notes": "规则 [LLM判定] 已核"},
        {"claim_type": "fact", "evidence": [{"url": "u2"}], "notes": "规则判定"},
        {"claim_type": "fact", "evidence": [], "notes": ""},
        {"claim_type": "opinion", "evidence": [{"url": "u3"}], "notes": "[LLM判定] x"},
    ]]

    llm = _verdict_path_metrics(actuals, engine="llm")
    assert llm["llm_candidate_claims"] == 2
    assert llm["llm_judged_claims"] == 1
    assert llm["rule_fallback_claims"] == 1
    assert llm["rule_fallback_rate"] == 0.5
    assert "5-30%" not in llm["assessment"]  # 50% -> "fix reliability first"
    assert "fix reliability first" in llm["assessment"]

    # Rule engine never invokes the judge, so the rate is not a reliability signal.
    rule = _verdict_path_metrics(actuals, engine="rule")
    assert rule["assessment"].startswith("n/a")
