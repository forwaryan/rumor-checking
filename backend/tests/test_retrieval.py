from __future__ import annotations

import pytest

from backend.app.models.schemas import NormalizedEvent
from backend.app.services.mock_retriever import MockRetriever
from backend.app.services.timeline_builder import TimelineBuilder
from backend.tests.conftest import load_eval_fixture


RETRIEVAL_CASES = load_eval_fixture("retrieval_cases.json")


def _case_by_id(case_id: str):
    return next(item for item in RETRIEVAL_CASES if item["case_id"] == case_id)


def _event_for_case(case_id: str) -> NormalizedEvent:
    case = _case_by_id(case_id)
    input_type = "question_only" if case_id == "R03" else "text_news"
    return NormalizedEvent(
        summary=case["query"],
        keywords=[],
        input_type=input_type,
        raw_input=case["query"],
    )


def test_mock_retriever_normalizes_and_merges_results():
    case = _case_by_id("R01")
    bundle = MockRetriever().retrieve(case["query"])

    assert bundle.matched_case_id == "R01"
    assert bundle.related_result_count >= case["expected"]["min_related_results"]
    assert bundle.high_trust_result_count >= case["expected"]["min_high_trust_results"]

    canonical_ids = [item.result_id for item in bundle.canonical_results]
    assert "R01-2" in canonical_ids
    assert "R01-3" not in canonical_ids

    merged_report = next(item for item in bundle.canonical_results if item.result_id == "R01-2")
    assert merged_report.merged_result_ids == ("R01-3",)
    assert merged_report.merged_notes[0].startswith("R01-3:repost:")


@pytest.mark.parametrize("case_id", ["R01", "R02", "R03", "R04"])
def test_timeline_builder_uses_retrieval_candidates(case_id: str):
    case = _case_by_id(case_id)
    result_lookup = {item["result_id"]: item for item in case["mock_search_results"]}
    event = _event_for_case(case_id)
    retriever = MockRetriever()
    bundle = retriever.retrieve_for_event(event)
    timeline = TimelineBuilder().build(event, retrieval_bundle=bundle)

    assert timeline
    assert all(node.why_selected for node in timeline)

    expected_origin_id = case["expected"]["expected_origin_result_id"]
    if expected_origin_id is not None:
        origin_node = next(item for item in timeline if item.node_type == "origin")
        assert origin_node.url == result_lookup[expected_origin_id]["url"]

    expected_turn_id = case["expected"]["expected_turning_point_result_id"]
    if expected_turn_id is not None:
        expected_url = result_lookup[expected_turn_id]["url"]
        assert any(node.url == expected_url and node.node_type in {"turn", "clarification"} for node in timeline)
