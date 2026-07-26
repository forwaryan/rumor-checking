"""Tests for llm_verdict.py completion_fn routing and safe_mode credibility."""
from __future__ import annotations

import json

from backend.app.models.schemas import ClaimResult, EvidenceItem
from backend.app.services import llm_verdict
from backend.app.services.llm_verdict import llm_judge_claims


def _ev(title: str = "标题", snippet: str = "摘要") -> EvidenceItem:
    return EvidenceItem(
        title=title, url="https://example.com/a", source_name="新华社",
        published_at="2026-07-01", snippet=snippet, relevance_reason="r", source_tier="A",
    )


def _claim(claim: str, verdict: str = "insufficient", *, evidence=None) -> ClaimResult:
    return ClaimResult(
        claim=claim, claim_type="fact", verdict=verdict, confidence="low",
        evidence=evidence or [], notes="n",
    )


def test_completion_fn_bypasses_httpx(monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("httpx.post must not be called")
    monkeypatch.setattr(llm_verdict.httpx, "post", boom)

    calls = {"n": 0}

    def fake_complete(system: str, user: str) -> str:
        calls["n"] += 1
        return json.dumps({"verdict": "refuted", "confidence": "high", "reason": "证据明确否认"})

    claims = [_claim("拼多多买了5栋楼。", evidence=[_ev("拼多多仅1栋办公楼")])]
    out = llm_judge_claims(claims, completion_fn=fake_complete)

    assert calls["n"] == 1
    assert out[0].verdict == "refuted"
    assert out[0].confidence == "high"
    assert "LLM判定" in out[0].notes


def test_completion_fn_none_without_key_skips(monkeypatch):
    claims = [_claim("某事。", evidence=[_ev()])]
    # No completion_fn and no api_key -> should return unchanged
    out = llm_judge_claims(claims, completion_fn=None)
    assert out[0].verdict == "insufficient"


def test_completion_fn_empty_response_keeps_original():
    claims = [_claim("某事。", evidence=[_ev()])]
    out = llm_judge_claims(claims, completion_fn=lambda s, u: "")
    assert out[0].verdict == "insufficient"


def test_completion_fn_invalid_json_keeps_original():
    claims = [_claim("某事。", evidence=[_ev()])]
    out = llm_judge_claims(claims, completion_fn=lambda s, u: "not json")
    assert out[0].verdict == "insufficient"


def test_skips_claims_without_evidence():
    calls = {"n": 0}

    def counter(s, u):
        calls["n"] += 1
        return json.dumps({"verdict": "supported", "confidence": "high", "reason": "有"})

    claims = [_claim("某事。", evidence=[])]  # no evidence -> not a candidate
    out = llm_judge_claims(claims, completion_fn=counter)
    assert calls["n"] == 0
    assert out[0].verdict == "insufficient"


def test_skips_non_insufficient_claims():
    calls = {"n": 0}

    def counter(s, u):
        calls["n"] += 1
        return json.dumps({"verdict": "supported", "confidence": "high", "reason": "有"})

    claims = [_claim("某事。", verdict="supported", evidence=[_ev()])]
    out = llm_judge_claims(claims, completion_fn=counter)
    assert calls["n"] == 0
    assert out[0].verdict == "supported"
