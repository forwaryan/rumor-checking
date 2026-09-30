from __future__ import annotations

import copy
import json
import socket
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from backend.app.core import config
from backend.app.services import llm_verdict, model_health, page_fetcher
from backend.app.services.agent_replay import RecordedBoundaries, load_fixture, replay_case, replay_directory
from backend.scripts.replay_agent import main

FIXTURES = Path(__file__).resolve().parents[2] / "evals" / "agent_replay"


def test_deep_replay_runs_real_tools_and_is_deterministic():
    first = replay_directory(FIXTURES)
    assert first["passed"], [(case["case_id"], case["failures"]) for case in first["cases"]]
    assert first == replay_directory(FIXTURES)
    supported, missing_price, timeout = first["cases"]
    assert supported["claims"][0]["verdict"] == "supported"
    assert "SYNTHESIS_CRITIC_SYSTEM_PROMPT" in [call["template"] for call in supported["model_calls"]]
    assert missing_price["claims"][0]["evidence_gaps"] == ["price"]
    assert "CRITIC_REFINE_SYSTEM_PROMPT" in [call["template"] for call in missing_price["model_calls"]]
    assert any(call["stage"] == "per_claim_retrieval" for call in missing_price["retrieval_calls"])
    assert timeout["model_calls"][1]["outcome"] == "timeout"
    assert len(timeout["page_calls"]) == 1
    assert timeout["claims"][0]["verdict"] == "insufficient"
    assert "judge_claims" in [action["action"] for action in timeout["actions"]]
    assert supported["model_calls"][1]["input_evidence_ids"] == ["q0-museum_notice"]
    assert all(len(call["prompt_sha256"]) == 64 for case in first["cases"] for call in case["model_calls"])
    serialized = json.dumps(first, ensure_ascii=False)
    assert "青岚市" not in serialized
    assert "synthetic-replay-key" not in serialized
    assert "system_prompt" not in serialized
    assert "user_prompt" not in serialized


def test_replay_verdict_date_and_fingerprints_do_not_follow_wall_clock(monkeypatch):
    fixture = load_fixture(FIXTURES / "03_model_timeout.json")
    baseline = replay_case(fixture)

    class FutureDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2040, 1, 1, tzinfo=tz)

    monkeypatch.setattr(llm_verdict, "datetime", FutureDatetime)
    replayed = replay_case(fixture)
    assert baseline["passed"] and replayed["passed"]
    assert replayed == baseline


def test_unrecorded_retrieval_fails_even_when_production_falls_back():
    fixture = load_fixture(FIXTURES / "01_supported.json")
    fixture["retrieval"].pop()
    result = replay_case(fixture)
    assert not result["passed"]
    assert any(error.startswith("unrecorded_retrieval:") for error in result["failures"])


def test_unrecorded_model_call_and_unused_response_fail():
    fixture = load_fixture(FIXTURES / "01_supported.json")
    missing = copy.deepcopy(fixture)
    missing["completions"].pop()
    assert any(error.startswith("unrecorded_model_call:") for error in replay_case(missing)["failures"])
    fixture["completions"].append(fixture["completions"][-1])
    assert "unconsumed_model_responses" in replay_case(fixture)["failures"]


def test_wrong_gold_is_not_silently_accepted():
    fixture = load_fixture(FIXTURES / "01_supported.json")
    claim = next(iter(fixture["expected"]["claims"]))
    fixture["expected"]["claims"][claim] = "refuted"
    result = replay_case(fixture)
    assert not result["passed"]
    assert any(error.startswith("verdict_mismatch:") for error in result["failures"])


def test_unrecorded_http_is_blocked_before_any_transport():
    original_complete = RecordedBoundaries.complete

    def unexpected_http(boundaries, **kwargs):
        try:
            httpx.get("https://unrecorded.invalid/private")
        except Exception:
            pass
        return original_complete(boundaries, **kwargs)

    with patch.object(RecordedBoundaries, "complete", unexpected_http):
        result = replay_case(load_fixture(FIXTURES / "01_supported.json"))
    assert not result["passed"]
    assert "unrecorded_http_request" in result["failures"]


def test_replay_restores_settings_network_and_process_state(monkeypatch):
    original_settings = config.get_settings
    original_connect = socket.socket.connect
    original_cache = page_fetcher._cache
    original_registry = model_health._registry
    monkeypatch.setenv("LLM_API_KEY", "must-not-be-read")
    monkeypatch.setenv("LLM_BASE_URL", "https://must-not-be-read.invalid")
    result = replay_case(load_fixture(FIXTURES / "01_supported.json"))
    assert result["passed"]
    assert config.get_settings is original_settings
    assert socket.socket.connect is original_connect
    assert page_fetcher._cache is original_cache
    assert model_health._registry is original_registry
    assert "must-not-be-read" not in json.dumps(result)
    from backend.app.services.claim_correction import get_settings as correction_settings
    assert correction_settings is original_settings


def test_fixture_requires_synthetic_declaration_and_directory_is_not_empty(tmp_path):
    fixture = tmp_path / "unsafe.json"
    fixture.write_text(json.dumps({"synthetic": False}), encoding="utf-8")
    with pytest.raises(ValueError, match="synthetic"):
        load_fixture(fixture)
    with pytest.raises(ValueError, match="No agent replay"):
        replay_directory(tmp_path / "missing")


def test_cli_json_and_nonzero_failure_exit(tmp_path, monkeypatch, capsys):
    output = tmp_path / "result.json"
    monkeypatch.setattr(sys, "argv", ["replay_agent", "--dir", str(FIXTURES), "--output", str(output), "--json"])
    assert main() == 0
    assert json.loads(capsys.readouterr().out) == json.loads(output.read_text())
    wrong = load_fixture(FIXTURES / "01_supported.json")
    wrong["expected"]["required_actions"].append("missing_action")
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    (fixture_dir / "case.json").write_text(json.dumps(wrong), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["replay_agent", "--dir", str(fixture_dir), "--json"])
    assert main() == 1
    assert not json.loads(capsys.readouterr().out)["passed"]
