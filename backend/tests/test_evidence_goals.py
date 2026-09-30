import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from backend.app.core.config import get_settings
from backend.app.models.schemas import AnalyzeRequest, ClaimItem, ClaimResult, NormalizedEvent
from backend.app.services.agent_reasoner import LlmAgentReasoner
from backend.app.services.analyze_pipeline import AnalyzePipeline
from backend.app.services.evidence_goals import apply_evidence_goals, restrict_review_results, review_claim_items
from backend.app.services.per_claim_retriever import enrich_retrieval_for_claims, refine_evidence_gaps
from backend.app.services.retrieval_models import RetrievalBundle, SearchResult
from backend.app.services.verdict_engine import VerdictEngine, VerdictEvaluation


def _result(snippet, title="市立博物馆参观公告"):
    return SearchResult(case_id="test", query="test", result_id="e1", title=title,
                        url="https://museum.example.org/notice", source_name="市立博物馆",
                        published_at="", snippet=snippet, source_tier="S")


def _claim(text, evidence, verdict="supported"):
    return ClaimResult(claim=text, claim_type="fact", verdict=verdict, confidence="high",
                       evidence=[evidence.to_evidence(relevance_reason="相关公告")], notes="判定说明",
                       truth_probability=90, probability_basis="evidence")


@pytest.mark.parametrize("claim,title,snippet,dimension", [
    ("市立博物馆周三免费参观", "市立博物馆参观公告", "周三开放时间为9点至17点。", "price"),
    ("市立博物馆周三免费参观", "市立博物馆周三免费参观", "市立博物馆周三免费参观。开放时间9点至17点。", "price"),
    ("市立博物馆周三免费参观", "市立博物馆参观公告", "本馆提供免费停车服务。", "price"),
    ("市立博物馆周三免费参观", "市立博物馆参观公告", "本馆免费停车场开放至17点。", "price"),
    ("北京至上海有直飞航班", "北京至上海直飞航班", "北京机场航站楼开放时间为6点。", "route"),
    ("北京至上海有直飞航班", "航班公告", "北京至广州已开通直飞航班。", "route"),
    ("北京至上海有直飞航班", "航班公告", "北京至上海航线航班问题请咨询客服。", "route"),
    ("北京直飞上海的航班", "航班公告", "北京至广州已开通直飞航班。", "route"),
])
@pytest.mark.parametrize("verdict", ["supported", "refuted", "conflicting"])
def test_missing_property_only_annotates_gap(claim, title, snippet, dimension, verdict):
    evidence = _result(snippet, title)
    original = _claim(claim, evidence, verdict)
    checked = apply_evidence_goals([original], RetrievalBundle(query=claim, canonical_results=(evidence,)))[0]
    # A pattern miss flags a missing proof; it never re-adjudicates the claim.
    assert checked.verdict == original.verdict
    assert checked.confidence == original.confidence
    assert checked.truth_probability == original.truth_probability
    assert checked.correction == original.correction
    assert checked.evidence == original.evidence
    assert checked.evidence_gaps[0].dimension == dimension
    assert checked.evidence_gaps[0].suggested_queries
    ClaimResult.model_validate(checked.model_dump())


@pytest.mark.parametrize("claim,title,snippet", [
    ("市立博物馆周三免费参观", "市立博物馆参观公告", "本馆周三免费开放，需提前预约。"),
    ("市立博物馆门票50元", "市立博物馆参观公告", "成人门票为50元，儿童免票。"),
    ("北京至上海有直飞航班", "航班公告", "北京至上海每天都有直飞航班。"),
    ("北京至上海有直飞航班", "航班公告", "北京至上海无直飞航班，必须在广州转机。"),
    ("从北京直飞上海的航班", "航班公告", "北京至上海有直飞航班。"),
])
def test_property_coverage_preserves_existing_judgment(claim, title, snippet):
    evidence = _result(snippet, title)
    bundle = RetrievalBundle(query=claim, canonical_results=(evidence,))
    for verdict in ("supported", "refuted", "insufficient"):
        checked = apply_evidence_goals([_claim(claim, evidence, verdict)], bundle)[0]
        assert checked.verdict == verdict
        assert not checked.evidence_gaps


