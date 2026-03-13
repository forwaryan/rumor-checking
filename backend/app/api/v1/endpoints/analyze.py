from __future__ import annotations

from fastapi import APIRouter, Request

from backend.app.models.schemas import AnalyzeRequest, AnalyzeResponse
from backend.app.services.analyze_pipeline import AnalyzePipeline

router = APIRouter()
pipeline = AnalyzePipeline()


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(payload: AnalyzeRequest, request: Request) -> AnalyzeResponse:
    report = pipeline.analyze(payload)
    return AnalyzeResponse(request_id=request.state.request_id, report=report)
