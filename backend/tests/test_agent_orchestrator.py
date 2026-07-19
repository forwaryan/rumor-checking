from __future__ import annotations

import re

import pytest

from backend.app.core.config import get_settings
from backend.app.models.schemas import AnalyzeRequest
from backend.app.services.analyze_pipeline import AnalyzePipeline

# Inputs spanning the internal input types, all with stable mock retrieval.
PARITY_INPUTS = [
    ("【海州市市场监管局通报】2026年3月1日，海州市市场监管局发布通报称，在例行抽检中发现海州新鲜屋连锁门店有2批次酸奶超过保质期，涉事门店已停业整改。", "text_news"),
    ("晨星生物裁员40%是真的吗？", "question"),
    ("https://news.example.com/2026/03/05/ferry-delay", "url"),
    ("最近有个女网红脑出血死了真的假的？", "question"),
]

# Matches an ISO-8601 timestamp that carries a microsecond component — i.e. a
# generated "now" fallback (real mock dates are whole-day, no microseconds).
_NOW_ISO = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+")


def _scrub(value):
    """Recursively replace generated 'now' timestamps so two independent runs
    can be compared for structural/behavioural parity."""
    if isinstance(value, str):
        return _NOW_ISO.sub("<NOW>", value)
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    if isinstance(value, dict):
        return {key: _scrub(item) for key, item in value.items()}
    return value


def _report_for(monkeypatch, *, orchestrator: bool, raw_input: str, input_type: str):
    monkeypatch.setenv("AGENT_ORCHESTRATOR_ENABLED", "true" if orchestrator else "false")
    get_settings.cache_clear()
    pipeline = AnalyzePipeline()
    report = pipeline.analyze(AnalyzeRequest(raw_input=raw_input, input_type=input_type))
    return _scrub(report.model_dump(mode="json"))


@pytest.mark.parametrize("raw_input,input_type", PARITY_INPUTS)
def test_agent_orchestrator_matches_legacy_pipeline_on_off_mock(monkeypatch, raw_input, input_type):
    # Autouse fixture pins off+mock + isolated cache; both runs share it.
    legacy = _report_for(monkeypatch, orchestrator=False, raw_input=raw_input, input_type=input_type)
    agent = _report_for(monkeypatch, orchestrator=True, raw_input=raw_input, input_type=input_type)
    assert agent == legacy


def test_agent_orchestrator_falls_back_to_pipeline_on_runner_error(monkeypatch):
    monkeypatch.setenv("AGENT_ORCHESTRATOR_ENABLED", "true")
    get_settings.cache_clear()

    pipeline = AnalyzePipeline()

    # Force the agent runner to blow up; analyze() must fall back to the legacy
    # fixed pipeline and still return a valid Report.
    import backend.app.agent.runner as runner_mod

    def boom(self, request):
        raise RuntimeError("runner_exploded")

    monkeypatch.setattr(runner_mod.AgentRunner, "run", boom)

    report = pipeline.analyze(
        AnalyzeRequest(raw_input="晨星生物裁员40%是真的吗？", input_type="question")
    )
    assert report.mode in {"safe_mode", "partial_mode", "complete_mode"}
    assert report.provenance is not None


def test_agent_orchestrator_disabled_by_default():
    get_settings.cache_clear()
    assert get_settings().agent_orchestrator_enabled is False
