from __future__ import annotations

import json
from dataclasses import replace

from backend.app.core.config import get_settings
from backend.app.models.schemas import (
    AnalyzeRequest,
    ClaimResult,
    NormalizedEvent,
    ReportProvenance,
)
from backend.app.services.agent_reasoner import LlmAgentReasoner
from backend.app.services.content_check_builder import ContentCheckBuilder
from backend.app.services.report_builder import ReportBuilder
from backend.app.services.retrieval_service import RetrievalService
from backend.app.services.verdict_engine import coarse_truth_probability

_INPUT = "海州新鲜屋部分酸奶批次超过保质期，涉事门店已停业整改。"


def _mock_bundle():
    event = NormalizedEvent(
        summary="海州新鲜屋部分酸奶批次超过保质期",
        input_type="text_news",
        raw_input=_INPUT,
        title="海州新鲜屋酸奶抽检",
    )
    return RetrievalService().retrieve_for_event(event, request_context={}), event


def _enabled_reasoner(monkeypatch, response_json: dict) -> LlmAgentReasoner:
    reasoner = LlmAgentReasoner(
        settings=replace(get_settings(), analysis_provider="kimi", llm_api_key="test-key")
    )
    monkeypatch.setattr(
        reasoner, "_request_completion", lambda **kwargs: json.dumps(response_json, ensure_ascii=False)
    )
    return reasoner


# --- fast path: deterministic coarse probability ------------------------------


def test_coarse_probability_maps_verdict_and_confidence():
    assert coarse_truth_probability("supported", "high") == (90.0, "evidence")
    assert coarse_truth_probability("supported", "medium") == (75.0, "evidence")
    assert coarse_truth_probability("refuted", "high") == (10.0, "evidence")
    assert coarse_truth_probability("conflicting", "low") == (50.0, "evidence")


def test_coarse_probability_insufficient_is_prior_midpoint():
    # No information -> honest 50/50, and basis must be prior (not a knowledge claim).
    assert coarse_truth_probability("insufficient", "low") == (50.0, "prior")
    assert coarse_truth_probability("insufficient", "high") == (50.0, "prior")


def test_coarse_probability_accepts_float_confidence():
    assert coarse_truth_probability("supported", 0.9) == (90.0, "evidence")
    assert coarse_truth_probability("supported", 0.6) == (75.0, "evidence")
    assert coarse_truth_probability("supported", 0.2) == (62.0, "evidence")


def test_coarse_probability_without_evidence_is_prior():
    # A decisive verdict with no evidence attached must not claim "evidence" basis.
    assert coarse_truth_probability("supported", "high", has_evidence=False) == (90.0, "prior")


def _provenance() -> ReportProvenance:
    return ReportProvenance(
        source_type="backend_mock",
        event_source="input_normalized",
        claim_source="rule",
        evidence_source="none",
        timeline_source="none",
    )


def test_report_builder_backfills_missing_probabilities():
    builder = ReportBuilder()
    claims = [
        ClaimResult(claim="a。", claim_type="fact", verdict="insufficient", confidence="low", notes="n"),
    ]
    filled = builder._backfill_claim_probabilities(claims)
    assert filled[0].truth_probability == 50.0
    assert filled[0].probability_basis == "prior"


def test_report_builder_preserves_prefilled_probabilities():
    builder = ReportBuilder()
    claims = [
        ClaimResult(
            claim="a。",
            claim_type="fact",
            verdict="refuted",
            confidence="high",
            truth_probability=8.0,
            probability_basis="prior",
            notes="n",
        ),
    ]
    filled = builder._backfill_claim_probabilities(claims)
    assert filled[0].truth_probability == 8.0
    assert filled[0].probability_basis == "prior"


# --- deep path: LLM probability + scenarios -----------------------------------


