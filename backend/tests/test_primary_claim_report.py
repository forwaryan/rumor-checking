from backend.app.models.schemas import ClaimResult, EvidenceItem, NormalizedEvent, ReportProvenance
from backend.app.services.content_check_builder import ContentCheckBuilder
from backend.app.services.report_builder import ReportBuilder


def test_supported_industry_context_does_not_confirm_unproven_company_layoff():
    hit = EvidenceItem(
        title="互联网行业近年来多次人员调整",
        url="https://news.example.org/industry-layoffs",
        source_name="行业新闻",
        published_at="2026-10-20T09:00:00+08:00",
        snippet="多家公司过去几年有过人员调整",
        relevance_reason="background",
        source_tier="A",
    )
    report = ReportBuilder().build(
        event=NormalizedEvent(
            title="京东近期裁员传闻",
            summary="京东最近是不是有一次大裁员",
            input_type="question_only",
            raw_input="京东最近是不是有一次大裁员",
        ),
        claim_results=[
            ClaimResult(
                claim="京东近期发生了一次大规模裁员。",
                claim_type="fact", verdict="insufficient", confidence="low",
                evidence=[], notes="没有直接报道证明该事件。",
            ),
            ClaimResult(
                claim="2023至2026年间中国互联网行业发生过多轮裁员。",
                claim_type="fact", verdict="supported", confidence="high",
                evidence=[hit], notes="行业背景有公开报道。",
            ),
        ],
        timeline=[], evidence=[hit], evidence_grade="A",
        provenance=ReportProvenance(
            source_type="backend_live", event_source="input_normalized",
            claim_source="provider", evidence_source="retrieval_live", timeline_source="none",
        ),
        retrieval_hits=[hit],
    )
    answer = ContentCheckBuilder().build(report=report, original_input="京东最近是不是有一次大裁员")

    assert report.mode == "partial_mode"
    assert report.overall_credibility_label == "insufficient_evidence"
    assert report.overall_credibility_score <= 49
    assert "京东近期" in report.final_summary and "缺少直接证据" in report.final_summary
    assert "核心事件大体能对上" not in report.final_summary
    assert "京东近期" in report.investigation.reframed_question
    assert "不能根据其他背景事实认定" in report.investigation.final_conclusion
    assert "缺少直接证据" in answer.possible_answers[0].answer
    assert "核心事件更像成立" not in answer.possible_answers[0].answer
    assert answer.likely_true[0].claim.startswith("2023至2026")

    reversed_report = ReportBuilder().build(
        event=NormalizedEvent(
            title="京东近期裁员传闻", summary="京东最近是不是有一次大裁员",
            input_type="question_only", raw_input="京东最近是不是有一次大裁员",
        ),
        claim_results=list(reversed(report.claim_results)),
        timeline=[], evidence=[hit], evidence_grade="A",
        provenance=report.provenance, retrieval_hits=[hit],
    )
    reversed_answer = ContentCheckBuilder().build(
        report=reversed_report, original_input="京东最近是不是有一次大裁员"
    )
    assert reversed_report.overall_credibility_label == "insufficient_evidence"
    assert "京东近期" in reversed_report.final_summary
    assert "京东近期" in reversed_report.investigation.reframed_question
    assert "缺少直接证据" in reversed_answer.possible_answers[0].answer
