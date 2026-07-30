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
