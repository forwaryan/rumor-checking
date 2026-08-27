from __future__ import annotations

import json

from backend.scripts import source_doctor


def _snapshot(*, active_primary: str | None, unavailable: int) -> dict:
    return {
        "sources": [
            {
                "id": "mock",
                "enabled": active_primary == "mock",
                "configured": active_primary == "mock",
                "capabilities": ["offline_fixture"],
                "unavailable_reason": None,
            },
            {
                "id": "xiaohongshu",
                "enabled": False,
                "configured": unavailable > 0,
                "capabilities": ["social_search"],
                "unavailable_reason": "未检测到 xhs-cli",
            },
        ],
        "summary": {
            "status": "ok" if active_primary and not unavailable else "degraded",
            "active_primary": active_primary,
            "enabled": int(active_primary is not None),
            "unavailable": unavailable,
        },
    }


def test_doctor_default_allows_optional_source_degradation(monkeypatch, capsys):
    monkeypatch.setattr(
        source_doctor,
        "source_capability_snapshot",
        lambda: _snapshot(active_primary="mock", unavailable=1),
    )

    assert source_doctor.main([]) == 0
    output = capsys.readouterr().out
    assert "Provider Doctor: DEGRADED" in output
    assert "Active primary: mock" in output
    assert "[missing] xiaohongshu" in output


def test_doctor_strict_fails_for_configured_unavailable_source(monkeypatch):
    monkeypatch.setattr(
        source_doctor,
        "source_capability_snapshot",
        lambda: _snapshot(active_primary="mock", unavailable=1),
    )

    assert source_doctor.main(["--strict"]) == 1


def test_doctor_fails_without_active_primary_and_supports_json(monkeypatch, capsys):
    snapshot = _snapshot(active_primary=None, unavailable=0)
    monkeypatch.setattr(source_doctor, "source_capability_snapshot", lambda: snapshot)

    assert source_doctor.main(["--json"]) == 1
    assert json.loads(capsys.readouterr().out) == snapshot
