from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from hashlib import sha256
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.app.models.schemas import ClaimResult, Event, EvidenceItem, Report
from backend.app.services.evidence_snapshots import (
    capture_evidence_text,
    evidence_capture,
)


def evidence(quote=None, url="https://example.org/notice"):
    return EvidenceItem(title="公告", url=url, source_name="公告机构", published_at="2026-09-13T00:00:00Z",
                        snippet="模型整理的摘要", relevance_reason="说明开放情况", stance_quote=quote)


def report_with(item):
    return Report(mode="partial_mode", event=Event(title="核查", summary="核查", source_url=item.url,
                  source_name="公告机构", published_at=item.published_at, keywords=[], mode="partial_mode"),
                  claim_results=[ClaimResult(claim="场馆开放", claim_type="fact", verdict="supported",
                                            confidence="high", notes="有公告", evidence=[item])],
                  sources=[item], final_summary="核查结果", provenance={
                      "source_type": "backend_live", "event_source": "input_normalized", "claim_source": "rule",
                      "evidence_source": "retrieval_live", "timeline_source": "none",
                  })


def test_exact_quote_uses_captured_body_and_unicode_offsets():
    body = "公告😀：展馆免费开放。预约仍然必要。"
    original = report_with(evidence("展馆免费开放。"))
    with evidence_capture() as capture:
        capture_evidence_text(url=original.sources[0].url, text=body, kind="page_text",
                              acquisition="fetched", extractor="article-v1")
        result = capture.bind_report(original)
    item = result.claim_results[0].evidence[0]
    snapshot = result.evidence_snapshots[0]
    assert item.quote_status == "matched"
    assert snapshot.text[item.quote_start:item.quote_end] == item.stance_quote
    assert snapshot.text_sha256 == sha256(body.encode()).hexdigest()
    assert item.snapshot_id == snapshot.snapshot_id
    assert original.evidence_snapshots == []
    assert original.sources[0].snapshot_id is None
    assert Report.model_validate_json(result.model_dump_json()) == result


def test_generated_snippet_cannot_validate_a_quote():
    item = evidence("模型整理的摘要")
    with evidence_capture() as capture:
        result = capture.bind_report(report_with(item))
    assert result.sources[0].quote_status == "unavailable"
    assert result.evidence_snapshots == []
    with evidence_capture() as capture:
        capture_evidence_text(url=item.url, text="真实公告没有相关说法。", kind="page_text",
                              acquisition="fetched", extractor="article-v1")
        result = capture.bind_report(report_with(item))
    assert result.sources[0].quote_status == "unmatched"
    assert result.sources[0].quote_start is None


def test_search_snippet_is_not_promoted_to_page_text():
    item = evidence("只在搜索摘要出现")
    with evidence_capture() as capture:
        capture_evidence_text(url=item.url, text="只在搜索摘要出现", kind="search_snippet",
                              acquisition="retrieved", extractor="search-snippet-v1")
        capture_evidence_text(url=item.url, text="抓到的正文并未包含该引文", kind="page_text",
                              acquisition="cached", extractor="article-v1")
        result = capture.bind_report(report_with(item))
    assert result.sources[0].quote_status == "matched"
    bound = next(snapshot for snapshot in result.evidence_snapshots if snapshot.snapshot_id == result.sources[0].snapshot_id)
    assert bound.kind == "search_snippet"
    assert len(result.evidence_snapshots) == 2


def test_content_identity_ignores_capture_time_but_tracks_content_and_url():
    snapshots = []
    for url, text in [("https://example.org/notice", "原文"), ("https://example.org/notice", "原文"),
                      ("https://example.org/notice", "修改正文"), ("https://example.org/other", "原文")]:
        with evidence_capture() as capture:
            capture_evidence_text(url=url, text=text, kind="page_text", acquisition="fetched", extractor="article-v1")
            snapshots.append(capture.bind_report(report_with(evidence(url=url))).evidence_snapshots[0])
    assert snapshots[0].snapshot_id == snapshots[1].snapshot_id
    assert len({snapshot.snapshot_id for snapshot in snapshots}) == 3


