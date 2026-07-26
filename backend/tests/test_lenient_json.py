from __future__ import annotations

from dataclasses import replace

from backend.app.core.config import get_settings
from backend.app.models.schemas import AnalyzeRequest, NormalizedEvent
from backend.app.services.agent_reasoner import LlmAgentReasoner
from backend.app.services.contract_utils import (
    loads_lenient_json,
    repair_structural_defects,
    repair_unescaped_inner_quotes,
)
from backend.app.services.retrieval_service import RetrievalService


def test_parses_clean_json_unchanged():
    assert loads_lenient_json('{"a": 1, "b": "x"}') == {"a": 1, "b": "x"}


def test_parses_fenced_json_block():
    text = '```json\n{"a": 1}\n```'
    assert loads_lenient_json(text) == {"a": 1}


def test_repairs_unescaped_inner_quotes_from_glm():
    # A real model failure: raw ASCII quotes around a Chinese phrase inside a
    # string value close the string early under strict json.loads.
    text = '{ "summary": "用户提问"某公司发布新品吗"，未指明。", "n": null }'
    parsed = loads_lenient_json(text)
    assert parsed is not None
    assert parsed["summary"] == '用户提问"某公司发布新品吗"，未指明。'
    assert parsed["n"] is None


def test_repairs_inner_quotes_inside_fenced_block():
    text = '```json\n{ "s": "他说"你好"然后走了。" }\n```'
    parsed = loads_lenient_json(text)
    assert parsed == {"s": '他说"你好"然后走了。'}


def test_keeps_already_escaped_quotes_intact():
    text = '{"s": "他说\\"你好\\"。"}'
    assert loads_lenient_json(text) == {"s": '他说"你好"。'}


def test_repairs_inner_quote_immediately_before_comma():
    # The hard case: an inner quote followed by a comma that is part of the prose,
    # not a JSON element separator. `"他叫"张三",今年30岁。"` must stay one string.
    text = '{"notes": "他叫"张三",今年30岁。", "x": 1}'
    parsed = loads_lenient_json(text)
    assert parsed is not None
    assert parsed["notes"] == '他叫"张三",今年30岁。'
    assert parsed["x"] == 1


def test_glm_phrases_mid_value_stay_in_string():
    # Real model shape: quoted phrases mid-sentence inside a value.
    text = '{"summary": "但"购买三栋楼"和"5000名研发人员"未证实。", "n": 2}'
    parsed = loads_lenient_json(text)
    assert parsed is not None
    assert parsed["summary"] == '但"购买三栋楼"和"5000名研发人员"未证实。'


def test_real_comma_separators_still_close_strings():
    # A genuine value-separating comma (followed by the next key or an array
    # element) must still close the string — the repair must not over-escape.
    assert loads_lenient_json('{"a": "foo", "b": "bar"}') == {"a": "foo", "b": "bar"}
    assert loads_lenient_json('{"ids": ["pw-1", "pw-7"]}') == {"ids": ["pw-1", "pw-7"]}
    assert loads_lenient_json('{"a": "x", "n": 5000}') == {"a": "x", "n": 5000}


def test_returns_none_on_non_object():
    assert loads_lenient_json("[1, 2, 3]") is None
    assert loads_lenient_json("not json at all") is None


def test_recovers_complete_elements_from_truncated_json():
    # The real synthesis failure: the stream is cut mid-third-claim at
    # `"truth_probability":`. The two fully-formed claims before the cut must be
    # recovered; the partial third is dropped.
    frag = (
        '{ "claims": [ '
        '{ "claim": "拼多多在雄安购买了5栋楼", "verdict": "insufficient" }, '
        '{ "claim": "拼多多在雄安招聘了6000名研发人员", "verdict": "insufficient" }, '
        '{ "claim": "拼多多在雄安有买楼和扩招的动作", "verdict": "supported", "truth_probability":'
    )
    parsed = loads_lenient_json(frag)
    assert parsed is not None, "truncated fragment with complete claims was not recovered"
    claims = parsed["claims"]
    assert [c["claim"] for c in claims] == [
        "拼多多在雄安购买了5栋楼",
        "拼多多在雄安招聘了6000名研发人员",
    ]


def test_recovers_nested_object_before_truncation():
    # A complete nested object (event) plus one complete array element survive; the
    # dangling final element is discarded.
    frag = '{"event":{"title":"x"},"claims":[{"claim":"a"},{"claim":"b'
    parsed = loads_lenient_json(frag)
    assert parsed == {"event": {"title": "x"}, "claims": [{"claim": "a"}]}


