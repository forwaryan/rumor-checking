"""Optional OpenTelemetry export of existing agent traces to Phoenix."""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any

from backend.app.agent.trace import TraceRecord, TraceSpan

logger = logging.getLogger(__name__)


def _safe_attributes(values: dict[str, Any], *, prefix: str = "") -> dict[str, Any]:
    attributes: dict[str, Any] = {}
    for key, value in values.items():
        name = f"{prefix}{key}"
        if isinstance(value, (str, bool, int, float)):
            attributes[name] = value
        elif value is not None:
            attributes[name] = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return attributes


def span_attributes(span: TraceSpan) -> dict[str, Any]:
    """Translate a local trace span into Phoenix/OpenTelemetry attributes."""
    attributes = {
        "openinference.span.kind": "TOOL",
        "rumor_checking.span_id": span.span_id,
        "rumor_checking.success": span.success,
        **_safe_attributes(span.metadata, prefix="rumor_checking.metadata."),
    }
    if span.parent_span_id:
        attributes["rumor_checking.parent_span_id"] = span.parent_span_id
    if span.error_type:
        attributes["error.type"] = span.error_type
    if span.error_message:
        attributes["error.message"] = span.error_message
    for key, value in span.token_usage.items():
        attributes[f"llm.token_count.{key}"] = value
    return attributes


def build_spans(record: TraceRecord, tracer: Any) -> None:
    """Emit `record` as OpenInference spans on the given OTel tracer.

    Split out from export_trace_to_phoenix so the span-construction logic can be
    verified against an in-memory exporter without a live Phoenix/OTLP endpoint —
    the tree shape, span kinds, attributes, and OK/ERROR status are exactly what a
    real Phoenix would receive. Imports OTel lazily via the caller."""
    from opentelemetry import trace
    from opentelemetry.trace import Status, StatusCode

    root = tracer.start_span(
        "rumor-checking.run",
        start_time=int(record.start_time * 1_000_000_000),
        attributes={
            "openinference.span.kind": "CHAIN",
            "session.id": record.run_id,
            "rumor_checking.total_tokens": record.total_tokens,
            **_safe_attributes(record.metadata, prefix="rumor_checking.metadata."),
        },
    )
    children: dict[str | None, list[TraceSpan]] = defaultdict(list)
    known_ids = {span.span_id for span in record.spans}
    for span in record.spans:
        parent_id = span.parent_span_id if span.parent_span_id in known_ids else None
        children[parent_id].append(span)

    def emit(span: TraceSpan, parent: Any) -> None:
        otel_span = tracer.start_span(
            span.action,
            context=trace.set_span_in_context(parent),
            start_time=int(span.start_time * 1_000_000_000),
            attributes=span_attributes(span),
        )
        otel_span.set_status(Status(StatusCode.OK if span.success else StatusCode.ERROR))
        for child in children.get(span.span_id, []):
            emit(child, otel_span)
        end_time = span.end_time if span.end_time >= span.start_time else span.start_time
        otel_span.end(end_time=int(end_time * 1_000_000_000))

    for span in children.get(None, []):
        emit(span, root)
    root_end = record.end_time if record.end_time >= record.start_time else record.start_time
    root.end(end_time=int(root_end * 1_000_000_000))


def export_trace_to_phoenix(
    record: TraceRecord,
    *,
    enabled: bool,
    endpoint: str,
    project_name: str,
    api_key: str | None = None,
    timeout_seconds: float = 2.0,
) -> bool:
    """Export a completed trace, returning False when disabled or unavailable.

    OpenTelemetry is imported lazily so the default offline/test path keeps no
    observability dependency. Export failures never affect the analysis result.
    """
    if not enabled:
        return False

    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning(
            "phoenix_trace_export_skipped reason=missing_opentelemetry_dependencies"
        )
        return False

    try:
        headers = {"api_key": api_key} if api_key else None
        provider = TracerProvider(
            resource=Resource.create({
                "service.name": "rumor-checking",
                "openinference.project.name": project_name,
            })
        )
        exporter = OTLPSpanExporter(
            endpoint=endpoint,
            headers=headers,
            timeout=timeout_seconds,
        )
        processor = BatchSpanProcessor(
            exporter,
            schedule_delay_millis=100,
            max_export_batch_size=64,
        )
        provider.add_span_processor(processor)
        tracer = provider.get_tracer("rumor-checking.agent")

        build_spans(record, tracer)

        provider.force_flush(timeout_millis=max(int(timeout_seconds * 1000), 100))
        provider.shutdown()
        return True
    except Exception as exc:
        logger.warning("phoenix_trace_export_failed error=%s", str(exc)[:200])
        return False
