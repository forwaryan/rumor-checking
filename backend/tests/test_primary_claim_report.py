from backend.app.models.schemas import ClaimResult, EvidenceItem, NormalizedEvent, PossibilityItem, ReportProvenance
from backend.app.services.content_check_builder import ContentCheckBuilder
from backend.app.services.primary_claim import primary_fact_claim
from backend.app.services.report_builder import ReportBuilder


def test_primary_rumor_claim_wins_when_context_is_listed_first():
    rumor = "网传景甜被孙割包养了是吗"
    context = ClaimResult(
        claim="景甜方曾就孙宇晨相关热搜发表声明。", claim_type="fact",
        verdict="supported", confidence="medium", evidence=[], notes="背景",
    )
    main = ClaimResult(
        claim="景甜被孙宇晨包养。", claim_type="fact",
        verdict="insufficient", confidence="low", evidence=[], notes="未证实",
    )
    assert primary_fact_claim(rumor, [context, main]) is main



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
    assert reversed_report.independent_source_count == 1
    assert "京东近期" in reversed_report.final_summary
    assert "京东近期" in reversed_report.investigation.reframed_question
    assert "缺少直接证据" in reversed_answer.possible_answers[0].answer


def test_supported_context_does_not_confirm_unproven_personal_rumor():
    rumor = "网传景甜被孙割包养了是吗"
    hit = EvidenceItem(
        title="双方曾就相关热搜发表回应", url="https://news.example.org/response",
        source_name="公开报道", published_at="2026-08-27",
        snippet="相关热搜出现后双方回应", relevance_reason="context", source_tier="B",
    )
    claims = [
        ClaimResult(
            claim="景甜被孙宇晨包养。", claim_type="fact", verdict="insufficient",
            confidence="low", evidence=[], notes="缺少直接证据",
        ),
        ClaimResult(
            claim="景甜方曾就相关热搜发表声明。", claim_type="fact", verdict="supported",
            confidence="medium", evidence=[hit], notes="见相关报道",
        ),
        ClaimResult(
            claim="孙宇晨方曾回应相关争议。", claim_type="fact", verdict="supported",
            confidence="medium", evidence=[hit], notes="见相关报道",
        ),
    ]
    for input_type in ("text_news", "question_only"):
        report = ReportBuilder().build(
            event=NormalizedEvent(title=rumor, summary=rumor, input_type=input_type, raw_input=rumor),
            claim_results=claims, timeline=[], evidence=[hit], evidence_grade="C",
            provenance=ReportProvenance(
                source_type="backend_live", event_source="input_normalized", claim_source="provider",
                evidence_source="retrieval_live", timeline_source="none",
            ),
            retrieval_hits=[hit],
            possibilities_override=[PossibilityItem(
                scenario="包养关系属实", likelihood="medium", probability=65,
                basis="evidence", summary="相关声明被错误当成包养证据。",
            )],
        )
        answer = ContentCheckBuilder().build(report=report, original_input=rumor)
        assert all(item.scenario != "包养关系属实" for item in report.investigation.possibilities)
        assert report.overall_credibility_label == "insufficient_evidence"
        assert report.overall_credibility_score <= 49
        assert "包养" in report.final_summary and "缺少直接证据" in report.final_summary
        assert "包养" in report.investigation.reframed_question
        assert "缺少直接证据" in report.investigation.final_conclusion
        assert "包养" in answer.possible_answers[0].answer
        assert "缺少直接证据" in answer.possible_answers[0].answer


def test_old_denials_do_not_answer_a_recent_company_layoff_question():
    denial = EvidenceItem(
        title="2023年京东否认当年的裁员传闻", url="https://news.example.org/2023-denial",
        source_name="行业新闻", published_at="2023-12-01", snippet="京东称当时没有类似计划",
        relevance_reason="historical context", source_tier="A",
    )
    question = "京东最近是不是有一次大裁员"
    claims = [
        ClaimResult(
            claim="2023年12月京东否认了裁员传闻，称没有类似计划并仍在招聘。",
            claim_type="fact", verdict="supported", confidence="high", evidence=[denial], notes="旧闻",
        ),
        ClaimResult(
            claim="京东历史上曾多次否认裁员传闻。",
            claim_type="fact", verdict="supported", confidence="high", evidence=[denial], notes="背景",
        ),
        ClaimResult(
            claim="京东近期发生了一次大规模裁员。",
            claim_type="fact", verdict="insufficient", confidence="low", evidence=[denial], notes="缺少近期证据",
        ),
    ]
    for ordered in (claims, list(reversed(claims))):
        report = ReportBuilder().build(
            event=NormalizedEvent(title="京东裁员传闻", summary=question, input_type="question_only", raw_input=question),
            claim_results=ordered, timeline=[], evidence=[denial], evidence_grade="A",
            provenance=ReportProvenance(
                source_type="backend_live", event_source="input_normalized", claim_source="provider",
                evidence_source="retrieval_live", timeline_source="none",
            ),
            retrieval_hits=[denial],
        )
        answer = ContentCheckBuilder().build(report=report, original_input=question)
        assert report.overall_credibility_label == "insufficient_evidence"
        assert report.overall_credibility_score <= 49
        assert "京东近期" in report.final_summary and "缺少直接证据" in report.final_summary
        assert "京东近期" in report.investigation.reframed_question
        assert "缺少直接证据" in report.investigation.final_conclusion
        assert "京东近期" in answer.possible_answers[0].answer
        assert "缺少直接证据" in answer.possible_answers[0].answer
