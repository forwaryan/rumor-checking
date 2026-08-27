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
