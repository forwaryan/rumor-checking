from __future__ import annotations

import json
from dataclasses import replace

from backend.app.core.config import get_settings
from backend.app.models.schemas import ClaimResult, EvidenceItem
from backend.app.services.agent_reasoner import LlmAgentReasoner
from backend.app.services.progress import reset_progress_callback, set_progress_callback


def _reasoner(critic_enabled: bool = True) -> LlmAgentReasoner:
    return LlmAgentReasoner(
        settings=replace(
            get_settings(),
            analysis_provider="kimi",
            llm_api_key="k",
            agent_synthesis_critic_enabled=critic_enabled,
        )
    )


def _ev(snippet: str = "证据片段") -> EvidenceItem:
    return EvidenceItem(
        title="t", url="https://example.com/a", source_name="新华社",
        published_at="2026-07-01", snippet=snippet, relevance_reason="r", source_tier="A",
    )


def _claim(claim, verdict, *, evidence=None, confidence="high") -> ClaimResult:
    return ClaimResult(
        claim=claim, claim_type="fact", verdict=verdict, confidence=confidence,
        evidence=evidence or [], notes="原始说明",
    )


def _patch(reasoner, response: str, monkeypatch):
    def fake(**kwargs):
        fake.calls += 1
        fake.last = kwargs
        return response
    fake.calls = 0
    fake.last = None
    monkeypatch.setattr(reasoner, "_request_completion", fake)
    return fake


def test_critic_downgrades_unfaithful_supported_claim(monkeypatch):
    r = _reasoner()
    claims = [
        _claim("拼多多在雄安买了5栋楼。", "supported", evidence=[_ev()]),
        _claim("拼多多在雄安招了6000人。", "supported", evidence=[_ev()]),
    ]
    # Critic flags index 1 (keep:false) as unsupported by its own evidence.
    resp = json.dumps({"revisions": [{"index": 1, "keep": False, "reason": "证据只提到员工超600人"}]})
    _patch(r, resp, monkeypatch)

    out, downgraded_indices = r._critique_claim_results(claims)
    assert out[0].verdict == "supported"  # untouched
    assert out[1].verdict == "insufficient"  # downgraded
    assert out[1].confidence == "low"
    assert "核查复检" in out[1].notes
    assert "证据只提到员工超600人" in out[1].notes
    assert 1 in downgraded_indices


def test_critic_is_monotonic_ignores_keep_true_and_bad_upgrades(monkeypatch):
    r = _reasoner()
    claims = [_claim("某事属实。", "insufficient", evidence=[_ev()])]
    # Even if the critic tries to "keep" or upgrade, an insufficient claim with
    # evidence is not in the checkable set (only decisive verdicts are), and
    # keep:true is a no-op regardless.
    resp = json.dumps({"revisions": [{"index": 0, "keep": True, "reason": "looks fine"}]})
    fake = _patch(r, resp, monkeypatch)

    out, downgraded_indices = r._critique_claim_results(claims)
    assert out[0].verdict == "insufficient"
    assert len(downgraded_indices) == 0
    # An insufficient-only claim set has nothing decisive to check -> no LLM call.
    assert fake.calls == 0


def test_critic_disabled_flag_short_circuits(monkeypatch):
    r = _reasoner(critic_enabled=False)
    claims = [_claim("某事属实。", "supported", evidence=[_ev()])]
    fake = _patch(r, json.dumps({"revisions": [{"index": 0, "keep": False}]}), monkeypatch)

    out, downgraded_indices = r._critique_claim_results(claims)
    assert out[0].verdict == "supported"  # unchanged
    assert len(downgraded_indices) == 0
    assert fake.calls == 0  # never called when disabled


def test_critic_unparseable_response_keeps_original(monkeypatch):
    r = _reasoner()
    claims = [_claim("某事属实。", "supported", evidence=[_ev()])]
    _patch(r, "not json at all", monkeypatch)

    out, downgraded_indices = r._critique_claim_results(claims)
    assert out[0].verdict == "supported"  # preserved on parse failure
    assert len(downgraded_indices) == 0


def test_critic_skips_when_no_evidence(monkeypatch):
    r = _reasoner()
    # supported but with NO cited evidence -> not checkable, no LLM call.
    claims = [_claim("某事属实。", "supported", evidence=[])]
    fake = _patch(r, json.dumps({"revisions": []}), monkeypatch)

    out, downgraded_indices = r._critique_claim_results(claims)
    assert out[0].verdict == "supported"
    assert len(downgraded_indices) == 0
    assert fake.calls == 0


def test_critic_emits_completion_log_even_when_nothing_downgraded(monkeypatch):
    # Observability: a critic that ran and found everything faithful must still
    # leave a trace event, otherwise the verify layer is invisible when it agrees.
    r = _reasoner()
    claims = [_claim("拼多多在雄安买楼。", "supported", evidence=[_ev()])]
    _patch(r, json.dumps({"revisions": [{"index": 0, "keep": True}]}), monkeypatch)

    events: list[dict] = []
    token = set_progress_callback(lambda ev: events.append(ev))
    try:
        out, downgraded_indices = r._critique_claim_results(claims)
    finally:
        reset_progress_callback(token)

    assert out[0].verdict == "supported"  # unchanged (monotonic)
    assert len(downgraded_indices) == 0
    completions = [e for e in events if e.get("title") == "Synthesis critic 完成"]
    assert len(completions) == 1
    assert "全部与所引证据一致" in completions[0].get("summary", "")
