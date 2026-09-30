"""Adversarial regressions for comparing measurements within their stated scope."""
from __future__ import annotations

import pytest

from backend.app.models.schemas import EvidenceItem
from backend.app.services.verdict_engine import VerdictEngine


def evidence(text: str, *, url: str = 'https://example.com/notice') -> EvidenceItem:
    return EvidenceItem(title='公告', snippet=text, source_name='公告来源',
                        source_tier='S', url=url, published_at='2026-09-30', relevance_reason='原文')


@pytest.mark.parametrize(('claim', 'text'), [
    ('星河公司招聘2000人', '星河公司招聘2000人，工资最高8000元。'),
    ('星河公司裁员50人', '星河公司共有500人，本轮裁员50人。'),
    ('星河公司招聘2000人', '星河公司招聘2000人，安排10个部门参加。'),
    ('星河公司招聘1万人', '星河公司招聘10000人。'),
    ('星河公司招聘2000人', '星河公司招聘2000人，工资更正为8000元。'),
    ('星河公司招聘2000人', '星河公司招聘2000人，工资并非8000元。'),
])
def test_incidental_or_equivalent_quantity_does_not_reverse_supported_claim(claim, text):
    verdict, _, _, _ = VerdictEngine()._evaluate_fact_claim(
        claim_text=claim, evidence_pool=[evidence(text)], subject_anchors=[])
    assert verdict == 'supported'


@pytest.mark.parametrize('text', [
    '星河公司招聘2000人，并非此前传闻数字。',
    '星河公司招聘6000人的传言不实，实际招聘2000人。',
    '星河公司招聘6000人的传言不实，实际2000人。',
    '星河公司实际招聘2000人，工资8000元。',
])
def test_scoped_correction_can_include_original_and_unrelated_quantities(text):
    result = VerdictEngine()._detect_quantitative_conflict(
        claim_text='星河公司招聘6000人', evidence_pool=[evidence(text)])
    assert result is not None and result[0] == 'refuted'


def test_conflicting_sources_keep_both_sides_in_selected_evidence():
    supported = evidence('星河公司招聘6000人。', url='https://example.com/a')
    repeated = evidence('星河公司招聘6000人。', url='https://example.com/b')
    conflicting = evidence('星河公司招聘2000人。', url='https://example.com/c')
    result = VerdictEngine()._detect_quantitative_conflict(
        claim_text='星河公司招聘6000人', evidence_pool=[supported, repeated, conflicting])
    assert result is not None and result[0] == 'conflicting'
    assert {item.url for item in result[3]} == {supported.url, conflicting.url}


@pytest.mark.parametrize(('claim', 'text'), [
    ('某市新增确诊50例', '某市累计确诊500例。'),
    ('星河公司招聘2000人', '星河公司裁员50人，并非此前传闻数字。'),
    ('星河公司裁员50人', '星河公司员工500人，工资更正为8000元。'),
])
def test_different_attribute_or_scope_does_not_create_quantity_conflict(claim, text):
    result = VerdictEngine()._detect_quantitative_conflict(
        claim_text=claim, evidence_pool=[evidence(text)])
    assert result is not None and result[0] == 'insufficient'


def test_unrelated_correction_inside_same_clause_does_not_make_difference_decisive():
    result = VerdictEngine()._detect_quantitative_conflict(
        claim_text='星河公司招聘6000人', evidence_pool=[evidence('星河公司招聘2000人且工资最高8000元。')])
    assert result is not None and result[0] == 'conflicting'


@pytest.mark.parametrize(('claim', 'text'), [
    ('星河公司招聘2000人', '星河公司招聘新员工2000名。'),
    ('星河公司营收1.5亿元', '星河公司营收150000000元。'),
])
def test_equivalent_measurements_with_role_nouns_and_scaled_decimals(claim, text):
    assert VerdictEngine()._detect_quantitative_conflict(
        claim_text=claim, evidence_pool=[evidence(text)]) is None


@pytest.mark.parametrize(('claim', 'text', 'expected'), [
    ('星河公司招聘2000人', '星河公司招聘2000人，晨光公司实际招聘500人。', 'supported'),
    ('星河公司北京招聘2000人', '星河公司北京招聘2000人，上海实际招聘500人。', 'supported'),
    ('星河公司2026年招聘2000人', '星河公司2026年招聘2000人，2025年实际招聘500人。', 'supported'),
    ('星河公司月薪10000元', '星河公司年薪实际120000元。', 'insufficient'),
    ('某市新增确诊50例', '某市实际确诊500例。', 'insufficient'),
    ('星河公司招聘2000人', '星河公司招聘规模最高3000人。', 'insufficient'),
    ('星河公司产品涨价10%', '星河公司产品折扣实际20%。', 'insufficient'),
    ('星河公司招聘2000人，晨光公司招聘500人', '星河公司招聘2000人，晨光公司招聘500人。', 'supported'),
    ('某市累计确诊600例', '某市新增50例累计确诊实际500例。', 'refuted'),
    ('某市地铁开通5条线', '某市地铁实际开通3条线。', 'refuted'),
    ('星河公司招聘2000人', '星河公司招聘6000人报道有误，更正为2000人。', 'supported'),
    ('星河公司招聘2000人', '星河公司招聘结束后目前员工实际2000人。', 'insufficient'),
    ('星河公司月薪2000元', '星河公司月薪实际3千元。', 'refuted'),
])
def test_quantity_relation_identity_and_uncertainty_guard(claim, text, expected):
    verdict, _, _, _ = VerdictEngine()._evaluate_fact_claim(
        claim_text=claim, evidence_pool=[evidence(text)], subject_anchors=[])
    assert verdict == expected


def test_adjacent_predicate_synonyms_preserve_same_scope_conflicting_sources():
    supported = evidence('今日新增确诊500例。', url='https://gov.example/b').model_copy(
        update={'title': '某市发布会通报新增确诊500例'})
    conflicting = evidence('今日新增确诊50例。', url='https://health.example/a').model_copy(
        update={'title': '某市卫健委：新增确诊50例'})
    verdict, confidence, _, selected = VerdictEngine()._evaluate_fact_claim(
        claim_text='某市新增确诊病例500例', evidence_pool=[supported, conflicting], subject_anchors=[])
    assert (verdict, confidence) == ('conflicting', 'medium')
    assert {item.url for item in selected} == {supported.url, conflicting.url}