@pytest.mark.parametrize("claim,title,snippet", [
    ("某市地铁票价上涨到10元", "某市地铁票价维持2元起步", "某市地铁执行2元起步价，全程最高9元，价格保持不变。"),
    ("某市地铁票价10元", "某市地铁票制公告", "全程最高9元。"),
    ("某市公交票价5元", "某市公交车乘车公告", "公交车执行1.5元起步价。"),
    ("某市有轨电车票价5元", "某市有轨电车票制公告", "乘客支付三元起步价。"),
    ("某市轻轨票价5元", "某市轻轨乘车公告", "单程票价为4元，站内停车收费10元。"),
    ("某市地铁票价10元", "某市地铁乘车公告", "儿童免费乘坐。"),
    ("某市地铁票价10元", "某市地铁服务公告", "停车每小时5元。地铁执行2元起步价。"),
])
@pytest.mark.parametrize("verdict", ["supported", "refuted", "conflicting", "insufficient"])
def test_transit_fare_coverage_preserves_judgment_without_matching_claim_value(claim, title, snippet, verdict):
    evidence = _result(snippet, title)
    checked = apply_evidence_goals([_claim(claim, evidence, verdict)],
                                   RetrievalBundle(query=claim, canonical_results=(evidence,)))[0]
    assert checked.verdict == verdict
    assert not checked.evidence_gaps


@pytest.mark.parametrize("title,snippet", [
    ("某市地铁服务公告", "地铁每天6点开始运营，9点增开列车。"),
    ("某市地铁服务公告", "地铁站提供免费停车服务。"),
    ("某市地铁服务公告", "地铁站停车收费2元起步价，全程最高9元。"),
    ("某市地铁服务公告", "地铁站提供寄存服务，寄存收费2元起步。"),
    ("某市地铁服务公告", "公交执行2元起步价，全程最高9元。"),
    ("某市地铁服务公告", "站内公园门票收费2元。"),
    ("某市地铁服务公告", "出租车执行2元起步价。"),
    ("某市地铁服务公告", "地铁票价尚未公布，出租车执行2元起步价。"),
    ("某市地铁服务公告", "地铁站停车收费2元起步价。全程最高9元。"),
    ("某市地铁票制公告", "地铁站停车收费2元起步价。全程最高9元。"),
    ("某市地铁票制公告", "出租车提供接驳服务。全程最高9元。"),
    ("某市地铁服务公告", "地铁站购物中心游乐设施2元起步价。"),
    ("某市地铁服务公告", "全程最高9元。"),
    ("某市公交票制公告", "全程最高9元。"),
    ("某市地铁票价2元起步", "某市地铁票价2元起步。"),
])
def test_transit_fare_needs_substantive_matching_transport_content(title, snippet):
    claim = "某市地铁票价上涨到10元"
    evidence = _result(snippet, title)
    checked = apply_evidence_goals([_claim(claim, evidence, "refuted")],
                                   RetrievalBundle(query=claim, canonical_results=(evidence,)))[0]
    assert checked.verdict == "refuted"
    assert [gap.dimension for gap in checked.evidence_gaps] == ["price"]


def test_unrecognized_domain_keeps_existing_judgment():
    evidence = _result("这款软件无需付费即可使用。", "产品说明")
    checked = apply_evidence_goals([_claim("这款软件免费", evidence)],
                                   RetrievalBundle(query="软件", canonical_results=(evidence,)))[0]
    assert checked.verdict == "supported"
    assert not checked.evidence_gaps


@pytest.mark.parametrize("claim,snippet,dimension", [
    ("星河公司于2024年5月1日成立", "星河公司提供软件服务。", "time"),
    ("星河公司于2024年5月1日成立", "星河公司于2024年5月1日发布招聘公告。", "time"),
    ("星河公司招聘100名员工", "星河公司发布招聘公告，成立于2024年。", "quantity"),
    ("星河公司招聘100名员工", "星河公司共有100家门店，正在招聘员工。", "quantity"),
    ("星河公司所有门店都已停业", "星河公司门店发布营业安排。", "scope"),
    ("星河公司所有门店都已停业", "星河公司全部员工参加培训，门店营业安排已发布。", "scope"),
    ("星河公司所有门店都已停业", "星河公司部分门店停业。", "scope"),
    ("星河公司于2024年成立", "明月公司于2024年成立。", "time"),
    ("星河公司于2024年成立", "星河公司发布声明，明月公司于2024年成立。", "time"),
    ("星河公司于2024年开业", "星河公司于2023年停业。", "time"),
    ("星河公司招聘100名员工", "明月公司招聘100名员工。", "quantity"),
    ("星河公司所有门店都已停业", "明月公司所有门店都已停业。", "scope"),
])
@pytest.mark.parametrize("verdict", ["supported", "refuted", "conflicting"])
def test_explicit_attribute_gap_is_annotated(claim, snippet, dimension, verdict):
    evidence = _result(snippet, "企业公告")
    original = _claim(claim, evidence, verdict)
    checked = apply_evidence_goals([original], RetrievalBundle(query=claim, canonical_results=(evidence,)))[0]
    assert checked.verdict == original.verdict
    assert dimension in {gap.dimension for gap in checked.evidence_gaps}
    assert checked.truth_probability == original.truth_probability
    assert checked.correction == original.correction


