"""Tests for llm_verdict.py completion_fn routing and safe_mode credibility."""
from __future__ import annotations

import json
from datetime import date

import pytest

from backend.app.models.schemas import ClaimResult, EvidenceItem
from backend.app.services import model_health
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
    monkeypatch.setattr(model_health.httpx, "post", boom)

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


def test_judges_all_fact_claims_with_evidence():
    calls = {"n": 0}

    def counter(s, u):
        calls["n"] += 1
        return json.dumps({"verdict": "supported", "confidence": "high", "reason": "确认"})

    claims = [_claim("某事。", verdict="supported", evidence=[_ev()])]
    out = llm_judge_claims(claims, completion_fn=counter)
    assert calls["n"] == 1
    assert out[0].verdict == "supported"


@pytest.mark.parametrize("published_at", ["2026-07-01", "2026-07-01T09:30:00+08:00"])
def test_judge_receives_source_and_date_alongside_selected_evidence(published_at):
    evidence = _ev("开放安排", "周三闭馆").model_copy(update={
        "source_name": "滨海科技馆", "published_at": published_at,
    })
    calls = []

    def complete(system, user):
        calls.append(user)
        return '{"verdict":"insufficient","confidence":"low","reason":"待核实适用期"}'

    result = llm_judge_claims([_claim("滨海科技馆目前周三闭馆", evidence=[evidence])], completion_fn=complete)

    assert len(calls) == 1
    supplied_evidence = calls[0].split("<untrusted-evidence>\n", 1)[1].split("\n</untrusted-evidence>", 1)[0]
    assert published_at in supplied_evidence
    assert evidence.source_name in supplied_evidence
    assert evidence.title in supplied_evidence and evidence.snippet in supplied_evidence
    assert result[0].evidence == [evidence]


@pytest.mark.parametrize("published_at", ["", "  ", "not-a-date", "2026-02-30"])
def test_judge_treats_missing_and_invalid_dates_as_unknown(published_at):
    evidence = _ev().model_copy(update={"published_at": published_at})
    calls = []

    def complete(system, user):
        calls.append(user)
        return '{"verdict":"insufficient","confidence":"low","reason":"日期未知"}'

    llm_judge_claims([_claim("当前开放安排", evidence=[evidence])], completion_fn=complete)

    assert len(calls) == 1
    assert "发布日期：未知" in calls[0]
    if published_at.strip():
        assert published_at not in calls[0]


def test_evaluation_date_is_separate_from_source_date():
    calls = []

    def complete(system, user):
        calls.append((system, user))
        return '{"verdict":"insufficient","confidence":"low","reason":"适用期未确认"}'

    evidence = _ev().model_copy(update={"published_at": "2024-03-02"})
    llm_judge_claims(
        [_claim("目前的安排", evidence=[evidence])], completion_fn=complete,
        reference_date=date(2026, 9, 30),
    )

    assert "2026-09-30" in calls[0][0]
    assert "2024-03-02" in calls[0][1]
    assert "2026-09-30" not in calls[0][1]
