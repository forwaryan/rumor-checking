"""Tests for structured output validation (P0)."""
from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from backend.app.agent.structured_output import (
    ActionSequenceSchema,
    CriticResponseSchema,
    EnrichmentResponseSchema,
    InvestigationPlanSchema,
    NextActionSchema,
    QueryTermsSchema,
    RefineResponseSchema,
    StructuredOutputError,
    SynthesisResponseSchema,
    parse_validated,
    parse_validated_or_raise,
    schema_validator,
)


# --- schema_validator callback tests ---


class SimpleSchema(BaseModel):
    name: str
    value: int


def test_validator_rejects_empty():
    v = schema_validator(SimpleSchema)
    assert v("") is False
    assert v("   ") is False


def test_validator_accepts_valid_json():
    v = schema_validator(SimpleSchema)
    assert v(json.dumps({"name": "test", "value": 42})) is True


def test_validator_rejects_invalid_schema():
    v = schema_validator(SimpleSchema)
    # Missing required field
    assert v(json.dumps({"name": "test"})) is False
    # Wrong type
    assert v(json.dumps({"name": "test", "value": "not_int"})) is False


def test_validator_handles_markdown_fenced_json():
    v = schema_validator(SimpleSchema)
    content = '```json\n{"name": "test", "value": 42}\n```'
    assert v(content) is True


def test_validator_handles_lenient_json():
    v = schema_validator(SimpleSchema)
    # Trailing comma (lenient parser handles this)
    content = '{"name": "test", "value": 42,}'
    assert v(content) is True


def test_validator_rejects_non_json():
    v = schema_validator(SimpleSchema)
    assert v("This is not JSON at all") is False


# --- parse_validated tests ---


def test_parse_validated_success():
    content = json.dumps({"name": "hello", "value": 99})
    result = parse_validated(content, SimpleSchema)
    assert result is not None
    assert result.name == "hello"
    assert result.value == 99


def test_parse_validated_returns_none_on_failure():
    assert parse_validated("", SimpleSchema) is None
    assert parse_validated("invalid", SimpleSchema) is None
    assert parse_validated(json.dumps({"name": "x"}), SimpleSchema) is None


def test_parse_validated_with_extra_fields():
    content = json.dumps({"name": "test", "value": 1, "extra": "ignored"})
    result = parse_validated(content, SimpleSchema)
    assert result is not None
    assert result.name == "test"


# --- parse_validated_or_raise tests ---


def test_parse_or_raise_success():
    content = json.dumps({"name": "ok", "value": 5})
    result = parse_validated_or_raise(content, SimpleSchema)
    assert result.name == "ok"
    assert result.value == 5


def test_parse_or_raise_empty_content():
    with pytest.raises(StructuredOutputError, match="empty content"):
        parse_validated_or_raise("", SimpleSchema)


def test_parse_or_raise_no_json():
    with pytest.raises(StructuredOutputError, match="no JSON found"):
        parse_validated_or_raise("no json here whatsoever!", SimpleSchema)


def test_parse_or_raise_schema_mismatch():
    content = json.dumps({"name": "test"})  # missing 'value'
    with pytest.raises(StructuredOutputError, match="Schema validation failed"):
        parse_validated_or_raise(content, SimpleSchema)


# --- Pre-built schema validation ---


def test_investigation_plan_schema():
    content = json.dumps({"should_continue": True, "follow_up_query": "拼多多 雄安", "reason": "weak evidence"})
    result = parse_validated(content, InvestigationPlanSchema)
    assert result is not None
    assert result.should_continue is True
    assert result.follow_up_query == "拼多多 雄安"


def test_investigation_plan_schema_minimal():
    content = json.dumps({"should_continue": False})
    result = parse_validated(content, InvestigationPlanSchema)
    assert result is not None
    assert result.should_continue is False
    assert result.follow_up_query is None


