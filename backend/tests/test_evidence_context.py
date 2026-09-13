from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace

import httpx
import pytest

from backend.app.agent.context_window import estimate_tokens
from backend.app.core.config import get_settings
from backend.app.models.schemas import AnalyzeRequest, NormalizedEvent
from backend.app.services.agent_reasoner import CLAIMS_ONLY_SYSTEM_PROMPT, LlmAgentReasoner
from backend.app.services.evidence_context import ContextBudgetExceeded, build_evidence_prompt
from backend.app.services.retrieval_models import RetrievalBundle, SearchResult


def _hits(count=12):
    return [
        {
            "result_id": f"result-{index}", "title": f"测试政策 {index}",
            "url": f"https://source{index}.example/article", "source_name": f"来源{index}",
            "published_at": "2026-09-13", "source_tier": "A", "snippet": "当前政策待查。" * 250,
        }
        for index in range(count)
    ]


def _build(**overrides):
    arguments = {
        "context": {"raw_input": "这个政策是真的吗？"}, "hits": _hits(), "fetched_bodies": {},
        "query": "这个政策是真的吗？", "system_prompt": "system policy", "context_limit": 32000,
        "output_reserve": 4096, "playbooks": [],
    }
    arguments.update(overrides)
    return build_evidence_prompt(**arguments)


def _payload(prompt):
    return json.loads(prompt.split("<untrusted-input>\n", 1)[1].rsplit("\n</untrusted-input>", 1)[0])


@pytest.mark.parametrize("text", ["x" * 30000, "政策" * 15000, "!@#$%👩🚀" * 4000])
def test_long_content_is_budgeted_without_mutating_originals(text):
    hits = _hits()
    for hit in hits:
        hit["snippet"] = text
    bodies = {hit["result_id"]: text for hit in hits}
    before = copy.deepcopy((hits, bodies))
    prompt = _build(hits=hits, fetched_bodies=bodies, context_limit=8500)
    assert estimate_tokens("system policy") + estimate_tokens(prompt) + 16 + 4096 <= 8500
    assert (hits, bodies) == before
    assert len(_payload(prompt)["retrieval_hits"]) == 12
    counts = prompt.context_counts
    assert counts["total_estimated"] == sum(counts[key] for key in (
        "system", "user_overhead", "evidence_index", "evidence_summaries",
        "evidence_passages", "playbooks", "output_reserve",
    ))


def test_late_counterevidence_is_verbatim_and_matches_existing_source():
    hits = _hits(1)
    body = "一般网站导航 " * 1700 + "官方澄清：该政策说法不实，文件并未发布。" + " 网站页脚" * 30
    snippet = "一般描述。" * 600 + "该政策并非真实政策，官方否认。"
    hits[0]["snippet"] = snippet
    prompt = _build(hits=hits, fetched_bodies={"result-0": body, "unknown": "绝不能引用的秘密正文"})
    payload = _payload(prompt)
    assert "绝不能引用" not in prompt
    assert any("该政策说法不实" in passage["full_text"] for passage in payload["fetched_full_text"])
    assert any("官方否认" in summary["snippet"] for summary in payload["evidence_summaries"])
    for passage in payload["fetched_full_text"]:
        assert passage["result_id"] == "result-0"
        assert passage["full_text"] == body[passage["start"]:passage["end"]]
    index = payload["retrieval_hits"][0]
    assert {key: index[key] for key in ("result_id", "url", "source_name", "published_at")} == {
        key: hits[0][key] for key in ("result_id", "url", "source_name", "published_at")
    }


def test_index_covers_evidence_beyond_old_top_eight():
    payload = _payload(_build())
    assert {hit["result_id"] for hit in payload["retrieval_hits"]} == {hit["result_id"] for hit in _hits()}
    assert all("snippet" not in hit for hit in payload["retrieval_hits"])


