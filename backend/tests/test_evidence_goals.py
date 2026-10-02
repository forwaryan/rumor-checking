import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from backend.app.core.config import get_settings
from backend.app.models.schemas import AnalyzeRequest, ClaimItem, ClaimResult, NormalizedEvent
from backend.app.services.agent_reasoner import LlmAgentReasoner
from backend.app.services.analyze_pipeline import AnalyzePipeline
from backend.app.services.evidence_goals import apply_evidence_goals
from backend.app.services.per_claim_retriever import enrich_retrieval_for_claims, refine_evidence_gaps
from backend.app.services.retrieval_models import RetrievalBundle, SearchResult
from backend.app.services.review_scope import restrict_review_results, review_claim_items, select_review_claims
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


def test_review_scope_consumes_duplicate_claim_results_once():
    evidence = _result("正文")
    request = AnalyzeRequest(raw_input="旧报告", request_context={
        "review_claim_texts": ["同一声明", "同一声明"], "review_claim_types": ["fact", "fact"],
    })
    one_result = _claim("同一声明。", evidence, "supported")
    selected = restrict_review_results([one_result], request)
    assert [result.verdict for result in selected] == ["supported", "insufficient"]
    assert not selected[1].evidence

    another_result = _claim("同一声明", evidence, "refuted")
    selected = restrict_review_results([one_result, another_result], request)
    assert [result.verdict for result in selected] == ["supported", "refuted"]


@pytest.mark.parametrize("wrong_type", ["opinion", "prediction", "unverifiable"])
def test_review_fact_cannot_promote_model_nonfact_verdict(wrong_type):
    evidence = _result("正文")
    request = AnalyzeRequest(raw_input="旧报告", request_context={
        "review_claim_texts": ["待核事实"], "review_claim_types": ["fact"],
    })
    misclassified = _claim("待核事实", evidence).model_copy(update={"claim_type": wrong_type})
    selected = restrict_review_results([misclassified], request)[0]
    assert selected.claim_type == "fact"
    assert selected.verdict == "insufficient"
    assert selected.confidence == "low"
    assert selected.truth_probability is None
    assert not selected.evidence


def test_review_matches_same_type_before_misclassified_duplicate():
    evidence = _result("正文")
    request = AnalyzeRequest(raw_input="旧报告", request_context={
        "review_claim_texts": ["待核事实"], "review_claim_types": ["fact"],
    })
    wrong = _claim("待核事实", evidence).model_copy(update={"claim_type": "prediction"})
    correct = _claim("待核事实。", evidence, "refuted")
    selected = restrict_review_results([wrong, correct], request)
    assert selected[0].verdict == "refuted"
    assert selected[0].claim_type == "fact"


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


def test_verdict_engine_respects_explicit_review_subset(monkeypatch):
    request = AnalyzeRequest(raw_input="复核", request_context={
        "review_claim_texts": ["声明一", "声明二"], "review_claim_types": ["fact", "fact"],
    })
    subset = [ClaimItem(claim="声明二", claim_type="fact")]
    assert select_review_claims(request, [ClaimItem(claim="旧抽取", claim_type="fact")]) == review_claim_items(request)
    monkeypatch.setattr("backend.app.services.verdict_engine.llm_judge_claims", lambda results, **kwargs: results)
    evaluation = VerdictEngine().evaluate_with_source(
        request=request, event=NormalizedEvent(summary="复核", raw_input="复核", input_type="text_news"),
        claims=subset, retrieval_bundle=RetrievalBundle(query="复核"),
    )
    assert [result.claim for result in evaluation.claim_results] == ["声明二"]


@pytest.mark.parametrize("claims", [
    [ClaimItem(claim="范围外声明", claim_type="fact")],
    [ClaimItem(claim="声明一", claim_type="prediction")],
    [ClaimItem(claim="声明一", claim_type="fact"), ClaimItem(claim="声明一", claim_type="fact")],
])
def test_verdict_engine_rejects_out_of_review_scope_claims(claims):
    request = AnalyzeRequest(raw_input="复核", request_context={
        "review_claim_texts": ["声明一"], "review_claim_types": ["fact"],
    })
    with pytest.raises(ValueError, match="selected review scope"):
        VerdictEngine().evaluate_with_source(
            request=request, event=NormalizedEvent(summary="复核", raw_input="复核", input_type="text_news"),
            claims=claims,
        )


