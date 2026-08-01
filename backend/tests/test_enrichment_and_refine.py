"""Tests for the new enrichment (timeline/scenarios) and critic-triggered
refinement methods added to agent_reasoner.synthesize."""
from __future__ import annotations

import json
from dataclasses import replace

from backend.app.core.config import get_settings
from backend.app.models.schemas import AnalyzeRequest, ClaimResult, EvidenceItem, NormalizedEvent
from backend.app.services.agent_reasoner import LlmAgentReasoner
from backend.app.services.progress import reset_progress_callback, set_progress_callback
from backend.app.services.retrieval_models import RetrievalBundle, SearchResult


def _reasoner() -> LlmAgentReasoner:
    return LlmAgentReasoner(
        settings=replace(
            get_settings(),
            analysis_provider="kimi",
            llm_api_key="k",
            agent_synthesis_critic_enabled=True,
        )
    )


def _ev(snippet: str = "证据片段", title: str = "t") -> EvidenceItem:
    return EvidenceItem(
        title=title, url="https://example.com/a", source_name="新华社",
        published_at="2026-07-01", snippet=snippet, relevance_reason="r", source_tier="A",
    )


def _claim(claim, verdict, *, evidence=None, confidence="high", notes="n") -> ClaimResult:
    return ClaimResult(
        claim=claim, claim_type="fact", verdict=verdict, confidence=confidence,
        evidence=evidence or [], notes=notes,
    )


def _search_result(result_id: str, title: str = "标题", snippet: str = "摘要") -> SearchResult:
    return SearchResult(
        case_id="c1", query="q", result_id=result_id, title=title,
        url=f"https://example.com/{result_id}", source_name="来源",
        published_at="2026-07-01", snippet=snippet, source_tier="B",
    )


def _bundle(*results: SearchResult) -> RetrievalBundle:
    return RetrievalBundle(
        query="test", canonical_results=tuple(results), provider_name="mock",
    )


# --- _refine_after_critic tests ---


def test_refine_skips_when_no_critic_downgrades(monkeypatch):
    r = _reasoner()
    claims = [_claim("X。", "insufficient", notes="原始")]
    calls = {"n": 0}
    monkeypatch.setattr(r, "_request_completion", lambda **kw: (calls.__setitem__("n", calls["n"] + 1), "")[1])

    out = r._refine_after_critic(
        claims, downgraded_indices=set(), retrieval_bundle=_bundle(_search_result("r1")), fetched_bodies=None,
    )
    assert out[0].verdict == "insufficient"
    assert calls["n"] == 0  # no LLM call when nothing was critic-downgraded


def test_refine_upgrades_critic_downgraded_claim(monkeypatch):
    r = _reasoner()
    claims = [
        _claim("拼多多买了5栋楼。", "insufficient", notes="核查复检：cited 证据不足以支撑原判定，已下调为存疑。"),
    ]
    bundle = _bundle(_search_result("r1", title="拼多多雄安办公楼1栋", snippet="拼多多确认购入1栋办公楼"))
    resp = json.dumps({
        "refined_claims": [
            {"index": 0, "verdict": "refuted", "confidence": "high",
             "evidence_result_ids": ["r1"], "notes": "证据显示仅1栋而非5栋"}
        ]
    })
    monkeypatch.setattr(r, "_request_completion", lambda **kw: resp)

    out = r._refine_after_critic(claims, downgraded_indices={0}, retrieval_bundle=bundle, fetched_bodies=None)
    assert out[0].verdict == "refuted"
    assert out[0].confidence == "high"
    assert "1栋" in (out[0].notes or "")


def test_refine_rejects_verdict_without_evidence(monkeypatch):
    r = _reasoner()
    claims = [
        _claim("某事。", "insufficient", notes="核查复检：cited 证据不足以支撑原判定，已下调为存疑。"),
    ]
    bundle = _bundle(_search_result("r1"))
    resp = json.dumps({
        "refined_claims": [
            {"index": 0, "verdict": "supported", "confidence": "high",
             "evidence_result_ids": ["nonexistent_id"], "notes": ""}
        ]
    })
    monkeypatch.setattr(r, "_request_completion", lambda **kw: resp)

    out = r._refine_after_critic(claims, downgraded_indices={0}, retrieval_bundle=bundle, fetched_bodies=None)
    # "supported" with no valid evidence is rejected -> stays insufficient
    assert out[0].verdict == "insufficient"