def test_synthesis_parses_claim_probability(monkeypatch):
    bundle, event = _mock_bundle()
    response = {
        "event": {"title": "海州酸奶", "summary": "抽检超期", "anchor_result_id": "R01-1"},
        "claims": [
            {
                "claim": "海州新鲜屋部分酸奶批次超过保质期。",
                "claim_type": "fact",
                "verdict": "supported",
                "confidence": "high",
                "truth_probability": 88,
                "probability_basis": "evidence",
                "evidence_result_ids": ["R01-1"],
                "notes": "grounded",
            }
        ],
        "scenarios": [],
        "timeline": [],
    }
    reasoner = _enabled_reasoner(monkeypatch, response)
    result = reasoner.synthesize(
        request=AnalyzeRequest(raw_input=_INPUT, input_type="text"),
        event=event,
        retrieval_bundle=bundle,
    )
    assert result is not None
    claim = result.verdict.claim_results[0]
    assert claim.truth_probability == 88.0
    assert claim.probability_basis == "evidence"


def test_probability_is_independent_of_grounded_verdict_downgrade(monkeypatch):
    # The LLM gives a decisive verdict with NO evidence -> verdict downgrades to
    # insufficient (grounding invariant), but a prior-based probability may remain.
    bundle, event = _mock_bundle()
    response = {
        "event": {"title": "海州酸奶", "summary": "抽检超期", "anchor_result_id": "R01-1"},
        "claims": [
            {
                "claim": "拼多多在雄安买了三栋楼。",
                "claim_type": "fact",
                "verdict": "supported",
                "confidence": "high",
                "truth_probability": 15,
                "probability_basis": "prior",
                "evidence_result_ids": [],
                "notes": "no ids",
            }
        ],
        "scenarios": [],
        "timeline": [],
    }
    reasoner = _enabled_reasoner(monkeypatch, response)
    result = reasoner.synthesize(
        request=AnalyzeRequest(raw_input="拼多多在雄安买了三栋楼", input_type="text"),
        event=event,
        retrieval_bundle=bundle,
    )
    assert result is not None
    claim = result.verdict.claim_results[0]
    # Grounding invariant intact.
    assert claim.verdict == "insufficient"
    assert claim.evidence == []
    # Probability survives independently and stays honest about its basis.
    assert claim.truth_probability == 15.0
    assert claim.probability_basis == "prior"


def test_synthesis_parses_scenarios_and_renormalizes(monkeypatch):
    bundle, event = _mock_bundle()
    response = {
        "event": {"title": "海州酸奶", "summary": "抽检超期", "anchor_result_id": "R01-1"},
        "claims": [
            {
                "claim": "海州新鲜屋部分酸奶批次超过保质期。",
                "claim_type": "fact",
                "verdict": "supported",
                "confidence": "high",
                "truth_probability": 80,
                "probability_basis": "evidence",
                "evidence_result_ids": ["R01-1"],
                "notes": "grounded",
            }
        ],
        # Deliberately sums to 60, not 100 -> must renormalize.
        "scenarios": [
            {"label": "基本属实", "probability": 40, "basis": "evidence", "summary": "s1"},
            {"label": "细节被夸大", "probability": 20, "basis": "prior", "summary": "s2"},
        ],
        "timeline": [],
    }
    reasoner = _enabled_reasoner(monkeypatch, response)
    result = reasoner.synthesize(
        request=AnalyzeRequest(raw_input=_INPUT, input_type="text"),
        event=event,
        retrieval_bundle=bundle,
    )
    assert result is not None
    scenarios = result.possibilities
    assert len(scenarios) == 2
    total = sum(s.probability for s in scenarios)
    assert abs(total - 100.0) <= 1.0
    assert scenarios[0].scenario == "基本属实"
    assert scenarios[0].basis == "evidence"