@pytest.mark.parametrize("claim,snippet", [
    ("星河公司于2024年5月1日成立", "星河公司成立于2023年5月1日。"),
    ("星河公司于2024-05-01成立", "星河公司于2023年5月1日成立。"),
    ("星河公司于2024年成立", "星河公司尚未成立。"),
    ("星河公司招聘100名员工", "星河公司本次仅招聘50人。"),
    ("星河公司招聘100名员工", "星河公司没有招聘员工。"),
    ("星河公司招聘一百名员工", "星河公司计划招聘五十人。"),
    ("星河公司招聘100名员工", "星河公司招聘人数为0人。"),
    ("星河公司所有门店都已停业", "星河公司只有部分门店停业。"),
    ("星河公司所有门店都已停业", "星河公司所有门店仍正常营业。"),
    ("星河公司所有门店都已停业", "星河公司并非所有门店都已停业。"),
    ("星河公司仅招聘研发岗位", "星河公司招聘岗位包括研发和销售，并非仅招聘研发。"),
])
@pytest.mark.parametrize("verdict", ["supported", "refuted", "conflicting", "insufficient"])
def test_attribute_coverage_does_not_require_claim_value(claim, snippet, verdict):
    evidence = _result(snippet, "企业公告")
    checked = apply_evidence_goals([_claim(claim, evidence, verdict)],
                                   RetrievalBundle(query=claim, canonical_results=(evidence,)))[0]
    assert checked.verdict == verdict
    assert not checked.evidence_gaps


@pytest.mark.parametrize("claim", ["星河公司于2024年成立", "星河公司招聘100名员工", "星河公司所有门店都已停业"])
def test_new_attributes_need_raw_related_content(claim):
    evidence = _result(f"{claim}。其他服务请查看公告。", claim)
    original = _claim(claim, evidence)
    original.evidence[0].snippet = claim
    bundle = RetrievalBundle(query=claim, canonical_results=(evidence,))
    assert apply_evidence_goals([original], bundle)[0].evidence_gaps
    assert not apply_evidence_goals([original], bundle, {"e1": f"{claim}。"})[0].evidence_gaps


def test_publication_date_and_model_quote_do_not_cover_event_time():
    claim = "星河公司于2024年成立"
    evidence = replace(_result("星河公司提供软件服务。", "星河公司成立公告"), published_at="2024-01-01")
    original = _claim(claim, evidence)
    original.evidence[0].stance_quote = "星河公司于2024年成立。"
    checked = apply_evidence_goals([original], RetrievalBundle(query=claim, canonical_results=(evidence,)))[0]
    assert checked.verdict == original.verdict
    assert checked.evidence_gaps[0].dimension == "time"


@pytest.mark.parametrize("claim_type", ["opinion", "prediction", "unverifiable"])
def test_new_attributes_do_not_change_nonfacts(claim_type):
    evidence = _result("企业简介", "企业公告")
    original = _claim("星河公司2025年招聘100名员工，所有门店都将开业", evidence)
    original.claim_type = claim_type
    assert apply_evidence_goals([original], RetrievalBundle(query="企业", canonical_results=(evidence,))) == [original]


@pytest.mark.parametrize("claim", [
    "这款软件已经开放", "明年情况将完全不同", "公司编号为100", "这个人有百来个想法",
    "公司裁员100人后招聘50人", "该公司预计明年成立", "星河公司于二〇二四年成立",
])
def test_unrecognized_attribute_format_keeps_existing_path(claim):
    evidence = _result("相关材料", "信息")
    checked = apply_evidence_goals([_claim(claim, evidence)],
                                   RetrievalBundle(query=claim, canonical_results=(evidence,)))[0]
    assert checked.verdict == "supported"
    assert not checked.evidence_gaps


