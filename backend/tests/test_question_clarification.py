"""Tests for the question_resolver ambiguity/clarification signal."""
from __future__ import annotations

import types

from backend.app.models.schemas import NormalizedEvent
from backend.app.services.analyze_pipeline import _apply_clarification_note
from backend.app.services.question_resolver import QuestionResolution, QuestionResolver
from backend.app.services.retrieval_models import RetrievalBundle, SearchResult


def _hit(rid: str, title: str, source: str, snippet: str = "") -> SearchResult:
    return SearchResult(
        case_id="c", query="q", result_id=rid, title=title, url=f"http://{rid}.example",
        source_name=source, published_at="2026-07-20", snippet=snippet or title, source_tier="A",
    )


def _resolve(question: str, hits) -> QuestionResolution:
    bundle = RetrievalBundle(query=question, canonical_results=tuple(hits))
    event = NormalizedEvent(summary=question, input_type="question_only", raw_input=question)
    return QuestionResolver().resolve(event=event, retrieval_bundle=bundle)


def test_distinct_events_trigger_clarification():
    """A question that maps to two genuinely different incidents flags ambiguity
    and still anchors to a best guess (a report is always produced)."""
    resolution = _resolve(
        "小米汽车出事了吗",
        [
            _hit("r1", "小米汽车发生交通事故一人受伤 官方回应", "财新网", "小米 汽车 交通事故 一人受伤"),
            _hit("r2", "小米汽车工厂发生火灾 无人员伤亡", "新华社", "小米 汽车 工厂 火灾 无伤亡"),
        ],
    )
    assert resolution.needs_clarification is True
    assert len(resolution.candidates) == 2
    assert resolution.selected_result is not None  # still guesses
    note = resolution.clarification_note()
    assert note and "多个不同事件" in note


def test_same_event_two_outlets_does_not_trigger_clarification():
    """The SAME incident covered by two outlets must not nag — high title-bigram
    overlap marks them as one event."""
    resolution = _resolve(
        "小米汽车事故是真的吗",
        [
            _hit("r1", "小米汽车发生交通事故一人受伤 官方回应", "财新网", "小米 汽车 交通事故 受伤"),
            _hit("r2", "小米汽车交通事故致一人受伤 警方通报", "新华社", "小米 汽车 交通事故 受伤 通报"),
        ],
    )
    assert resolution.needs_clarification is False
    assert resolution.candidates == ()
    assert resolution.clarification_note() is None


def test_single_result_never_triggers_clarification():
    resolution = _resolve(
        "小米汽车出事了吗",
        [_hit("r1", "小米汽车发生交通事故一人受伤 官方回应", "财新网", "小米 汽车 交通事故")],
    )
    assert resolution.needs_clarification is False


def test_clarification_note_gated_by_flag():
    """The note only reaches the report when AGENT_CLARIFICATION_ENABLED is on;
    otherwise the silent-guess behaviour is unchanged."""
    from backend.app.models.schemas import Event, Report, ReportProvenance

    event = NormalizedEvent(summary="s", input_type="question_only", raw_input="r")
    resolution = QuestionResolution(
        event=event, follow_up_query=None, selected_result=_hit("r1", "事故A", "财新"),
        needs_clarification=True, candidates=(_hit("r1", "事故A", "财新"), _hit("r2", "火灾B", "新华")),
    )
    report = Report(
        mode="partial_mode",
        event=Event(title="t", summary="s", source_url="http://x", source_name="财新",
                    published_at="2026-07-20", keywords=["k"], mode="partial_mode"),
        final_summary="fs", risks=["原有风险"],
        provenance=ReportProvenance(source_type="backend_live", event_source="retrieval_resolved",
                                    claim_source="rule", evidence_source="retrieval_live",
                                    timeline_source="retrieval"),
    )

    off = types.SimpleNamespace(agent_clarification_enabled=False)
    on = types.SimpleNamespace(agent_clarification_enabled=True)

    assert _apply_clarification_note(off, report, resolution).risks == ["原有风险"]
    on_risks = _apply_clarification_note(on, report, resolution).risks
    assert len(on_risks) == 2 and "多个不同事件" in on_risks[0]


def test_clarification_note_noop_when_no_ambiguity_even_if_enabled():
    from backend.app.models.schemas import Event, Report, ReportProvenance

    event = NormalizedEvent(summary="s", input_type="question_only", raw_input="r")
    resolution = QuestionResolution(
        event=event, follow_up_query=None, selected_result=_hit("r1", "事故A", "财新"),
    )
    report = Report(
        mode="partial_mode",
        event=Event(title="t", summary="s", source_url="http://x", source_name="财新",
                    published_at="2026-07-20", keywords=["k"], mode="partial_mode"),
        final_summary="fs", risks=["原有风险"],
        provenance=ReportProvenance(source_type="backend_live", event_source="retrieval_resolved",
                                    claim_source="rule", evidence_source="retrieval_live",
                                    timeline_source="retrieval"),
    )
    on = types.SimpleNamespace(agent_clarification_enabled=True)
    assert _apply_clarification_note(on, report, resolution).risks == ["原有风险"]


def test_resolution_details_do_not_leak_ambiguity_when_flag_off(monkeypatch):
    """default-OFF must be a full no-op: the needs_clarification signal must not
    leak into the pipeline-trace details either."""
    from dataclasses import replace

    from backend.app.core import config
    import backend.app.services.analyze_pipeline as ap
    from backend.app.services.analyze_pipeline import _question_resolution_details

    event = NormalizedEvent(summary="s", input_type="question_only", raw_input="r")
    resolution = QuestionResolution(
        event=event, follow_up_query=None, selected_result=_hit("r1", "事故A", "财新"),
        needs_clarification=True, candidates=(_hit("r1", "事故A", "财新"), _hit("r2", "火灾B", "新华")),
    )

    off = replace(config.get_settings(), agent_clarification_enabled=False)
    monkeypatch.setattr(ap, "get_settings", lambda: off)

    details = _question_resolution_details(resolution)
    assert not any("needs_clarification" in d for d in details)


def test_resolution_details_show_ambiguity_when_flag_on(monkeypatch):
    from dataclasses import replace

    from backend.app.core import config
    import backend.app.services.analyze_pipeline as ap
    from backend.app.services.analyze_pipeline import _question_resolution_details

    event = NormalizedEvent(summary="s", input_type="question_only", raw_input="r")
    resolution = QuestionResolution(
        event=event, follow_up_query=None, selected_result=_hit("r1", "事故A", "财新"),
        needs_clarification=True, candidates=(_hit("r1", "事故A", "财新"), _hit("r2", "火灾B", "新华")),
    )
    on = replace(config.get_settings(), agent_clarification_enabled=True)
    monkeypatch.setattr(ap, "get_settings", lambda: on)

    details = _question_resolution_details(resolution)
    assert any("needs_clarification=true" in d for d in details)