def test_tight_budget_keeps_late_counterevidence_from_low_ranked_source():
    bodies = {hit["result_id"]: "一般政策报道。" * 600 for hit in _hits()}
    bodies["result-11"] += "官方辟谣：该政策不实，否认已经发布。" * 10
    prompt = _build(fetched_bodies=bodies, context_limit=8500)
    assert any(
        passage["result_id"] == "result-11" and "官方辟谣" in passage["full_text"]
        for passage in _payload(prompt)["fetched_full_text"]
    )


def test_exact_fixed_prompt_boundary_and_oversized_original_input():
    empty = _build(hits=[])
    required = empty.context_counts["total_estimated"]
    assert _build(hits=[], context_limit=required).context_counts["total_estimated"] == required
    with pytest.raises(ContextBudgetExceeded):
        _build(hits=[], context_limit=required - 1)
    with pytest.raises(ContextBudgetExceeded):
        _build(context={"raw_input": "原始问题必须保留" * 20000})


def test_oversized_metadata_is_omitted_without_forced_minimum_or_orphan_body():
    hits = _hits(1)
    hits[0]["url"] += "x" * 100000
    prompt = _build(hits=hits, fetched_bodies={"result-0": "不可成为孤立正文"})
    assert _payload(prompt)["retrieval_hits"] == []
    assert _payload(prompt)["fetched_full_text"] == []
    assert prompt.context_counts["evidence_omitted"] == 1


def test_playbooks_are_counted_as_non_evidence_and_omitted_whole_when_too_big():
    book = {"id": "policy", "title": "政策核查", "instructions": ["找到文件文号"],
            "source_url": "repo://policy", "reviewed_at": "2026-09-13"}
    prompt = _build(playbooks=[book])
    assert _payload(prompt)["checking_playbooks"] == [book]
    assert prompt.context_counts["playbooks"] > 0
    assert "NOT evidence" in prompt
    book["instructions"] = ["方法" * 100000]
    assert _payload(_build(playbooks=[book]))["checking_playbooks"] == []


def test_parallel_prompt_counts_are_isolated_and_read_only():
    with ThreadPoolExecutor(max_workers=2) as pool:
        prompts = list(pool.map(lambda count: _build(hits=_hits(count)), [1, 12]))
    assert [prompt.context_counts["evidence_selected"] for prompt in prompts] == [1, 12]
    with pytest.raises(TypeError):
        prompts[0].context_counts["system"] = 0


def _reasoner(**overrides):
    return LlmAgentReasoner(settings=replace(
        get_settings(), analysis_provider="kimi", llm_api_key="test-key",
        llm_model="fast-x", llm_search_model="", llm_synthesis_model="",
        **overrides,
    ))


def _inputs():
    request = AnalyzeRequest(raw_input="政策私人问题")
    event = NormalizedEvent(raw_input=request.raw_input, input_type="text_news", summary="私人摘要")
    bundle = RetrievalBundle(query=request.raw_input, canonical_results=tuple(
        SearchResult.from_dict(hit) for hit in _hits()
    ))
    return request, event, bundle


def test_reasoner_diagnostics_are_counts_only_and_synthesis_uses_complete_budget(monkeypatch):
    reasoner = _reasoner(agent_context_max_tokens=8500)
    monkeypatch.setattr(reasoner, "_checking_playbooks", lambda text: [])
    logs = []
    monkeypatch.setattr("backend.app.services.agent_reasoner.emit_log", lambda **entry: logs.append(entry))
    request, event, bundle = _inputs()
    prompt = reasoner._build_synthesis_prompt(request=request, event=event, retrieval_bundle=bundle)
    assert isinstance(prompt, str)
    assert reasoner._prompt_fits(CLAIMS_ONLY_SYSTEM_PROMPT, prompt, reasoner._synthesis_model())
    serialized = json.dumps(logs, ensure_ascii=False)
    assert "heuristic" in serialized
    for secret in ("私人", "source0.example", "来源0", "当前政策待查"):
        assert secret not in serialized
    assert "total_estimated=" in serialized