def test_large_review_judges_all_claims_without_per_claim_llm_budget(monkeypatch):
    from backend.app.services.run_control import RunControl, reset_run_control, set_run_control

    text = "市立博物馆2024年成立"
    evidence = _result("市立博物馆2024年成立。")
    claims = [ClaimItem(claim=f"{text}：编号{index}", claim_type="fact") for index in range(31)]
    request = AnalyzeRequest(raw_input="复核", request_context={
        "review_claim_texts": [item.claim for item in claims], "review_claim_types": ["fact"] * len(claims),
    })
    monkeypatch.setattr("backend.app.services.verdict_engine.fetch_page_snippets", lambda *args: {})
    monkeypatch.setattr("backend.app.services.verdict_engine.llm_judge_claims", lambda results, **kwargs: (
        pytest.fail("must not call the per-claim LLM in a large review") if not kwargs.get("skip_llm") else results
    ))
    monkeypatch.setattr("backend.app.services.verdict_engine.annotate_claim_corrections",
                        lambda *args, **kwargs: pytest.fail("large review must skip optional correction LLM"))
    control = RunControl(max_llm_calls=1)
    token = set_run_control(control)
    try:
        evaluated = VerdictEngine().evaluate_with_source(
            request=request, event=NormalizedEvent(summary="复核", raw_input="复核", input_type="text_news"),
            claims=claims, retrieval_bundle=RetrievalBundle(query="复核", canonical_results=(evidence,)),
        )
    finally:
        reset_run_control(token)
    assert len(evaluated.claim_results) == len(claims)
    assert control.llm_calls == 0


def test_synthesis_does_not_silently_truncate_large_review_scope(monkeypatch):
    texts = [f"待复核声明{index}" for index in range(7)]
    request = AnalyzeRequest(raw_input="旧报告", request_context={
        "review_claim_texts": texts, "review_claim_types": ["fact"] * len(texts),
    })
    evidence = _result("公告正文")
    reasoner = LlmAgentReasoner(settings=replace(get_settings(), analysis_provider="kimi", llm_api_key="test",
                                                evidence_rerank_enabled=False))
    monkeypatch.setattr(reasoner, "_request_completion", lambda **kwargs: pytest.fail("不能只核查前六条"))
    assert reasoner.synthesize(
        request=request, event=NormalizedEvent(summary="旧报告", raw_input="旧报告", input_type="text_news"),
        retrieval_bundle=RetrievalBundle(query="旧报告", canonical_results=(evidence,)),
    ) is None


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


@pytest.mark.parametrize("starting_verdict", ["supported", "refuted", "conflicting"])
def test_decisive_verdict_with_gap_triggers_targeted_retrieval_and_subset_rejudge(starting_verdict):
    claim = "市立博物馆周三免费参观"
    other = "其他声明"
    evidence = _result("本馆周三9点开放。")
    bundle = RetrievalBundle(query=claim, canonical_results=(evidence,))
    missing = apply_evidence_goals([_claim(claim, evidence, starting_verdict)], bundle)[0]
    preserved = _claim(other, evidence, "refuted")
    verdict = VerdictEvaluation(claim_results=[missing, preserved], evidence=[],
                                evidence_grade="B", evidence_source="retrieval_live")
    request = AnalyzeRequest(raw_input=claim, request_context={
        "review_claim_texts": [claim, other], "review_claim_types": ["fact", "fact"],
    })
    queries = []
    judged = []

    def retrieve(event, request_context):
        queries.append(request_context["force_retrieval_query"])
        return RetrievalBundle(query=claim, canonical_results=(
            replace(evidence, result_id="e2", url="https://other.example.org", snippet="本馆周三免费开放。"),
        ))

    def evaluate_with_source(**kwargs):
        judged.extend(kwargs["claims"])
        assert [item.claim for item in kwargs["claims"]] == [claim]
        return replace(verdict, claim_results=[_claim(claim, evidence, starting_verdict)])

    enriched, final, iterations = refine_evidence_gaps(
        request=request, event=None, verdict=verdict, bundle=bundle,
        retriever=SimpleNamespace(retrieve_for_event=retrieve),
        verdict_engine=SimpleNamespace(evaluate_with_source=evaluate_with_source),
    )
    assert iterations == len(queries) == 1
    assert "票价" in queries[0]
    assert [item.claim for item in judged] == [claim]
    assert final.claim_results[0].verdict == starting_verdict
    assert final.claim_results[1] == preserved
    assert len(enriched.canonical_results) == 2


