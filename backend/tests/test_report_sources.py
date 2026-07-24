from __future__ import annotations

from backend.app.models.schemas import (
    ClaimResult,
    EvidenceItem,
    NormalizedEvent,
    ReportProvenance,
)
from backend.app.services.report_builder import ReportBuilder


def _event() -> NormalizedEvent:
    return NormalizedEvent(
        title="拼多多在雄安买了三栋楼招了5000研发人员",
        summary="拼多多在雄安买了三栋楼招了5000研发人员",
        input_type="text_news",
        raw_input="拼多多在雄安买了三栋楼招了5000研发人员",
    )


def _provenance(evidence_source: str = "retrieval_live") -> ReportProvenance:
    return ReportProvenance(
        source_type="backend_live",
        event_source="input_normalized",
        claim_source="provider",
        evidence_source=evidence_source,
        timeline_source="none",
    )


def _hit(url: str, title: str) -> EvidenceItem:
    return EvidenceItem(
        title=title,
        url=url,
        source_name=url.split("//")[-1].split("/")[0],
        published_at="2026-07-20T09:00:00+08:00",
        snippet=title,
        relevance_reason="retrieved",
    )


def test_uncited_retrieval_hits_do_not_count_as_evidence():
    # The pinduoduo failure mode: a brand page is retrieved but no claim cites it.
    # It must land in retrieval_hits, NOT sources (which drives "证据 N 条").
    builder = ReportBuilder()
    uncited = _hit("https://pifa.pinduoduo.com/", "拼多多批发 官方采购批发平台")
    claims = [
        ClaimResult(
            claim="拼多多在雄安购买了办公楼。",
            claim_type="fact",
            verdict="insufficient",
            confidence="low",
            evidence=[],  # no evidence cited
            notes="检索结果未提及。",
        ),
    ]
    report = builder.build(
        event=_event(),
        claim_results=claims,
        timeline=[],
        evidence=[uncited],  # the pool the old code dumped into sources verbatim
        evidence_grade="C",
        provenance=_provenance(),
        retrieval_hits=[uncited],
    )
    assert report.sources == []
    assert any(h.url == "https://pifa.pinduoduo.com/" for h in report.retrieval_hits)


def test_cited_evidence_populates_sources():
    builder = ReportBuilder()
    cited = _hit("https://finance.example.com/pdd-xiongan", "拼多多雄安研发中心")
    claims = [
        ClaimResult(
            claim="拼多多在雄安设立研发中心。",
            claim_type="fact",
            verdict="supported",
            confidence="high",
            evidence=[cited],
            notes="grounded",
        ),
    ]
    report = builder.build(
        event=_event(),
        claim_results=claims,
        timeline=[],
        evidence=[cited],
        evidence_grade="B",
        provenance=_provenance(),
        retrieval_hits=[cited],
    )
    assert [s.url for s in report.sources] == ["https://finance.example.com/pdd-xiongan"]


def test_sources_dedupe_across_claims():
    builder = ReportBuilder()
    shared = _hit("https://news.example.com/a", "共享证据")
    claims = [
        ClaimResult(claim="c1。", claim_type="fact", verdict="supported", confidence="high", evidence=[shared], notes="n"),
        ClaimResult(claim="c2。", claim_type="fact", verdict="supported", confidence="high", evidence=[shared], notes="n"),
    ]
    report = builder.build(
        event=_event(),
        claim_results=claims,
        timeline=[],
        evidence=[shared],
        evidence_grade="B",
        provenance=_provenance(),
        retrieval_hits=[shared],
    )
    assert len(report.sources) == 1
