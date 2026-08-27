from pathlib import Path

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