@pytest.mark.parametrize("claim,query_term", [
    ("星河公司于2024年成立", "时间"),
    ("星河公司招聘100名员工", "数量"),
    ("星河公司所有门店都已停业", "范围"),
])
def test_new_attribute_gaps_drive_focused_queries(claim, query_term):
    bundle = RetrievalBundle(query=claim, canonical_results=(_result("公司简介", "企业公告"),))
    queries = []

    def retrieve(event, request_context):
        queries.append(request_context["force_retrieval_query"])
        return bundle

    enrich_retrieval_for_claims([ClaimItem(claim=claim, claim_type="fact")], bundle,
                              SimpleNamespace(retrieve_for_event=retrieve),
                              NormalizedEvent(summary=claim, raw_input=claim, input_type="text_news"), iteration=1)
    assert queries
    assert query_term in queries[0]


def test_uncited_property_cannot_fill_cited_evidence_gap():
    evidence = _result("周三9点开放。")
    other = replace(_result("周三免费开放。"), result_id="e2", url="https://other.example.org")
    checked = apply_evidence_goals([_claim("市立博物馆周三免费参观", evidence)],
                                   RetrievalBundle(query="museum", canonical_results=(evidence, other)))[0]
    assert [gap.dimension for gap in checked.evidence_gaps] == ["price"]


def test_raw_body_can_cover_property():
    evidence = _result("周三9点开放。")
    checked = apply_evidence_goals([_claim("市立博物馆周三免费参观", evidence)],
                                   RetrievalBundle(query="museum", canonical_results=(evidence,)),
                                   {"e1": "周三免费开放。"})[0]
    assert not checked.evidence_gaps


def test_fetched_body_retains_substantive_sentence_matching_title():
    claim = "明泉市博物馆周三免费开放"
    evidence = _result(claim, claim)
    bundle = RetrievalBundle(query=claim, canonical_results=(evidence,))
    checked = apply_evidence_goals([_claim(claim, evidence)], bundle, {"e1": f"{claim}。"})[0]
    assert checked.verdict == "supported"
    assert not checked.evidence_gaps
    without_body = apply_evidence_goals([_claim(claim, evidence)], bundle)[0]
    assert without_body.evidence_gaps


def test_fetched_supplement_body_in_snippet_is_not_discarded_as_title():
    claim = "明泉市博物馆周三免费开放"
    evidence = replace(_result(claim, claim), case_id="supplemental")
    checked = apply_evidence_goals([_claim(claim, evidence)], RetrievalBundle(query=claim, canonical_results=(evidence,)))[0]
    assert not checked.evidence_gaps


@pytest.mark.parametrize("destination,expected_gap", [("澄海市", False), ("星川市", True)])
def test_route_grammar_is_excluded_from_city_endpoints(destination, expected_gap):
    claim = "远桥市机场已经开通到澄海市的直飞航班"
    evidence = _result("机场航站楼开放时间为6点。", "远桥市机场航班公告")
    checked = apply_evidence_goals([_claim(claim, evidence)],
                                   RetrievalBundle(query=claim, canonical_results=(evidence,)),
                                   {"e1": f"远桥市机场开通至{destination}的直飞航线。"})[0]
    assert checked.verdict == "supported"
    assert bool(checked.evidence_gaps) == expected_gap


def test_explicit_mock_evidence_is_checked_against_its_own_raw_content():
    evidence = _result("周三免费开放。")
    original = _claim("市立博物馆周三免费参观", evidence)
    checked = apply_evidence_goals([original], None, raw_evidence=original.evidence)[0]
    assert checked.verdict == "supported"
    assert not checked.evidence_gaps


def test_rule_and_llm_verdicts_share_gap_annotation(monkeypatch):
    claim = "市立博物馆周三免费参观"
    evidence = _result("周三开放时间为9点至17点。")
    monkeypatch.setattr("backend.app.services.verdict_engine.llm_judge_claims", lambda *args, **kwargs: [_claim(claim, evidence)])
    verdict = VerdictEngine().evaluate_with_source(
        request=AnalyzeRequest(raw_input=claim), event=NormalizedEvent(summary=claim, raw_input=claim, input_type="text_news"),
        claims=[ClaimItem(claim=claim, claim_type="fact")],
        retrieval_bundle=RetrievalBundle(query=claim, canonical_results=(evidence,)),
    )
    assert verdict.claim_results[0].verdict == "supported"
    assert verdict.claim_results[0].evidence_gaps[0].dimension == "price"


