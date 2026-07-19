from __future__ import annotations

import json
import queue
from datetime import datetime, timezone
from threading import Thread
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from backend.app.core.exceptions import AppError
from backend.app.models.schemas import AnalyzeRequest, Report
from backend.app.services.analyze_pipeline import AnalyzePipeline
from backend.app.services.progress import reset_progress_callback, set_progress_callback

router = APIRouter()
_STREAM_DONE = object()
# Longest allowed silence on the stream. A single Kimi $web_search round can
# block ~45s with no pipeline event; without a keepalive, proxies/browsers may
# idle-timeout and drop the connection. Emit a heartbeat if the queue is quiet
# this long so the NDJSON stream never goes silent.
_HEARTBEAT_INTERVAL_SECONDS = 10.0


@router.post("/analyze", response_model=Report)
def analyze(payload: AnalyzeRequest) -> Report:
    pipeline = AnalyzePipeline()
    return pipeline.analyze(payload)


@router.post("/analyze/stream")
def analyze_stream(payload: AnalyzeRequest, request: Request) -> StreamingResponse:
    event_queue: queue.Queue[dict[str, Any] | object] = queue.Queue()
    run_id = uuid4().hex
    trace_id = getattr(request.state, "request_id", "unknown")

    def push_event(event: dict[str, Any]) -> None:
        event_queue.put(
            {
                "emitted_at": datetime.now(timezone.utc).isoformat(),
                **event,
            }
        )

    def worker() -> None:
        token = set_progress_callback(push_event)
        try:
            preview = payload.raw_input.strip().replace("\r", " ").replace("\n", " ")
            if len(preview) > 140:
                preview = preview[:137] + "..."
            push_event(
                {
                    "type": "session",
                    "run_id": run_id,
                    "trace_id": trace_id,
                    "input_type": payload.input_type or "auto",
                    "summary": "后端已接收分析任务，开始执行流式追踪。",
                    "preview": preview,
                }
            )
            pipeline = AnalyzePipeline()
            report = pipeline.analyze(payload)
            push_event(
                {
                    "type": "report",
                    "run_id": run_id,
                    "summary": f"分析完成，输出 {report.mode}。",
                    "report": report.model_dump(mode="json"),
                }
            )
            push_event(
                {
                    "type": "complete",
                    "run_id": run_id,
                    "success": True,
                    "summary": "分析流程已结束。",
                }
            )
        except AppError as exc:
            push_event(
                {
                    "type": "error",
                    "run_id": run_id,
                    "code": exc.code,
                    "message": exc.message,
                    "status_code": exc.status_code,
                    "details": _stringify_error_details(exc.details),
                }
            )
            push_event(
                {
                    "type": "complete",
                    "run_id": run_id,
                    "success": False,
                    "summary": f"分析失败: {exc.code}",
                }
            )
        except Exception as exc:  # pragma: no cover
            push_event(
                {
                    "type": "error",
                    "run_id": run_id,
                    "code": "internal_server_error",
                    "message": "The server hit an unexpected error.",
                    "status_code": 500,
                    "details": [f"error_type={exc.__class__.__name__}"],
                }
            )
            push_event(
                {
                    "type": "complete",
                    "run_id": run_id,
                    "success": False,
                    "summary": "分析因意外错误中止。",
                }
            )
        finally:
            reset_progress_callback(token)
            event_queue.put(_STREAM_DONE)

    def event_stream():
        worker_thread = Thread(target=worker, name=f"analyze-stream-{run_id}", daemon=True)
        worker_thread.start()
        while True:
            try:
                item = event_queue.get(timeout=_HEARTBEAT_INTERVAL_SECONDS)
            except queue.Empty:
                # Worker is busy (e.g. a slow web-search round) but alive; emit a
                # keepalive so the connection is not idle-timed-out mid-analysis.
                yield json.dumps(
                    {
                        "type": "heartbeat",
                        "run_id": run_id,
                        "emitted_at": datetime.now(timezone.utc).isoformat(),
                    },
                    ensure_ascii=False,
                ) + "\n"
                continue
            if item is _STREAM_DONE:
                break
            yield json.dumps(item, ensure_ascii=False) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


def _stringify_error_details(details: dict[str, Any] | None) -> list[str]:
    if not details:
        return []
    lines: list[str] = []
    for key, value in details.items():
        if isinstance(value, (list, dict)):
            lines.append(f"{key}={json.dumps(value, ensure_ascii=False)}")
        else:
            lines.append(f"{key}={value}")
    return lines[:8]