def test_overbudget_synthesis_falls_back_without_calling_model(monkeypatch):
    reasoner = _reasoner(agent_context_max_tokens=100)
    monkeypatch.setattr(reasoner, "_checking_playbooks", lambda text: [])
    monkeypatch.setattr(reasoner, "_request_completion", lambda **kwargs: pytest.fail("must not send oversized prompt"))
    request, event, bundle = _inputs()
    assert reasoner.synthesize(request=request, event=event, retrieval_bundle=bundle) is None


def test_retry_model_is_budget_checked_again(monkeypatch):
    reasoner = _reasoner(llm_reasoning_models=("reasoning-x",), llm_reasoning_retries=1)
    monkeypatch.setattr(reasoner, "_candidate_models", lambda primary: ["reasoning-x", "fast-x"])
    calls = []
    monkeypatch.setattr(reasoner, "_stream_completion", lambda **kwargs: calls.append(kwargs["model"]) or "")
    prompt = "证" * 21000
    reasoner._request_completion(stage_key="agent_synthesis", title="test", system_prompt="sys", user_prompt=prompt)
    assert calls == ["reasoning-x"]


def test_disabling_diagnostics_suppresses_context_logs(monkeypatch):
    reasoner = _reasoner(agent_context_diagnostics_enabled=False)
    monkeypatch.setattr(reasoner, "_checking_playbooks", lambda text: [])
    logs = []
    monkeypatch.setattr("backend.app.services.agent_reasoner.emit_log", lambda **entry: logs.append(entry))
    request, event, bundle = _inputs()
    reasoner._build_synthesis_prompt(request=request, event=event, retrieval_bundle=bundle)
    assert logs == []


def test_stream_ledger_receives_request_local_counts_without_leaking_to_next_call(monkeypatch):
    reasoner = _reasoner()
    records = []
    monkeypatch.setattr("backend.app.services.agent_reasoner.record_call", lambda **entry: records.append(entry))

    @contextmanager
    def stream(method, url, **kwargs):
        yield httpx.Response(200, request=httpx.Request(method, url), content=(
            b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n'
        ))

    monkeypatch.setattr(reasoner._client, "stream", stream)
    prompt = _build(hits=_hits(1))
    for user_prompt in (prompt, "separate request"):
        assert reasoner._stream_completion(
            endpoint="https://gateway.example/chat/completions", model="fast-x",
            system_prompt="system policy", user_prompt=user_prompt,
        ) == "ok"
    assert records[0]["stage_key"] == "agent_synthesis"
    assert records[0]["context_estimate"] == dict(prompt.context_counts)
    assert records[1]["context_estimate"] is None
    assert records[1]["stage_key"] is None


def test_reviewed_playbooks_use_original_input_in_both_planning_and_synthesis(monkeypatch):
    calls = []
    book = {"id": "policy-check", "title": "政策方法", "instructions": ["找原始文件"],
            "source_url": "repo://policy", "reviewed_at": "2026-09-13"}

    def select(text, **kwargs):
        calls.append(text)
        return [book]

    monkeypatch.setattr("backend.app.services.checking_playbooks.select_checking_playbooks", select)
    reasoner = _reasoner()
    request, event, bundle = _inputs()
    synthesis = reasoner._build_synthesis_prompt(request=request, event=event, retrieval_bundle=bundle)
    planning = reasoner._build_investigation_prompt(event=event, retrieval_bundle=bundle, round_index=1)
    assert calls == [request.raw_input, event.raw_input]
    assert _payload(synthesis)["checking_playbooks"] == [book]
    assert "never factual evidence or citation targets" in planning
    assert "policy-check" in planning
    assert all(hit["result_id"] != book["id"] for hit in _payload(synthesis)["retrieval_hits"])