def test_gap_query_targets_price_instead_of_number():
    claim = "市立博物馆周三免费参观"
    bundle = RetrievalBundle(query=claim, canonical_results=(_result("周三9点开放。"),))
    queries = []

    def retrieve(event, request_context):
        queries.append(request_context["force_retrieval_query"])
        return bundle

    enrich_retrieval_for_claims([ClaimItem(claim=claim, claim_type="fact")], bundle,
                              SimpleNamespace(retrieve_for_event=retrieve),
                              NormalizedEvent(summary=claim, raw_input=claim, input_type="text_news"), iteration=1)
    assert "门票" in queries[0]
    assert "真实数量" not in queries[0]


def test_review_scope_drops_unselected_claims_and_keeps_missing_insufficient():
    evidence = _result("正文")
    request = AnalyzeRequest(raw_input="旧报告", request_context={"review_claim_texts": ["要复核的声明", "缺失的声明"]})
    results = restrict_review_results([_claim("要复核的声明。", evidence), _claim("其他声明", evidence)], request)
    assert [item.claim for item in results] == ["要复核的声明", "缺失的声明"]
    assert results[1].verdict == "insufficient"


@pytest.mark.parametrize("claim_type", ["opinion", "prediction", "unverifiable"])
def test_review_preserves_nonfact_type_even_when_synthesis_calls_it_fact(claim_type):
    evidence = _result("相关正文")
    request = AnalyzeRequest(raw_input="旧报告", request_context={
        "review_claim_texts": ["所选声明", "缺失声明"], "review_claim_types": [claim_type, claim_type],
    })
    assert [item.claim_type for item in review_claim_items(request)] == [claim_type, claim_type]
    results = restrict_review_results([_claim("所选声明", evidence)], request)
    assert [item.claim_type for item in results] == [claim_type, claim_type]
    assert all(item.verdict == "insufficient" for item in results)
    assert all(item.truth_probability is None for item in results)


def test_review_types_remain_aligned_when_empty_text_is_filtered():
    request = AnalyzeRequest(raw_input="旧报告", request_context={
        "review_claim_texts": ["", "保留的预测"], "review_claim_types": ["fact", "prediction"],
    })
    assert review_claim_items(request)[0].claim_type == "prediction"


def test_review_preserves_the_full_api_supported_scope():
    texts = [f"声明{index}" for index in range(30)]
    request = AnalyzeRequest(raw_input="复核", request_context={
        "review_claim_texts": texts, "review_claim_types": ["fact"] * len(texts),
    })
    assert [item.claim for item in review_claim_items(request)] == texts


def test_synthesis_applies_review_scope_and_gap_annotation(monkeypatch):
    claim = "市立博物馆周三免费参观"
    evidence = _result("周三开放时间为9点至17点。")
    reasoner = LlmAgentReasoner(settings=replace(get_settings(), analysis_provider="kimi", llm_api_key="test",
                                                agent_synthesis_critic_enabled=False, evidence_rerank_enabled=False))
    payload = {"claims": [{"claim": text, "claim_type": "fact", "verdict": "supported", "confidence": "high",
                           "evidence_result_ids": ["e1"]} for text in (claim, "无关的声明")]}
    monkeypatch.setattr(reasoner, "_request_completion", lambda **kwargs: json.dumps(payload))
    monkeypatch.setattr(reasoner, "_enrich_synthesis", lambda **kwargs: {"timeline_nodes": [], "possibilities": [], "event": None})
    request = AnalyzeRequest(raw_input=f"{claim}，以及其他问题", request_context={"review_claim_texts": [claim]})
    synthesis = reasoner.synthesize(request=request, event=NormalizedEvent(summary=claim, raw_input=claim, input_type="text_news"),
                                    retrieval_bundle=RetrievalBundle(query=claim, canonical_results=(evidence,)))
    assert synthesis is not None
    assert len(synthesis.verdict.claim_results) == 1
    assert synthesis.verdict.claim_results[0].claim.rstrip("。") == claim
    assert synthesis.verdict.claim_results[0].verdict == "supported"
    assert synthesis.verdict.claim_results[0].evidence_gaps[0].dimension == "price"


