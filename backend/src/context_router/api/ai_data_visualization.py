from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status

from context_router.schemas.ai_data_visualization import (
    AiDataQueryHistory,
    AiDataQueryLatest,
    AiDataQueryRecord,
    AiDataQueryWrite,
)
from context_router.services.ai_data_visualization import (
    AiDataVisualizationError,
    AiDataVisualizationService,
)

router = APIRouter(prefix="/ai-visualization/query-records", tags=["ai-data-visualization"])


def _service(request: Request) -> AiDataVisualizationService:
    return request.app.state.ai_data_visualization_service


def _error(exc: AiDataVisualizationError) -> HTTPException:
    code = status.HTTP_400_BAD_REQUEST
    if exc.code in {
        "workspace_not_found",
        "environment_not_found",
        "relation_snapshot_not_found",
        "relation_table_not_found",
    }:
        code = status.HTTP_404_NOT_FOUND
    return HTTPException(status_code=code, detail=f"{exc.code}: {exc}")


@router.post("", response_model=AiDataQueryRecord, status_code=status.HTTP_201_CREATED)
def create(payload: AiDataQueryWrite, request: Request) -> AiDataQueryRecord:
    """Accept one validated query-condition record from a local AI or operations client."""
    try:
        return _service(request).create(payload)
    except AiDataVisualizationError as exc:
        raise _error(exc) from exc


@router.get("/latest", response_model=AiDataQueryLatest)
def latest(request: Request) -> AiDataQueryLatest:
    try:
        return _service(request).latest()
    except AiDataVisualizationError as exc:
        raise _error(exc) from exc


@router.get("", response_model=AiDataQueryHistory)
def history(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
) -> AiDataQueryHistory:
    try:
        return _service(request).history(limit=limit)
    except AiDataVisualizationError as exc:
        raise _error(exc) from exc
