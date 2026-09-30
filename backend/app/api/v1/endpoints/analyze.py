from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from backend.app.core.exceptions import error_response
from backend.app.models.schemas import AnalyzeRequest, Report
from backend.app.services.analysis_runs import AnalysisRunManager, get_analysis_run_manager

router = APIRouter()
_MIN_POLL_SECONDS = 0.05
_MAX_POLL_SECONDS = 0.5


@router.post("/analyze", response_model=Report)
async def analyze(
    payload: AnalyzeRequest, request: Request, response: Response,
    manager: AnalysisRunManager = Depends(get_analysis_run_manager),
) -> Report | JSONResponse:
    run = await asyncio.to_thread(manager.create, payload)
    response.headers["X-Analysis-Run-ID"] = run.run_id
    # Poll tightly at first so a cached/fast run answers immediately, then back off:
    # a deep run lasts minutes and there is nothing to gain from asking 20x a second.
    delay = _MIN_POLL_SECONDS
    while run.status in {"queued", "running"}:
        await asyncio.sleep(delay)
        delay = min(delay * 1.5, _MAX_POLL_SECONDS)
        run = await asyncio.to_thread(manager.get, run.run_id)
    if run.status == "completed" and run.report is not None:
        return run.report
    stopped = run.status == "cancelled"
    details = {"run_id": run.run_id, "stop_reason": run.stop_reason}
    if run.status == "failed":
        events, _run = await asyncio.to_thread(manager.event_page, run.run_id, max(0, run.last_event_id - 3))
        for envelope in events:
            event = envelope.get("event", envelope)
            if event.get("type") == "error" and event.get("error_type"):
                details["error_type"] = event["error_type"]
    failure = error_response(
        request=request, status_code=504 if run.stop_reason == "agent_timeout" else 409 if stopped else 500,
        code="analysis_stopped" if stopped else "internal_server_error",
        message="Analysis stopped before producing a report." if stopped else "The server hit an unexpected error.",
        details=details,
    )
    failure.headers["X-Analysis-Run-ID"] = run.run_id
    return failure


@router.post("/analyze/stream")
async def analyze_stream(
    payload: AnalyzeRequest, request: Request,
    manager: AnalysisRunManager = Depends(get_analysis_run_manager),
) -> StreamingResponse:
    run = await asyncio.to_thread(manager.create, payload)
    trace_id = getattr(request.state, "request_id", "unknown")

    async def event_stream():
        async for line in manager.events(run.run_id):
            envelope = json.loads(line)
            event = envelope.get("event", envelope)
            if event.get("type") == "session":
                event = {**event, "trace_id": trace_id, "input_type": payload.input_type or "auto",
                         "preview": " ".join(payload.raw_input.split())[:140]}
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson",
                             headers={"X-Analysis-Run-ID": run.run_id, "Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
