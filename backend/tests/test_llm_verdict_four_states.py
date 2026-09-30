"""LLM verdict protocol preserves conflict and degrades on malformed output."""
from __future__ import annotations

import json

import pytest

from backend.app.models.schemas import ClaimResult, EvidenceItem
from backend.app.services.llm_verdict import _parse_verdict_response, llm_judge_claims


def claim() -> ClaimResult:
    return ClaimResult(claim='某市新增确诊50例', claim_type='fact', verdict='insufficient',
                       confidence='low', notes='', evidence=[EvidenceItem(
                           title='新增确诊通报', snippet='某市新增确诊50例', source_name='通报',
                           source_tier='S', published_at='2026-09-30', url='https://example.com/a', relevance_reason='原文')])


def test_conflicting_is_accepted_through_primary_judge():
    original = claim()
    result = llm_judge_claims([original], completion_fn=lambda *_: json.dumps({
        'verdict': 'conflicting', 'confidence': 'medium', 'reason': '两侧可靠来源口径一致但数字不同',
    }))
    assert result[0].verdict == 'conflicting'
    assert result[0].evidence == original.evidence


@pytest.mark.parametrize('payload', [[], [{'verdict': 'supported'}], None, 'supported', {'verdict': []},
                                     {'verdict': 'refuted', 'reason': {}},
                                     {'verdict': 'unknown'}])
def test_malformed_verdict_does_not_raise_or_change_original(payload):
    assert _parse_verdict_response(json.dumps(payload), claim()) is None


def test_non_string_confidence_uses_existing_fallback():
    result = _parse_verdict_response(json.dumps({'verdict': 'supported', 'confidence': []}), claim())
    assert result is not None and result.confidence == 'medium'