def test_capture_is_bounded_and_excludes_uncited_or_private_sources():
    with evidence_capture() as capture:
        capture_evidence_text(url="https://example.org/unused", text="无引用的网页", kind="page_text",
                              acquisition="fetched", extractor="article-v1")
        capture_evidence_text(url="http://127.0.0.1/private", text="不应留档", kind="page_text",
                              acquisition="fetched", extractor="article-v1")
        capture_evidence_text(url="https://example.org/notice", text="文" * 25000, kind="page_text",
                              acquisition="fetched", extractor="article-v1")
        result = capture.bind_report(report_with(evidence()))
    assert len(result.evidence_snapshots) == 1
    assert len(result.evidence_snapshots[0].text) == 24000
    assert result.evidence_snapshots[0].truncated


def test_capture_context_isolated_and_shared_across_copied_threads():
    with evidence_capture() as outer:
        with ThreadPoolExecutor(max_workers=2) as pool:
            future = pool.submit(copy_context().run, capture_evidence_text, url="https://example.org/notice",
                                 text="并发原文", kind="page_text", acquisition="fetched", extractor="article-v1")
            future.result()
        with evidence_capture() as inner:
            assert inner.bind_report(report_with(evidence())).evidence_snapshots == []
        assert outer.bind_report(report_with(evidence())).evidence_snapshots[0].text == "并发原文"
    capture_evidence_text(url="https://example.org/notice", text="无运行上下文", kind="page_text",
                          acquisition="fetched", extractor="article-v1")


def test_supplied_snapshot_references_are_not_trusted():
    item = evidence("伪造引文").model_copy(update={"snapshot_id": "a" * 64, "quote_start": 0,
                                                 "quote_end": 4, "quote_status": "matched"})
    with evidence_capture() as capture:
        result = capture.bind_report(report_with(item))
    assert result.sources[0].snapshot_id is None
    assert result.sources[0].quote_status == "unavailable"


def captured_report(body, quote=None, extractor="article-v1"):
    with evidence_capture() as capture:
        capture_evidence_text(url="https://example.org/notice", text=body, kind="page_text",
                              acquisition="fetched", extractor=extractor)
        return capture.bind_report(report_with(evidence(quote)))


def test_snapshot_rejects_corrupt_text_and_identity():
    original = captured_report("原始公告")
    for field, value in [("text", "篡改正文"), ("snapshot_id", "0" * 64)]:
        payload = original.model_dump()
        payload["evidence_snapshots"][0][field] = value
        with pytest.raises(ValidationError):
            Report.model_validate(payload)


def test_report_comparison_distinguishes_quote_changes_and_source_changes():
    from backend.app.services.report_revisions import compare_reports

    before = captured_report("周一闭馆。周二开放。", "周一闭馆。")
    quote_changed = captured_report("周一闭馆。周二开放。", "周二开放。")
    comparison = compare_reports("next", "parent", before, quote_changed, [0])
    assert comparison.changes[0].kind == "changed"
    assert comparison.changed_source_urls == []
    after = captured_report("周一正常开放。周二开放。", "周二开放。")
    comparison = compare_reports("next", "parent", before, after, [0])
    assert comparison.changed_source_urls == ["https://example.org/notice"]
    assert comparison.added_source_urls == []
    different_extractor = captured_report("不同提取方式", extractor="tag-strip-v1")
    assert compare_reports("next", "parent", before, different_extractor, [0]).changed_source_urls == []


