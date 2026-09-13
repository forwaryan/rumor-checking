from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from backend.app.core.exceptions import AppError
from backend.app.models.schemas import AnalysisRun, AnalyzeRequest
from backend.app.services.analysis_runs import AnalysisRunManager, get_analysis_run_manager

router = APIRouter()


@router.post("/analysis-runs", response_model=AnalysisRun, status_code=202)
def create_analysis_run(
    payload: AnalyzeRequest, manager: AnalysisRunManager = Depends(get_analysis_run_manager)
) -> AnalysisRun:
    return manager.create(payload)


@router.get("/analysis-runs/{run_id}", response_model=AnalysisRun)
def get_analysis_run(run_id: UUID, manager: AnalysisRunManager = Depends(get_analysis_run_manager)) -> AnalysisRun:
    return manager.get(run_id.hex)


@router.post("/analysis-runs/{run_id}/resume", response_model=AnalysisRun)
def resume_analysis_run(run_id: UUID, manager: AnalysisRunManager = Depends(get_analysis_run_manager)) -> AnalysisRun:
    return manager.resume(run_id.hex)


@router.get("/analysis-runs/{run_id}/events")
def analysis_run_events(
    run_id: UUID,
    after: int = Query(default=0, ge=0),
    manager: AnalysisRunManager = Depends(get_analysis_run_manager),
) -> StreamingResponse:
    run = manager.get(run_id.hex)
    if after > run.last_event_id:
        raise AppError(status_code=422, code="invalid_event_cursor", message="Event cursor is ahead of this run.")
    return StreamingResponse(
        manager.events(run_id.hex, after), media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
