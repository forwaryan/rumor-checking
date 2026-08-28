"""Regression test for the pipeline-level model-override / failover bug.

Bug: `_apply_model_override` used to call `resolve_model(None)`, which returns the
DEFAULT model as a concrete string, and pinned it to `model_override` on EVERY
request — even when the user picked nothing. Downstream, `_candidate_models`
reads any non-None `model_override` as "the user demanded this exact model, never
fail over", so the failover candidate list collapsed to a single model. A flaky
default (GLM-5.2 returning empty 14× in one run) then dragged the whole analysis
into safe_mode instead of switching to a healthy alternate.

Fix: only pin `model_override` when the user explicitly picked a valid model;
otherwise leave it None so the default is merely the primary failover candidate.
"""
from __future__ import annotations

from backend.app.models.schemas import AnalyzeRequest
from backend.app.services.analyze_pipeline import AnalyzePipeline


def _apply(pipeline: AnalyzePipeline, model_ctx) -> str | None:
    ctx = {} if model_ctx is _UNSET else {"model": model_ctx}
    request = AnalyzeRequest(raw_input="京东今年裁员", request_context=ctx)
    pipeline._apply_model_override(request)
    return pipeline.agent_reasoner.model_override


_UNSET = object()


def test_no_pick_leaves_override_none_so_failover_stays_enabled():
    pipeline = AnalyzePipeline()
    assert _apply(pipeline, _UNSET) is None
    # With no override, the candidate list must span the whole whitelist so a
    # flaky primary can fail over to healthy alternates.
    primary = pipeline.agent_reasoner._reasoning_model()
    candidates = pipeline.agent_reasoner._candidate_models(primary)
    assert len(candidates) == len(pipeline.settings.available_models)
    assert set(candidates) == set(pipeline.settings.available_models)


def test_invalid_pick_leaves_override_none():
    pipeline = AnalyzePipeline()
    assert _apply(pipeline, "not-a-real-model") is None
    assert _apply(pipeline, "") is None


def test_valid_explicit_pick_pins_and_disables_failover():
    pipeline = AnalyzePipeline()
    chosen = pipeline.settings.available_models[-1]
    assert _apply(pipeline, chosen) == chosen
    # An explicit pick is honored exactly — no silent failover off the user's choice.
    assert pipeline.agent_reasoner._candidate_models(chosen) == [chosen]


def test_override_applied_to_both_reasoner_and_enricher():
    pipeline = AnalyzePipeline()
    chosen = pipeline.settings.available_models[-1]
    _apply(pipeline, chosen)
    assert pipeline.agent_reasoner.model_override == chosen
    assert pipeline.provider_enricher.provider.model_override == chosen
    # And clearing back to no-pick resets both.
    _apply(pipeline, _UNSET)
    assert pipeline.agent_reasoner.model_override is None
    assert pipeline.provider_enricher.provider.model_override is None
