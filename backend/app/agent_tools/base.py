from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ToolContext:
    """Shared service instances the tools operate through.

    Built from an AnalyzePipeline's own service objects so that anything the
    caller monkeypatches (tests swap pipeline.agent_reasoner, .provider_enricher,
    .retriever, ...) is the exact instance the tools use.
    """

    settings: object
    input_normalizer: object
    retriever: object
    url_content_extractor: object
    question_resolver: object
    agent_reasoner: object
    provider_enricher: object
    claim_extractor: object
    verdict_engine: object
    timeline_builder: object
    report_builder: object
    content_check_builder: object
    pipeline_trace_builder: object
