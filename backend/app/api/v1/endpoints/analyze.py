from __future__ import annotations

from fastapi import APIRouter

from backend.app.models.schemas import AnalyzeRequest, Report
from backend.app.services.analyze_pipeline import AnalyzePipeline

router = APIRouter()
pipeline = AnalyzePipeline()


@router.post("/analyze", response_model=Report)
def analyze(payload: AnalyzeRequest) -> Report:
    return pipeline.analyze(payload)