def test_truncation_recovery_needs_a_complete_element():
    # A cut before ANY nested element closes has nothing to salvage.
    assert loads_lenient_json('{"summary": "拼') is None
    assert loads_lenient_json('{"claims": [{"claim": "半') is None


def test_recovery_does_not_alter_wellformed_json():
    # The recovery path is a last resort; well-formed input still parses verbatim
    # via the earlier candidates, untouched by the salvage logic.
    assert loads_lenient_json('{"a": 1, "b": [1, 2], "c": {"d": 3}}') == {
        "a": 1,
        "b": [1, 2],
        "c": {"d": 3},
    }


def test_repair_is_noop_on_valid_string():
    valid = '{"s": "no inner quotes here"}'
    assert repair_unescaped_inner_quotes(valid) == valid


def test_drops_trailing_commas():
    assert loads_lenient_json('{"a": 1, "b": 2,}') == {"a": 1, "b": 2}
    assert loads_lenient_json('{"ids": ["x", "y",]}') == {"ids": ["x", "y"]}


def test_escapes_literal_control_chars_inside_strings():
    assert loads_lenient_json('{"note": "第一行\n第二行"}') == {"note": "第一行\n第二行"}
    assert loads_lenient_json('{"note": "col1\tcol2"}') == {"note": "col1\tcol2"}


def test_fullwidth_comma_separator_normalized_but_prose_kept():
    # A fullwidth comma used as a pair separator (outside a string) is fixed;
    # a fullwidth comma inside a Chinese string value is normal text, untouched.
    assert loads_lenient_json('{"a": 1，"b": 2}') == {"a": 1, "b": 2}
    assert loads_lenient_json('{"s": "你好，世界"}') == {"s": "你好，世界"}


def test_combined_inner_quote_and_trailing_comma():
    # Both defects at once: unescaped inner quotes AND a trailing comma.
    parsed = loads_lenient_json('{"s": "他说"你好",今天很好。",}')
    assert parsed == {"s": '他说"你好",今天很好。'}


def test_structural_repair_noop_on_clean_json():
    valid = '{"a": 1, "b": "文本，含全角逗号"}'
    assert repair_structural_defects(valid) == valid


def test_synthesis_recovers_from_glm_malformed_json(monkeypatch):
    # End-to-end guard for the real model failure: the model returns a fenced JSON
    # block whose string values contain unescaped inner quotes AND a phrase quote
    # immediately before a prose comma. Before the repair this fell back to rules
    # (claim_source becomes not "provider"); now synthesis must parse it and adopt
    # the LLM's grounded claims.
    event = NormalizedEvent(
        summary="海州新鲜屋部分酸奶批次超过保质期",
        input_type="text_news",
        raw_input="海州新鲜屋部分酸奶批次超过保质期，涉事门店已停业整改。",
        title="海州新鲜屋酸奶抽检",
    )
    bundle = RetrievalService().retrieve_for_event(event, request_context={})
    cite_id = bundle.canonical_results[0].result_id  # a real id so evidence attaches

    raw = (
        "```json\n"
        "{\n"
        '  "event": { "title": "海州酸奶抽检", '
        '"summary": "报道称\"部分批次\"超期，涉事门店已整改，但\"全部下架\"未证实。", '
        '"anchor_result_id": "%s" },\n'
        '  "claims": [\n'
        '    { "claim": "海州新鲜屋部分酸奶批次超过保质期。", "claim_type": "fact", '
        '"verdict": "supported", "confidence": "high", "truth_probability": 82, '
        '"probability_basis": "evidence", "evidence_result_ids": ["%s"], '
        '"notes": "监管通报\"抽检不合格\",随后门店停业。" }\n'
        "  ],\n"
        '  "scenarios": [], "timeline": []\n'
        "}\n"
        "```"
    ) % (cite_id, cite_id)

    reasoner = LlmAgentReasoner(
        settings=replace(get_settings(), analysis_provider="kimi", llm_api_key="test-key")
    )
    monkeypatch.setattr(reasoner, "_request_completion", lambda **kwargs: raw)

    result = reasoner.synthesize(
        request=AnalyzeRequest(raw_input=event.raw_input, input_type="text"),
        event=event,
        retrieval_bundle=bundle,
    )
    assert result is not None, "synthesis fell back instead of parsing the GLM JSON"
    assert result.claim_extraction.source == "provider"
    claim = result.verdict.claim_results[0]
    assert claim.verdict == "supported"
    assert claim.evidence, "grounded claim lost its cited evidence"