def test_empty_first_batch_does_not_starve_unsearched_claims():
    texts = [f"待核事实{index}未确认" for index in range(4)]
    verdict = VerdictEvaluation(claim_results=[
        ClaimResult(claim=text, claim_type="fact", verdict="insufficient", confidence="low", notes="")
        for text in texts
    ], evidence=[], evidence_grade="D", evidence_source="retrieval_live")
    bundle = RetrievalBundle(query="多条事实", canonical_results=(_result("背景信息"),))
    queries = []

    def retrieve(event, request_context):
        query = request_context["force_retrieval_query"]
        queries.append(query)
        if texts[3] in query:
            return RetrievalBundle(query=query, canonical_results=(
                replace(_result("直接证据"), result_id="new", url="https://example.org/new"),
            ))
        return RetrievalBundle(query=query, canonical_results=())

    _bundle, _verdict, iterations = refine_evidence_gaps(
        request=AnalyzeRequest(raw_input="多条事实"), event=None, verdict=verdict, bundle=bundle,
        retriever=SimpleNamespace(retrieve_for_event=retrieve),
        verdict_engine=SimpleNamespace(evaluate_with_source=lambda **kwargs: replace(
            verdict, claim_results=[claim.model_copy(update={"verdict": "supported"})
                                    for claim in verdict.claim_results])),
    )
    assert iterations == 2
    assert len(queries) == 6
    assert all(texts[3] not in query for query in queries[:3])
    assert any(texts[3] in query for query in queries[3:])


def test_gapless_insufficient_synthesis_gets_focused_retrieval():
    claim = "没有预定义缺口的声明"
    source = _result("尚无直接证据", title="核查背景")
    bundle = RetrievalBundle(query=claim, canonical_results=(source,))
    unresolved = _claim(claim, source, "insufficient")
    original = VerdictEvaluation(claim_results=[unresolved], evidence=[], evidence_grade="D",
                                 evidence_source="retrieval_live")
    queries = []

    def retrieve(event, request_context):
        queries.append(request_context["force_retrieval_query"])
        return RetrievalBundle(query=claim, canonical_results=(
            replace(source, result_id="resolved", url="https://resolved.example.org", snippet="直接证据"),
        ))

    resolved = _claim(claim, source, "supported")
    _bundle, final, iterations = refine_evidence_gaps(
        request=AnalyzeRequest(raw_input=claim), event=None, verdict=original, bundle=bundle,
        retriever=SimpleNamespace(retrieve_for_event=retrieve),
        verdict_engine=SimpleNamespace(evaluate_with_source=lambda **kwargs: replace(
            original, claim_results=[resolved])),
    )
    assert iterations == len(queries) == 1
    assert final.claim_results[0].verdict == "supported"


