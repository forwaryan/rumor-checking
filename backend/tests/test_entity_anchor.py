from __future__ import annotations

from backend.app.services.entity_anchor import (
    candidate_matches_subject_anchors,
    extract_subject_anchors,
)


def test_action_prefix_capture_strips_trailing_frequency_adverb():
    """The non-greedy action-prefix capture swallows a frequency adverb sitting
    between subject and verb ('公司又回应' -> '公司又'). The trailing adverb must
    be stripped so the anchor is the bare entity."""
    anchors = extract_subject_anchors("公司又回应只暂停一条产线")
    assert "公司又" not in anchors


def test_entity_suffix_anchor_preserved():
    """A clean entity-suffix anchor must survive adverb stripping untouched."""
    anchors = extract_subject_anchors("晨星生物本周裁员40%")
    assert any("晨星生物" == anchor for anchor in anchors)


def test_trailing_adverb_strip_does_not_clip_legitimate_names():
    """Stripping trailing adverbs must not clip a name that legitimately ends in
    one of those characters when it is a real multi-char entity."""
    # "美的" ends in 的 (not an adverb); "格力" plain — neither should be touched.
    anchors = extract_subject_anchors("美的回应裁员传闻")
    assert any("美的" == anchor for anchor in anchors)


def test_subject_match_still_works_after_stripping():
    """After stripping the adverb, the cleaned anchor should still match source
    text that mentions the same entity (the whole point of the gate)."""
    anchors = extract_subject_anchors("公司又回应只暂停一条产线")
    # Whatever survives should match an article that names the entity.
    assert candidate_matches_subject_anchors(anchors, "公司回应称只暂停一条产线") or not anchors


def test_known_brand_recognized_far_from_action_verb():
    """A known brand must be found even when it sits far from the action verb and
    the messy input defeats the action-prefix pattern. Regression for the 京东
    layoff case: '京东在今年830 930 730的时间内开始裁员' used to yield only
    '730的时间内开始' and drop 京东, so a split '主要针对中层' sub-claim floated
    with no subject and the rule engine couldn't align it to 京东砍层级 hits."""
    anchors = extract_subject_anchors("京东在今年830 930 730的时间内开始裁员")
    assert "京东" in anchors


def test_known_brand_collision_not_anchored():
    """A brand that is only the prefix of a different compound noun is NOT the
    subject: 京东镇 (a village) / 京东白条 (a product) must not anchor 京东."""
    assert extract_subject_anchors("京东镇城中村改善人居环境") == []
    assert extract_subject_anchors("关于取消京东白条实施诈骗的预警") == []


def test_ambiguous_two_char_prefix_not_a_brand():
    """阿里山 must not false-anchor 阿里 — ambiguous 2-char prefixes are kept out
    of KNOWN_BRANDS on purpose."""
    assert "阿里" not in extract_subject_anchors("阿里山发生山体滑坡事故")


def test_brand_match_rejects_compound_collision():
    """The matcher applies the same boundary guard: a 京东 anchor matches a real
    京东 mention but not 京东镇/京东白条."""
    assert candidate_matches_subject_anchors(["京东"], "大厂集体向中层开刀:京东砍层级")
    assert candidate_matches_subject_anchors(["京东"], "迪庆州与京东集团举行座谈")
    assert not candidate_matches_subject_anchors(["京东"], "京东镇城中村改善人居环境")
    assert not candidate_matches_subject_anchors(["京东"], "取消京东白条实施诈骗预警")


def test_non_brand_anchor_keeps_substring_matching():
    """Non-brand anchors keep plain substring matching (the boundary guard is
    brand-only), so abbreviation/overlap behavior elsewhere is unchanged."""
    assert candidate_matches_subject_anchors(["晨星生物"], "晨星生物制药发布公告")