def test_report_comparison_does_not_include_unreviewed_sources():
    from backend.app.services.report_revisions import compare_reports

    before = captured_report("原始正文")
    after = captured_report("已修改正文")
    unrelated = before.claim_results[0].model_copy(update={"claim": "其他事项", "evidence": []})
    before = before.model_copy(update={"claim_results": [unrelated, *before.claim_results]})
    comparison = compare_reports("next", "parent", before, after, [0])
    assert comparison.changed_source_urls == []


def test_report_comparison_scopes_after_snapshot_to_matched_reviewed_claims():
    from backend.app.services.report_revisions import compare_reports

    before = captured_report("原始正文")
    after = captured_report("新正文")
    before_unreviewed = before.claim_results[0].model_copy(update={"claim": "未复核事项"})
    after_unreviewed = after.claim_results[0].model_copy(update={"claim": "未复核事项"})
    before = before.model_copy(update={"claim_results": [before.claim_results[0], before_unreviewed]})
    changed_reference = after.claim_results[0].model_copy(update={"evidence": [evidence(url="https://example.org/new")]})
    after = after.model_copy(update={"claim_results": [changed_reference, after_unreviewed]})
    assert compare_reports("next", "parent", before, after, [0]).changed_source_urls == []


def test_timeout_worker_inherits_capture_context():
    from backend.app.agent.multi.supervisor import Supervisor

    def run(state, context):
        capture_evidence_text(url="https://example.org/notice", text="来自带超时的子线程", kind="page_text",
                              acquisition="fetched", extractor="article-v1")

    with evidence_capture() as capture:
        Supervisor(SimpleNamespace())._invoke_agent(SimpleNamespace(run=run), None, timeout_seconds=2)
        result = capture.bind_report(report_with(evidence()))
    assert result.evidence_snapshots[0].text == "来自带超时的子线程"


def test_completed_checkpoint_resume_preserves_snapshot_identity_and_capture_time():
    from backend.app.agent.checkpoint import MemoryCheckpointStore, snapshot_state
    from backend.app.agent.planner import DONE
    from backend.app.agent.runner import AgentRunner
    from backend.app.agent.state import AgentState
    from backend.app.models.schemas import AnalyzeRequest

    original = captured_report("周一闭馆。", "周一闭馆。")
    state = AgentState(request=AnalyzeRequest(raw_input="场馆开放"))
    state.report = original
    store = MemoryCheckpointStore()
    store.save("finished-run", snapshot_state(state, "finalize_report", 8))
    context = SimpleNamespace(settings=SimpleNamespace(agent_wall_clock_seconds=0), agent_reasoner=SimpleNamespace())
    runner = AgentRunner(context, planner=SimpleNamespace(next_action=lambda state: DONE), checkpoint_store=store)
    with evidence_capture() as capture:
        resumed = capture.bind_report(runner.resume("finished-run"))
    assert resumed == original


def test_legacy_checkpoint_bodies_are_explicitly_marked_restored():
    from backend.app.services.evidence_snapshots import restore_captured_evidence
    from backend.app.services.retrieval_models import RetrievalBundle, SearchResult

    result = SearchResult(case_id="real_search", query="核查", result_id="source-1", title="公告",
                          url="https://example.org/notice", source_name="机构", published_at="", snippet="摘要", source_tier="A")
    bundle = RetrievalBundle(query="核查", canonical_results=(result,), provider_name="test")
    with evidence_capture() as capture:
        restore_captured_evidence(bundle, {"source-1": "完整正文并非总能从旧检查点恢复。"})
        report = capture.bind_report(report_with(evidence()))
    assert report.evidence_snapshots[0].acquisition == "restored"
    assert report.evidence_snapshots[0].extractor == "checkpoint-text-v1"
    assert report.evidence_snapshots[0].truncated