def test_subset_rejudge_retains_unaffected_claim_evidence_pool():
    claim = "市立博物馆周三免费参观"
    source = _result("本馆9点开放。")
    other = replace(source, result_id="other", url="https://other.example.org", snippet="另一声明证据")
    original_bundle = RetrievalBundle(query=claim, canonical_results=(source, other))
    missing = apply_evidence_goals([_claim(claim, source)], original_bundle)[0]
    preserved = _claim("其他声明", other, "refuted")
    original = VerdictEvaluation(claim_results=[missing, preserved], evidence=[
        source.to_evidence(relevance_reason="旧来源"), other.to_evidence(relevance_reason="旧来源")],
        evidence_grade="A", evidence_source="retrieval_live")
    refined_source = replace(source, result_id="refined", url="https://refined.example.org", snippet="本馆周三免费开放。")
    incoming = RetrievalBundle(query=claim, canonical_results=(refined_source,))
    judged = replace(original, claim_results=[_claim(claim, refined_source)],
                     evidence=[refined_source.to_evidence(relevance_reason="新来源")], evidence_grade="C")
    _bundle, final, iterations = refine_evidence_gaps(
        request=AnalyzeRequest(raw_input=claim), event=None, verdict=original, bundle=original_bundle,
        retriever=SimpleNamespace(retrieve_for_event=lambda *args, **kwargs: incoming),
        verdict_engine=SimpleNamespace(evaluate_with_source=lambda **kwargs: judged),
    )
    assert iterations == 1
    assert final.claim_results[1] == preserved
    assert {item.url for item in final.evidence} >= {other.url, refined_source.url}
    assert final.evidence_grade == "A"


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


def test_subset_rejudge_keeps_probability_when_judgment_and_citations_are_unchanged():
    claim = "市立博物馆周三免费参观"
    evidence = _result("本馆周三9点开放。")
    original_bundle = RetrievalBundle(query=claim, canonical_results=(evidence,))
    prior = apply_evidence_goals([_claim(claim, evidence)], original_bundle)[0].model_copy(update={
        "truth_probability": 97, "probability_basis": "evidence",
    })
    verdict = VerdictEvaluation(claim_results=[prior], evidence=[], evidence_grade="B", evidence_source="retrieval_live")
    added = replace(evidence, result_id="new", url="https://additional.example.org", snippet="背景材料")
    judged_claim = prior.model_copy(update={"truth_probability": None, "probability_basis": None})
    _bundle, refined, iterations = refine_evidence_gaps(
        request=AnalyzeRequest(raw_input=claim), event=None, verdict=verdict, bundle=original_bundle,
        retriever=SimpleNamespace(retrieve_for_event=lambda *args, **kwargs: RetrievalBundle(
            query=claim, canonical_results=(added,))),
        verdict_engine=SimpleNamespace(evaluate_with_source=lambda **kwargs: replace(
            verdict, claim_results=[judged_claim])),
        max_iterations=1,
    )
    assert iterations == 1
    assert refined.claim_results[0].truth_probability == 97
    assert refined.claim_results[0].probability_basis == "evidence"


def test_subset_rejudge_clears_probability_when_verdict_changes():
    claim = "市立博物馆周三免费参观"
    evidence = _result("本馆周三9点开放。")
    original_bundle = RetrievalBundle(query=claim, canonical_results=(evidence,))
    prior = apply_evidence_goals([_claim(claim, evidence)], original_bundle)[0].model_copy(update={
        "truth_probability": 97, "probability_basis": "evidence",
    })
    verdict = VerdictEvaluation(claim_results=[prior], evidence=[], evidence_grade="B", evidence_source="retrieval_live")
    added = replace(evidence, result_id="new", url="https://additional.example.org", snippet="明确收费")
    judged_claim = prior.model_copy(update={"verdict": "refuted", "truth_probability": None, "probability_basis": None})
    _bundle, refined, iterations = refine_evidence_gaps(
        request=AnalyzeRequest(raw_input=claim), event=None, verdict=verdict, bundle=original_bundle,
        retriever=SimpleNamespace(retrieve_for_event=lambda *args, **kwargs: RetrievalBundle(
            query=claim, canonical_results=(added,))),
        verdict_engine=SimpleNamespace(evaluate_with_source=lambda **kwargs: replace(
            verdict, claim_results=[judged_claim])),
        max_iterations=1,
    )
    assert iterations == 1
    assert refined.claim_results[0].truth_probability is None
    assert refined.claim_results[0].probability_basis is None


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
