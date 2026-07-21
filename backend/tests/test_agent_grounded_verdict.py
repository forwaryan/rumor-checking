from __future__ import annotations

import json
import tempfile
from dataclasses import replace

from backend.app.agent_tools.tools import LLM_SYNTHESIS_FALLBACK_REASON
from backend.app.core.config import get_settings
from backend.app.models.schemas import AnalyzeRequest, NormalizedEvent
from backend.app.services.agent_reasoner import LlmAgentReasoner
from backend.app.services.analyze_pipeline import AnalyzePipeline
from backend.app.services.retrieval_service import RetrievalService

_ACID_INPUT = "海州市市场监管局通报称，海州新鲜屋部分酸奶批次超过保质期，涉事门店已停业整改。"


def _mock_bundle():
    event = NormalizedEvent(
        summary="海州新鲜屋部分酸奶批次超过保质期",
        input_type="text_news",
        raw_input=_ACID_INPUT,
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


# --- grounding invariant ------------------------------------------------------


def test_decisive_verdict_without_evidence_is_downgraded_to_insufficient(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_CACHE_DIR", tempfile.mkdtemp())
    get_settings.cache_clear()
    bundle, event = _mock_bundle()

    # The LLM claims a decisive "supported" verdict but supplies NO evidence ids.
    response = {
        "event": {"title": "海州酸奶", "summary": "抽检超期", "anchor_result_id": "R01-1"},
        "claims": [
            {
                "claim": "海州新鲜屋部分酸奶批次超过保质期。",
                "claim_type": "fact",
                "verdict": "supported",
                "confidence": "high",
                "evidence_result_ids": [],
                "notes": "no ids on purpose",
            }
        ],
        "timeline": [],
    }
    reasoner = _enabled_reasoner(monkeypatch, response)
    result = reasoner.synthesize(
        request=AnalyzeRequest(raw_input=_ACID_INPUT, input_type="text"),
        event=event,
        retrieval_bundle=bundle,
    )
    assert result is not None
    claim = result.verdict.claim_results[0]
    assert claim.verdict == "insufficient"
    assert claim.evidence == []


def test_absolute_scope_claim_is_downgraded_when_evidence_only_partially_supports(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_CACHE_DIR", tempfile.mkdtemp())
    get_settings.cache_clear()
    bundle, event = _mock_bundle()
    response = {
        "event": {"title": "拼多多雄安招聘", "summary": "岗位信息", "anchor_result_id": "R01-1"},
        "claims": [
            {
                "claim": "拼多多在雄安新区招聘的都是研发技术相关的岗位。",
                "claim_type": "fact",
                "verdict": "supported",
                "confidence": "high",
                "evidence_result_ids": ["R01-1"],
                "notes": "证据提到新增了中台运营、数据分析、质检专家等岗位。",
            }
        ],
        "timeline": [],
    }
    reasoner = _enabled_reasoner(monkeypatch, response)

    result = reasoner.synthesize(
        request=AnalyzeRequest(raw_input="拼多多雄安新区已经入住了，而且招的都是研发技术相关的", input_type="text"),
        event=event,
        retrieval_bundle=bundle,
    )

    assert result is not None
    claim = result.verdict.claim_results[0]
    assert claim.verdict == "insufficient"
    assert claim.confidence == "low"
    assert "绝对化" in claim.notes


def test_every_decisive_verdict_carries_evidence(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_CACHE_DIR", tempfile.mkdtemp())
    get_settings.cache_clear()
    bundle, event = _mock_bundle()

    response = {
        "event": {"title": "海州酸奶", "summary": "抽检超期", "anchor_result_id": "R01-1"},
        "claims": [
            {
                "claim": "海州新鲜屋部分酸奶批次超过保质期。",
                "claim_type": "fact",
                "verdict": "supported",
                "confidence": "high",
                "evidence_result_ids": ["R01-1"],
                "notes": "grounded",
            },
            {
                "claim": "海州新鲜屋多人中毒。",
                "claim_type": "fact",
                "verdict": "refuted",
                "confidence": "medium",
                "evidence_result_ids": ["R01-2"],
                "notes": "grounded refute",
            },
        ],
        "timeline": [],
    }
    reasoner = _enabled_reasoner(monkeypatch, response)
    result = reasoner.synthesize(
        request=AnalyzeRequest(raw_input=_ACID_INPUT, input_type="text"),
        event=event,
        retrieval_bundle=bundle,
    )
    assert result is not None
    decisive = [c for c in result.verdict.claim_results if c.verdict in {"supported", "refuted", "conflicting"}]
    assert decisive, "expected at least one decisive verdict"
    for claim in decisive:
        assert claim.evidence, f"decisive verdict without evidence: {claim.claim}"


def test_absence_of_evidence_stays_insufficient_not_refuted(monkeypatch):
    # The LLM, guided by the prompt rule, returns insufficient when the evidence
    # is about a different subject; the pipeline must preserve that (not silently
    # upgrade/downgrade). Guards the 京东造游轮-class error (real event judged false).
    monkeypatch.setenv("RETRIEVAL_CACHE_DIR", tempfile.mkdtemp())
    get_settings.cache_clear()
    bundle, event = _mock_bundle()
    response = {
        "event": {"title": "京东游轮", "summary": "主体不匹配", "anchor_result_id": "R01-1"},
        "claims": [
            {
                "claim": "京东开始造游轮了。",
                "claim_type": "fact",
                "verdict": "insufficient",
                "confidence": "low",
                "evidence_result_ids": ["R01-1"],
                "notes": "检索结果未覆盖该主体，证据不足以判断。",
            }
        ],
        "timeline": [],
    }
    reasoner = _enabled_reasoner(monkeypatch, response)
    result = reasoner.synthesize(
        request=AnalyzeRequest(raw_input="京东开始造游轮了", input_type="text"),
        event=event,
        retrieval_bundle=bundle,
    )
    assert result is not None
    claim = result.verdict.claim_results[0]
    assert claim.verdict == "insufficient"
    assert claim.verdict != "refuted"


def test_extract_query_terms_returns_entity_focused_query(monkeypatch):
    from backend.app.models.schemas import NormalizedEvent

    reasoner = _enabled_reasoner(
        monkeypatch,
        {
            "entities": ["京东", "刘强东", "探海游艇"],
            "keywords": ["造", "游轮", "布局"],
            "primary_query": "京东 刘强东 探海游艇 游轮 布局",
            "aliases": ["Sea Expandary"],
        },
    )
    event = NormalizedEvent(
        title="京东开始造游轮了",
        summary="京东开始造游轮了，而且他早在两年前就打算造游轮",
        input_type="text_news",
        raw_input="京东开始造游轮了，而且他早在两年前就打算造游轮",
    )
    terms = reasoner.extract_query_terms(event=event)
    assert terms is not None
    assert "京东" in terms.entities
    assert "京东" in terms.primary_query
    # The colloquial filler must not survive into the search query.
    assert "而且" not in terms.primary_query
    assert "Sea Expandary" in terms.aliases


def test_extract_query_terms_disabled_returns_none():
    reasoner = LlmAgentReasoner(
        settings=replace(get_settings(), analysis_provider="off", llm_api_key=None)
    )
    from backend.app.models.schemas import NormalizedEvent

    event = NormalizedEvent(summary="x", input_type="text_news", raw_input="x")
    assert reasoner.extract_query_terms(event=event) is None


# --- honest fallback provenance ----------------------------------------------


class _FailingReasoner:
    """LLM is 'enabled' but synthesis never produces a result (parse fail etc.)."""

    enabled = True

    def resolve_question(self, *, event, retrieval_bundle):
        return None

    def synthesize(self, *, request, event, retrieval_bundle):
        return None


def test_llm_enabled_synthesis_fallback_is_flagged_in_provenance(monkeypatch):
    monkeypatch.setenv("AGENT_ORCHESTRATOR_ENABLED", "true")
    monkeypatch.setenv("RETRIEVAL_CACHE_DIR", tempfile.mkdtemp())
    get_settings.cache_clear()

    pipeline = AnalyzePipeline()
    pipeline.agent_reasoner = _FailingReasoner()

    report = pipeline.analyze(AnalyzeRequest(raw_input=_ACID_INPUT, input_type="text"))

    assert report.provenance.claim_source == "rule"
    assert LLM_SYNTHESIS_FALLBACK_REASON in report.provenance.fallback_reasons
    assert report.provenance.fallback_used is True


def test_off_mock_path_has_no_llm_fallback_reason(monkeypatch):
    # Autouse fixture keeps ANALYSIS_PROVIDER=off; synthesis is never attempted.
    monkeypatch.setenv("AGENT_ORCHESTRATOR_ENABLED", "true")
    get_settings.cache_clear()

    pipeline = AnalyzePipeline()
    report = pipeline.analyze(AnalyzeRequest(raw_input=_ACID_INPUT, input_type="text"))

    assert report.provenance.claim_source == "rule"
    assert LLM_SYNTHESIS_FALLBACK_REASON not in report.provenance.fallback_reasons
