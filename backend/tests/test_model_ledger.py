from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from backend.app.services import model_ledger


def _settings(*, enabled: bool, ledger_dir: Path):
    return SimpleNamespace(model_ledger_enabled=enabled, model_ledger_dir=ledger_dir)


def test_ledger_is_noop_when_disabled(tmp_path: Path):
    model_ledger._reset_for_tests()
    settings = _settings(enabled=False, ledger_dir=tmp_path / "ledger")

    model_ledger.record_call(provider="llm", model="m1", input_tokens=10, settings=settings)

    assert not (tmp_path / "ledger").exists()
    assert model_ledger.get_model_ledger(settings) is None


def test_ledger_appends_desensitized_record_when_enabled(tmp_path: Path):
    model_ledger._reset_for_tests()
    ledger_dir = tmp_path / "ledger"
    settings = _settings(enabled=True, ledger_dir=ledger_dir)

    model_ledger.record_call(
        provider="llm",
        model="deepseek-v4",
        input_tokens=120,
        output_tokens=45,
        cache_tokens=64,
        latency_ms=1234,
        status="ok",
        stage_key="agent_synthesis",
        settings=settings,
    )

    files = list(ledger_dir.glob("model-calls-*.jsonl"))
    assert len(files) == 1
    record = json.loads(files[0].read_text(encoding="utf-8").strip())
    assert record["model"] == "deepseek-v4"
    assert record["input_tokens"] == 120
    assert record["output_tokens"] == 45
    assert record["cache_tokens"] == 64
    assert record["latency_ms"] == 1234
    assert record["status"] == "ok"
    assert record["stage_key"] == "agent_synthesis"
    # Desensitization: no secret-shaped keys survive to disk.
    for forbidden in ("api_key", "base_url", "authorization", "bearer", "endpoint", "host"):
        assert forbidden not in files[0].read_text(encoding="utf-8").lower()


def test_ledger_scrubs_secret_shaped_values(tmp_path: Path):
    """Even if a caller smuggles a secret-looking string into a field, the scrub
    drops it rather than persisting it."""
    model_ledger._reset_for_tests()
    ledger_dir = tmp_path / "ledger"
    settings = _settings(enabled=True, ledger_dir=ledger_dir)

    model_ledger.record_call(
        provider="llm",
        model="Bearer sk-secret-leak",  # deliberately hostile value
        settings=settings,
    )

    content = list(ledger_dir.glob("*.jsonl"))[0].read_text(encoding="utf-8")
    assert "sk-secret-leak" not in content
    assert "bearer" not in content.lower()


def test_ledger_never_raises_on_broken_dir(tmp_path: Path, monkeypatch):
    """A ledger failure must never propagate into the completion path."""
    model_ledger._reset_for_tests()
    settings = _settings(enabled=True, ledger_dir=tmp_path / "ledger")

    def _boom(self, record):
        raise OSError("disk full")

    monkeypatch.setattr(model_ledger.ModelLedger, "append", _boom)
    # Must not raise.
    model_ledger.record_call(provider="llm", model="m", settings=settings)


def test_context_estimate_persists_only_known_nonnegative_integer_counts(tmp_path: Path):
    model_ledger._reset_for_tests()
    model_ledger.record_call(
        provider="llm", model="model", settings=_settings(enabled=True, ledger_dir=tmp_path),
        context_estimate={
            "system": 120, "total_estimated": 500, "prompt": "private user input",
            "evidence_passages": {"text": "test private passage"},
            "playbooks": "private strategy", "evidence_omitted": -1, "evidence_selected": True,
        },
    )
    content = list(tmp_path.glob("*.jsonl"))[0].read_text()
    assert "private" not in content
    assert json.loads(content)["context_estimate"] == {
        "system": 120, "total_estimated": 500, "estimate_kind": "heuristic",
    }
