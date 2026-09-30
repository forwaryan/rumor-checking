from dataclasses import replace

import pytest

from backend.app.models.schemas import AnalyzeRequest, ClaimItem, ClaimResult, NormalizedEvent
from backend.app.services.evidence_goals import apply_evidence_goals
from backend.app.services.retrieval_models import RetrievalBundle, SearchResult
from backend.app.services.verdict_engine import VerdictEngine


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
])
@pytest.mark.parametrize("verdict", ["supported", "refuted", "conflicting"])
def test_missing_property_only_downgrades(claim, title, snippet, dimension, verdict):
    evidence = _result(snippet, title)
    original = _claim(claim, evidence, verdict)
    checked = apply_evidence_goals([original], RetrievalBundle(query=claim, canonical_results=(evidence,)))[0]
    assert checked.verdict == "insufficient"
    assert checked.confidence == "low"
    assert checked.truth_probability is None
    assert checked.evidence == original.evidence
    assert checked.evidence_gaps[0].dimension == dimension
    assert checked.evidence_gaps[0].suggested_queries
    ClaimResult.model_validate(checked.model_dump())


@pytest.mark.parametrize("claim,title,snippet", [
    ("市立博物馆周三免费参观", "市立博物馆参观公告", "本馆周三免费开放，需提前预约。"),
    ("市立博物馆门票50元", "市立博物馆参观公告", "成人门票为50元，儿童免票。"),
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
    assert checked.verdict == "insufficient"
    assert [gap.dimension for gap in checked.evidence_gaps] == ["price"]


def test_unrecognized_domain_keeps_existing_judgment():
    evidence = _result("这款软件无需付费即可使用。", "产品说明")
    checked = apply_evidence_goals([_claim("这款软件免费", evidence)],
                                   RetrievalBundle(query="软件", canonical_results=(evidence,)))[0]
    assert checked.verdict == "supported"
    assert not checked.evidence_gaps


def test_uncited_property_cannot_fill_cited_evidence_gap():
    evidence = _result("周三9点开放。")
    other = replace(_result("周三免费开放。"), result_id="e2", url="https://other.example.org")
    checked = apply_evidence_goals([_claim("市立博物馆周三免费参观", evidence)],
                                   RetrievalBundle(query="museum", canonical_results=(evidence, other)))[0]
    assert checked.verdict == "insufficient"


def test_raw_body_can_cover_property():
    evidence = _result("周三9点开放。")
    checked = apply_evidence_goals([_claim("市立博物馆周三免费参观", evidence)],
                                   RetrievalBundle(query="museum", canonical_results=(evidence,)),
                                   {"e1": "周三免费开放。"})[0]
    assert checked.verdict == "supported"


def test_fetched_body_retains_substantive_sentence_matching_title():
    claim = "明泉市博物馆周三免费开放"
    evidence = _result(claim, claim)
    bundle = RetrievalBundle(query=claim, canonical_results=(evidence,))
    checked = apply_evidence_goals([_claim(claim, evidence)], bundle, {"e1": f"{claim}。"})[0]
    assert checked.verdict == "supported"
    assert not checked.evidence_gaps
    without_body = apply_evidence_goals([_claim(claim, evidence)], bundle)[0]
    assert without_body.verdict == "insufficient"


def test_explicit_mock_evidence_is_checked_against_its_own_raw_content():
    evidence = _result("周三免费开放。")
    original = _claim("市立博物馆周三免费参观", evidence)
    checked = apply_evidence_goals([original], None, raw_evidence=original.evidence)[0]
    assert checked.verdict == "supported"
    assert not checked.evidence_gaps


def test_rule_and_llm_verdicts_share_guard(monkeypatch):
    claim = "市立博物馆周三免费参观"
    evidence = _result("周三开放时间为9点至17点。")
    monkeypatch.setattr("backend.app.services.verdict_engine.llm_judge_claims", lambda *args, **kwargs: [_claim(claim, evidence)])
    verdict = VerdictEngine().evaluate_with_source(
        request=AnalyzeRequest(raw_input=claim), event=NormalizedEvent(summary=claim, raw_input=claim, input_type="text_news"),
        claims=[ClaimItem(claim=claim, claim_type="fact")],
        retrieval_bundle=RetrievalBundle(query=claim, canonical_results=(evidence,)),
    )
    assert verdict.claim_results[0].verdict == "insufficient"
