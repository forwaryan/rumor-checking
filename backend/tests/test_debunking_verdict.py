"""Regression tests for the debunking-claim polarity bug.

Reproduces the 美团 case: the only decisive claim was a *supported* debunking
claim (「美团曾对相关传闻进行辟谣」), which the report engine read as confirming
the rumor's core — headline 基本属实 — even though a supported debunking is
evidence the rumor is FALSE.
"""
from __future__ import annotations

from backend.app.models.schemas import (
    ClaimResult,
    EvidenceItem,
    NormalizedEvent,
    ReportProvenance,
)
from backend.app.services.report_builder import ReportBuilder, _claim_is_debunking


def _event() -> NormalizedEvent:
    return NormalizedEvent(
        title="网传美团裁员70%产品人员",
        summary="网传美团裁员70%产品人员",
        input_type="text_news",
        raw_input="美团最近裁了70%的产品",
    )


def _provenance() -> ReportProvenance:
    return ReportProvenance(
        source_type="backend_live",
        event_source="input_normalized",
        claim_source="provider",
        evidence_source="retrieval_live",
        timeline_source="none",
    )


def _hit(url: str, title: str, tier: str = "A") -> EvidenceItem:
    return EvidenceItem(
        title=title,
        url=url,
        source_name=url.split("//")[-1].split("/")[0],
        published_at="2026-07-20T09:00:00+08:00",
        snippet=title,
        relevance_reason="retrieved",
        source_tier=tier,
    )


def test_claim_is_debunking_recognizes_denial_predicates():
    assert _claim_is_debunking("美团曾对相关传闻进行辟谣")
    assert _claim_is_debunking("警方否认该说法")
    assert _claim_is_debunking("该消息不实")
    # A neutral response/investigation claim is NOT a debunk — it must not flip.
    assert not _claim_is_debunking("美团回应了此事")
    assert not _claim_is_debunking("美团最近进行了裁员")


def test_supported_debunking_does_not_read_as_rumor_confirmed():
    """The 美团 reproduction: one supported 辟谣 claim + insufficient detail
    claims must NOT yield a 核心事件大体能对上 / 基本属实 style verdict."""
    builder = ReportBuilder()
    debunk_hit = _hit("https://news.china.com/meituan", "美团产品岗裁员50%消息不实 官方已辟谣")
    claims = [
        ClaimResult(
            claim="美团最近进行了裁员。",
            claim_type="fact",
            verdict="insufficient",
            confidence="low",
            evidence=[],
            notes="检索结果未直接提及。",
        ),
        ClaimResult(
            claim="美团裁员涉及70%的产品人员。",
            claim_type="fact",
            verdict="insufficient",
            confidence="low",
            evidence=[],
            notes="无检索结果提及70%比例。",
        ),
        ClaimResult(
            claim="美团曾对相关传闻进行辟谣。",
            claim_type="fact",
            verdict="supported",
            confidence="medium",
            evidence=[debunk_hit],
            notes="官方辟谣。",
        ),
    ]
    report = builder.build(
        event=_event(),
        claim_results=claims,
        timeline=[],
        evidence=[debunk_hit],
        evidence_grade="B",
        provenance=_provenance(),
        retrieval_hits=[debunk_hit],
    )
    # The summary must not claim the rumor's core checks out.
    assert "核心事件大体能对上" not in report.final_summary
    assert "辟谣" in report.final_summary or "不属实" in report.final_summary
    # The credibility label must not read as credible.
    assert report.overall_credibility_label in {"low_credibility", "insufficient_evidence", "mixed"}


def test_supported_debunking_scores_low_credibility_with_high_trust():
    """With a high-trust debunking source and no confirming support, the rumor
    is contradicted — label must be low_credibility, not high/medium."""
    builder = ReportBuilder()
    debunk_hit = _hit("https://www.meituan.com/notice", "辟谣公告：产品岗裁员50%系不实消息", tier="A")
    label = builder._derive_credibility_label(
        overall_score=80.0,
        claim_results=[
            ClaimResult(
                claim="美团对产品岗裁员传闻进行辟谣，称消息不实。",
                claim_type="fact",
                verdict="supported",
                confidence="high",
                evidence=[debunk_hit],
                notes="官方辟谣。",
            ),
        ],
        evidence=[debunk_hit],
    )
    assert label == "low_credibility"


def test_genuine_supported_core_still_reads_as_credible():
    """Guard against over-correction: a non-debunking supported fact with a
    high-trust source must still be able to score as credible."""
    builder = ReportBuilder()
    cited = _hit("https://finance.example.com/pdd", "拼多多雄安研发中心正式设立", tier="A")
    label = builder._derive_credibility_label(
        overall_score=80.0,
        claim_results=[
            ClaimResult(
                claim="拼多多在雄安设立研发中心。",
                claim_type="fact",
                verdict="supported",
                confidence="high",
                evidence=[cited],
                notes="grounded",
            ),
        ],
        evidence=[cited],
    )
    assert label == "high_credibility"