def test_durable_versions_keep_independent_snapshots(tmp_path, monkeypatch):
    from backend.app.models.schemas import AnalysisRecheckRequest, AnalyzeRequest
    from backend.app.services.analysis_runs import AnalysisRunManager

    owners = {}
    manager = AnalysisRunManager(tmp_path)

    def launch(run_id, owner, execution_lock):
        owners[run_id] = owner
        execution_lock.close()

    monkeypatch.setattr(manager, "_launch", launch)
    parent = manager.create(AnalyzeRequest(raw_input="场馆开放"))
    original = captured_report("周一闭馆。", "周一闭馆。")
    manager._finish(parent.run_id, owners[parent.run_id], report=original)
    child = manager.recheck(parent.run_id, AnalysisRecheckRequest(request_id="capture-review", claim_indices=[0]))
    updated = captured_report("周一开放。", "周一开放。")
    manager._finish(child.run_id, owners[child.run_id], report=updated)
    reloaded = AnalysisRunManager(tmp_path)
    assert reloaded.get(parent.run_id).report == original
    assert reloaded.get(child.run_id).report == updated
    assert reloaded.changes(child.run_id).changed_source_urls == ["https://example.org/notice"]
    events, _run = reloaded.event_page(child.run_id, 0)
    assert any(envelope["event"].get("report", {}).get("evidence_snapshots") for envelope in events)


def test_pipeline_collects_raw_retrieval_before_report_rewrites(monkeypatch):
    from backend.app.models.schemas import AnalyzeRequest, NormalizedEvent
    from backend.app.services.analyze_pipeline import AnalyzePipeline
    from backend.app.services.retrieval_models import RetrievalBundle, SearchResult

    pipeline = AnalyzePipeline()
    source = SearchResult(case_id="real_search", query="核查", result_id="source-1", title="公告",
                          url="https://example.org/notice", source_name="机构", published_at="", source_tier="A",
                          snippet="原始检索摘要：场馆恢复开放。")
    bundle = RetrievalBundle(query="核查", canonical_results=(source,), provider_name="test")
    monkeypatch.setattr(pipeline.retriever, "_retrieve_for_event", lambda *args, **kwargs: bundle)
    monkeypatch.setattr(pipeline, "_get_verdict_cache", lambda: None)

    def analyze(request):
        event = NormalizedEvent(summary="场馆开放", raw_input=request.raw_input, input_type="text_news")
        pipeline.retriever.retrieve_for_event(event, request_context={"search_sources": ["baidu"]})
        return report_with(evidence("场馆恢复开放。"))

    monkeypatch.setattr(pipeline, "_analyze_uncached", analyze)
    result = pipeline.analyze(AnalyzeRequest(raw_input="场馆开放"))
    assert result.evidence_snapshots[0].text == source.snippet
    assert result.evidence_snapshots[0].kind == "search_snippet"
    assert result.sources[0].snippet == "模型整理的摘要"
    assert result.sources[0].quote_status == "matched"


def test_public_url_boundaries_and_report_size_are_enforced():
    with evidence_capture() as capture:
        for url in ("https://user:secret@example.org/private", "http://localhost/private", "http://[::1]/",
                    "file:///tmp/private", "http://service.internal/", "http://10.0.0.1/"):
            capture_evidence_text(url=url, text="不应留档", kind="page_text", acquisition="fetched", extractor="article-v1")
            assert capture.bind_report(report_with(evidence(url=url))).evidence_snapshots == []
        items = []
        for index in range(30):
            url = f"https://example.org/{index}"
            capture_evidence_text(url=url, text="原文" * 12000, kind="page_text", acquisition="fetched", extractor="article-v1")
            items.append(evidence(url=url))
        original = report_with(items[0])
        original.claim_results[0].evidence = items
        result = capture.bind_report(original)
    assert sum(len(snapshot.text) for snapshot in result.evidence_snapshots) <= 120000
    assert len(result.evidence_snapshots) <= 24
    snapshot_ids = {snapshot.snapshot_id for snapshot in result.evidence_snapshots}
    assert all(item.snapshot_id is None or item.snapshot_id in snapshot_ids for item in result.claim_results[0].evidence)