def test_fast_pipeline_reviews_only_selected_claim_and_surfaces_failed_supplement(monkeypatch):
    from backend.app.models.schemas import MockFetchResult
    from backend.app.services.supplemental_evidence import SupplementalUrlExtractor

    claim = "市立博物馆周三免费参观"
    evidence = _result("周三开放时间为9点至17点。")
    pipeline = AnalyzePipeline()
    monkeypatch.setattr(pipeline.retriever, "retrieve_for_event", lambda *args, **kwargs: RetrievalBundle(query=claim, canonical_results=(evidence,)))
    monkeypatch.setattr(SupplementalUrlExtractor, "extract", lambda *args: MockFetchResult(status="error"))
    request = AnalyzeRequest(raw_input=f"{claim}。以及公司裁员40%。", input_type="text", request_context={
        "mode": "fast", "review_claim_texts": [claim], "supplemental_urls": ["https://example.org/article"],
    })
    report = pipeline.analyze(request)
    assert [result.claim for result in report.claim_results] == [claim]
    assert report.claim_results[0].evidence_gaps[0].dimension == "price"
    assert any("未能安全读取" in risk for risk in report.risks)
    assert any("本轮复核范围" in risk for risk in report.risks)


def test_llm_budget_is_reserved_before_transport(monkeypatch):
    from backend.app.services.run_control import RunControl, RunStopped, reset_run_control, set_run_control

    reasoner = LlmAgentReasoner(settings=replace(get_settings(), llm_max_tokens=100))
    monkeypatch.setattr(reasoner._client, "stream", lambda *args, **kwargs: pytest.fail("budget exhausted before HTTP"))
    token = set_run_control(RunControl(max_tokens=1))
    try:
        with pytest.raises(RunStopped) as stopped:
            reasoner._stream_completion(endpoint="https://example.org", model="fast", system_prompt="sys", user_prompt="usr")
        assert stopped.value.reason == "token_budget_exhausted"
    finally:
        reset_run_control(token)


def test_synthesis_gap_refinement_preserves_other_claims_and_stops_when_filled(monkeypatch):
    claim = "市立博物馆周三免费参观"
    evidence = _result("本馆9点开放。")
    bundle = RetrievalBundle(query=claim, canonical_results=(evidence,))
    missing = apply_evidence_goals([_claim(claim, evidence)], bundle)[0]
    preserved = _claim("其他声明", evidence, "refuted")
    verdict = VerdictEvaluation(claim_results=[missing, preserved], evidence=[evidence.to_evidence(relevance_reason="来源")],
                                evidence_grade="B", evidence_source="retrieval_live")
    enriched = replace(bundle, canonical_results=(replace(evidence, snippet="本馆周三免费开放。"),))
    searches = []

    def search(*args, **kwargs):
        searches.append(kwargs)
        return enriched

    monkeypatch.setattr("backend.app.services.per_claim_retriever.enrich_retrieval_for_claims", search)
    engine = SimpleNamespace(evaluate_with_source=lambda **kwargs: replace(verdict, claim_results=[_claim(claim, evidence)]))
    _bundle, final, iterations = refine_evidence_gaps(request=AnalyzeRequest(raw_input=claim), event=None,
                                                     verdict=verdict, bundle=bundle, retriever=None, verdict_engine=engine)
    assert iterations == len(searches) == 1
    assert final.claim_results[0].verdict == "supported"
    assert final.claim_results[1] == preserved


def test_gap_refinement_obeys_stop_condition(monkeypatch):
    evidence = _result("9点开放。")
    bundle = RetrievalBundle(query="museum", canonical_results=(evidence,))
    verdict = VerdictEvaluation(claim_results=apply_evidence_goals([_claim("市立博物馆免费参观", evidence)], bundle),
                                evidence=[], evidence_grade="B", evidence_source="retrieval_live")
    monkeypatch.setattr("backend.app.services.per_claim_retriever.enrich_retrieval_for_claims",
                        lambda *args, **kwargs: pytest.fail("must not query after budget stop"))
    _bundle, final, iterations = refine_evidence_gaps(request=None, event=None, verdict=verdict, bundle=bundle,
                                                     retriever=None, verdict_engine=None, should_stop=lambda: True)
    assert iterations == 0
    assert final.claim_results[0].evidence_gaps