def test_next_action_schema():
    content = json.dumps({"next_action": "synthesize", "reason": "evidence strong"})
    result = parse_validated(content, NextActionSchema)
    assert result is not None
    assert result.next_action == "synthesize"


def test_action_sequence_schema():
    content = json.dumps({"actions": ["investigate", "synthesize"], "reason": "need more"})
    result = parse_validated(content, ActionSequenceSchema)
    assert result is not None
    assert result.actions == ["investigate", "synthesize"]


def test_query_terms_schema():
    content = json.dumps({
        "entities": ["拼多多", "雄安"],
        "keywords": ["买楼", "办公"],
        "primary_query": "拼多多 雄安 买楼",
        "aliases": ["PDD"],
    })
    result = parse_validated(content, QueryTermsSchema)
    assert result is not None
    assert "拼多多" in result.entities


def test_synthesis_response_schema():
    content = json.dumps({
        "claims": [
            {"claim": "拼多多在雄安买楼", "claim_type": "fact", "verdict": "insufficient",
             "confidence": "medium", "evidence_result_ids": ["r1"], "notes": "待查"}
        ]
    })
    result = parse_validated(content, SynthesisResponseSchema)
    assert result is not None
    assert len(result.claims) == 1
    assert result.claims[0].claim == "拼多多在雄安买楼"


def test_synthesis_response_empty_claims():
    content = json.dumps({"claims": []})
    result = parse_validated(content, SynthesisResponseSchema)
    assert result is not None
    assert result.claims == []


def test_critic_response_schema():
    content = json.dumps({"revisions": [{"index": 0, "keep": False, "reason": "证据不足"}]})
    result = parse_validated(content, CriticResponseSchema)
    assert result is not None
    assert len(result.revisions) == 1
    assert result.revisions[0].keep is False


def test_refine_response_schema():
    content = json.dumps({
        "refined_claims": [
            {"index": 0, "verdict": "refuted", "confidence": "high",
             "evidence_result_ids": ["r1"], "notes": "仅1栋"}
        ]
    })
    result = parse_validated(content, RefineResponseSchema)
    assert result is not None
    assert result.refined_claims[0].verdict == "refuted"


def test_enrichment_response_schema():
    content = json.dumps({
        "event": {"title": "事件标题", "summary": "摘要"},
        "scenarios": [
            {"label": "属实", "probability": 70, "basis": "evidence", "summary": "有证据"},
            {"label": "夸大", "probability": 30, "basis": "prior", "summary": "可能夸大"},
        ],
        "timeline": [
            {"node_type": "origin", "result_id": "r1", "summary": "最早", "why_selected": "起点"},
        ],
    })
    result = parse_validated(content, EnrichmentResponseSchema)
    assert result is not None
    assert result.event.title == "事件标题"
    assert len(result.scenarios) == 2
    assert result.scenarios[0].probability == 70
    assert len(result.timeline) == 1


def test_enrichment_response_partial():
    content = json.dumps({"scenarios": [{"label": "A", "probability": 100, "summary": "x"}]})
    result = parse_validated(content, EnrichmentResponseSchema)
    assert result is not None
    assert result.event is None
    assert len(result.scenarios) == 1
    assert result.timeline == []


# --- Integration: validator with retry semantics ---


def test_validator_used_as_is_valid_callback():
    """Simulate how _request_completion uses the validator."""
    v = schema_validator(SynthesisResponseSchema)

    # Truncated JSON — retry
    assert v('{"claims": [{"claim": "test"') is False

    # Valid but empty claims — still valid schema
    assert v('{"claims": []}') is True

    # Complete valid response
    assert v(json.dumps({"claims": [{"claim": "x", "verdict": "supported"}]})) is True


def test_validator_strict_mode():
    """Non-lenient mode requires exact JSON."""
    v = schema_validator(SimpleSchema, lenient_json=False)
    # Markdown fence not parsed in strict mode if lenient parser disabled
    # But our _extract_json falls back to json.loads on the raw content
    assert v(json.dumps({"name": "x", "value": 1})) is True
