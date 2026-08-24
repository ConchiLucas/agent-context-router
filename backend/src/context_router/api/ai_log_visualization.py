from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status

from context_router.schemas.ai_log_visualization import (
    AiLogInvestigationDetail,
    AiLogInvestigationList,
)
from context_router.services.ai_log_visualization import (
    AiLogVisualizationError,
    AiLogVisualizationService,
)

router = APIRouter(
    prefix="/ai-visualization/log-investigations",
    tags=["ai-log-visualization"],
)


def _service(request: Request) -> AiLogVisualizationService:
    return request.app.state.ai_log_visualization_service


def _error(exc: AiLogVisualizationError) -> HTTPException:
    if exc.code in {"record_not_found", "workspace_not_found"}:
        code = status.HTTP_404_NOT_FOUND
    elif exc.code == "invalid_cursor":
        code = status.HTTP_400_BAD_REQUEST
    else:
        code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HTTPException(status_code=code, detail=str(exc))


@router.get("", response_model=AiLogInvestigationList)
def list_investigations(
    request: Request,
    workspace_id: str | None = Query(default=None, min_length=1, max_length=36),
    severity: str | None = Query(default=None, pattern="^(error|critical)$"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100_000),
    cursor: str | None = Query(default=None, min_length=1, max_length=500),
    task_id: int | None = Query(default=None, ge=1),
):
    try:
        return _service(request).list_records(
            workspace_id=workspace_id,
            severity=severity,
            limit=limit,
            offset=offset,
            cursor=cursor,
            task_id=task_id,
        )
    except AiLogVisualizationError as exc:
        raise _error(exc) from exc


@router.get("/{record_id}", response_model=AiLogInvestigationDetail)
def investigation_detail(record_id: str, request: Request):
    try:
        return _service(request).get_record(record_id)
    except AiLogVisualizationError as exc:
        raise _error(exc) from exc