def test_refine_degrades_on_unparseable_response(monkeypatch):
    r = _reasoner()
    claims = [
        _claim("某事。", "insufficient", notes="核查复检：cited 证据不足以支撑原判定，已下调为存疑。"),
    ]
    bundle = _bundle(_search_result("r1"))
    monkeypatch.setattr(r, "_request_completion", lambda **kw: "not json")

    out = r._refine_after_critic(claims, downgraded_indices={0}, retrieval_bundle=bundle, fetched_bodies=None)
    assert out[0].verdict == "insufficient"  # unchanged


# --- _enrich_synthesis tests ---


def _event() -> NormalizedEvent:
    return NormalizedEvent(
        title="拼多多雄安买楼", summary="拼多多在雄安买楼传闻",
        raw_input="拼多多在雄安买了5栋楼", input_type="text_news",
        source_name="用户", source_url="",
    )


def _request() -> AnalyzeRequest:
    return AnalyzeRequest(raw_input="拼多多在雄安买了5栋楼")


def test_enrich_produces_timeline_and_scenarios(monkeypatch):
    r = _reasoner()
    bundle = _bundle(
        _search_result("r1", title="拼多多雄安公司注册", snippet="2025年1月注册"),
        _search_result("r2", title="网传拼多多买楼", snippet="社交媒体热议"),
        _search_result("r3", title="官方回应", snippet="未予证实"),
    )
    result_map = {sr.result_id: sr for sr in bundle.canonical_results}
    claims = [_claim("拼多多买了5栋楼。", "supported")]

    resp = json.dumps({
        "event": {"title": "拼多多雄安买楼传闻", "summary": "网传拼多多在雄安买入多栋办公楼"},
        "scenarios": [
            {"label": "传闻属实", "probability": 30, "basis": "prior", "summary": "确实大量购入"},
            {"label": "传闻夸大", "probability": 70, "basis": "evidence", "summary": "实际仅1栋"},
        ],
        "timeline": [
            {"node_type": "origin", "result_id": "r1", "summary": "公司注册", "why_selected": "最早事件"},
            {"node_type": "amplification", "result_id": "r2", "summary": "社媒传播", "why_selected": "扩散节点"},
        ],
    })
    monkeypatch.setattr(r, "_request_completion", lambda **kw: resp)

    out = r._enrich_synthesis(
        request=_request(), event=_event(), claim_results=claims,
        retrieval_bundle=bundle, fetched_bodies=None, result_map=result_map,
    )
    assert len(out["timeline_nodes"]) == 2
    node_types = {n.node_type for n in out["timeline_nodes"]}
    assert "origin" in node_types
    assert "amplification" in node_types
    assert len(out["possibilities"]) == 2
    assert out["possibilities"][0].scenario == "传闻属实"
    assert out["event"] is not None
    assert out["event"].title == "拼多多雄安买楼传闻"


def test_enrich_degrades_on_failure(monkeypatch):
    r = _reasoner()
    bundle = _bundle(_search_result("r1"))
    result_map = {"r1": bundle.canonical_results[0]}
    claims = [_claim("某事。", "supported")]

    monkeypatch.setattr(r, "_request_completion", lambda **kw: "")

    events: list[dict] = []
    token = set_progress_callback(lambda ev: events.append(ev))
    try:
        out = r._enrich_synthesis(
            request=_request(), event=_event(), claim_results=claims,
            retrieval_bundle=bundle, fetched_bodies=None, result_map=result_map,
        )
    finally:
        reset_progress_callback(token)

    assert out["timeline_nodes"] == []
    assert out["possibilities"] == []
    assert out["event"] is None
    # Should have emitted a warning
    warnings = [e for e in events if e.get("level") == "warning"]
    assert len(warnings) >= 1


def test_enrich_handles_partial_response(monkeypatch):
    r = _reasoner()
    bundle = _bundle(_search_result("r1"))
    result_map = {"r1": bundle.canonical_results[0]}
    claims = [_claim("某事。", "supported")]

    # Only scenarios, no timeline or event
    resp = json.dumps({
        "scenarios": [
            {"label": "A", "probability": 60, "basis": "evidence", "summary": "aaa"},
            {"label": "B", "probability": 40, "basis": "prior", "summary": "bbb"},
        ],
    })
    monkeypatch.setattr(r, "_request_completion", lambda **kw: resp)

    out = r._enrich_synthesis(
        request=_request(), event=_event(), claim_results=claims,
        retrieval_bundle=bundle, fetched_bodies=None, result_map=result_map,
    )
    assert out["timeline_nodes"] == []
    assert len(out["possibilities"]) == 2
    assert out["event"] is None