def test_scenarios_basis_defaults_to_none_when_absent(monkeypatch):
    bundle, event = _mock_bundle()
    response = {
        "event": {"title": "x", "summary": "y", "anchor_result_id": "R01-1"},
        "claims": [
            {
                "claim": "海州新鲜屋部分酸奶批次超过保质期。",
                "claim_type": "fact",
                "verdict": "insufficient",
                "confidence": "low",
                "evidence_result_ids": [],
                "notes": "n",
            }
        ],
        "scenarios": [
            {"label": "A", "probability": 50, "summary": "a"},
            {"label": "B", "probability": 50, "summary": "b"},
        ],
        "timeline": [],
    }
    reasoner = _enabled_reasoner(monkeypatch, response)
    result = reasoner.synthesize(
        request=AnalyzeRequest(raw_input=_INPUT, input_type="text"),
        event=event,
        retrieval_bundle=bundle,
    )
    assert result is not None
    assert all(s.basis is None for s in result.possibilities)


# --- claim decomposition: verified core survives an unverified detail ---------


def test_decomposed_core_stays_supported_while_detail_stays_uncertain(monkeypatch):
    # The 拼多多雄安 failure mode: a rumor bundles a supported CORE ("购置了办公楼",
    # evidence-backed) with an unverified DETAIL ("三栋" exact count). The fix asks
    # the model to SPLIT them; this test locks in that a split response flows all
    # the way through so the core lands in likely_true and the detail in uncertain,
    # instead of one bundled claim collapsing to insufficient.
    bundle, event = _mock_bundle()
    # result_ids from the mock bundle aren't a fixed sequence — cite a real one so
    # the grounding invariant keeps the core's supported verdict.
    core_evidence_id = bundle.canonical_results[0].result_id
    response = {
        "event": {"title": "拼多多雄安办公楼", "summary": "购置办公楼与招聘", "anchor_result_id": core_evidence_id},
        "claims": [
            {
                "claim": "拼多多在雄安购置了办公楼。",
                "claim_type": "fact",
                "verdict": "supported",
                "confidence": "high",
                "truth_probability": 85,
                "probability_basis": "evidence",
                "evidence_result_ids": [core_evidence_id],
                "notes": "多家公开来源确认购置办公楼。",
            },
            {
                "claim": "拼多多在雄安购置的办公楼数量为三栋。",
                "claim_type": "fact",
                "verdict": "insufficient",
                "confidence": "low",
                "truth_probability": 25,
                "probability_basis": "prior",
                "evidence_result_ids": [],
                "notes": "未见来源明确‘三栋’这一具体数量。",
            },
        ],
        "scenarios": [],
        "timeline": [],
    }
    reasoner = _enabled_reasoner(monkeypatch, response)
    result = reasoner.synthesize(
        request=AnalyzeRequest(raw_input="拼多多在雄安买了三栋楼", input_type="text"),
        event=event,
        retrieval_bundle=bundle,
    )
    assert result is not None

    core, detail = result.verdict.claim_results
    # The verified core keeps its supported verdict + evidence — NOT dragged down.
    assert core.verdict == "supported"
    assert core.evidence, "core claim must retain its grounding evidence"
    # The unverified detail stays honestly insufficient with a prior-based number.
    assert detail.verdict == "insufficient"
    assert detail.evidence == []
    assert detail.probability_basis == "prior"

    # And the split survives into the user-facing content_check split.
    report = ReportBuilder().build(
        event=result.event,
        claim_results=result.verdict.claim_results,
        timeline=result.timeline.nodes,
        evidence=result.verdict.evidence,
        evidence_grade=result.verdict.evidence_grade,
        provenance=_provenance(),
        retrieval_hits=bundle.to_retrieval_hit_items(),
        original_input="拼多多在雄安买了三栋楼",
        possibilities_override=result.possibilities or None,
    )
    content_check = ContentCheckBuilder().build(report=report, original_input="拼多多在雄安买了三栋楼")
    likely_true_claims = [item.claim for item in content_check.likely_true]
    uncertain_claims = [item.claim for item in content_check.uncertain]
    assert "拼多多在雄安购置了办公楼。" in likely_true_claims
    assert "拼多多在雄安购置的办公楼数量为三栋。" in uncertain_claims
