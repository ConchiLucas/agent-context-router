from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status

from context_router.schemas.ai_interface_visualization import (
    AiInterfaceRequestDetail,
    AiInterfaceRequestList,
)
from context_router.services.ai_interface_visualization import (
    AiInterfaceVisualizationError,
    AiInterfaceVisualizationService,
)

router = APIRouter(
    prefix="/ai-visualization/interface-requests",
    tags=["ai-interface-visualization"],
)


def _service(request: Request) -> AiInterfaceVisualizationService:
    return request.app.state.ai_interface_visualization_service


def _error(exc: AiInterfaceVisualizationError) -> HTTPException:
    code = (
        status.HTTP_404_NOT_FOUND
        if exc.code == "request_not_found"
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return HTTPException(status_code=code, detail=str(exc))


@router.get("", response_model=AiInterfaceRequestList)
def list_requests(
    request: Request,
    workspace_id: str | None = Query(default=None, min_length=1, max_length=32),
    success: bool | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100_000),
):
    try:
        return _service(request).list_requests(
            workspace_id=workspace_id,
            success=success,
            limit=limit,
            offset=offset,
        )
    except AiInterfaceVisualizationError as exc:
        raise _error(exc) from exc


@router.get("/{request_id}", response_model=AiInterfaceRequestDetail)
def request_detail(request_id: str, request: Request):
    try:
        return _service(request).get_request(request_id)
    except AiInterfaceVisualizationError as exc:
        raise _error(exc) from exc

