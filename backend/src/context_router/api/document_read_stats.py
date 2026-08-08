from fastapi import APIRouter, HTTPException, Query, Request, status

from context_router.schemas.document_read_stats import (
    DocumentReadStatItem,
    DocumentReadTaskItem,
)
from context_router.services.document_read_stats import (
    DocumentReadStatsService,
    DocumentReadStatsServiceError,
)

router = APIRouter(tags=["document-read-stats"])


def _stats_service(request: Request) -> DocumentReadStatsService:
    return request.app.state.document_read_stats_service


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


@router.get(
    "/document-read-stats",
    response_model=list[DocumentReadStatItem],
)
def list_document_read_stats(
    request: Request,
    workspace_id: str | None = Query(None, description="工作空间 ID 过滤"),
    limit: int = Query(50, ge=1, le=200, description="返回最大记录数量"),
) -> list[DocumentReadStatItem]:
    service = _stats_service(request)
    try:
        return service.list_document_read_stats(
            workspace_id=workspace_id,
            limit=limit,
        )
    except DocumentReadStatsServiceError as exc:
        raise _bad_request(str(exc)) from exc


@router.get(
    "/document-read-stats/{document_id:path}/tasks",
    response_model=list[DocumentReadTaskItem],
)
def list_document_read_tasks(
    document_id: str,
    request: Request,
    limit: int = Query(50, ge=1, le=200, description="返回最大记录数量"),
) -> list[DocumentReadTaskItem]:
    service = _stats_service(request)
    try:
        return service.list_document_read_tasks(
            document_id=document_id,
            limit=limit,
        )
    except DocumentReadStatsServiceError as exc:
        raise _bad_request(str(exc)) from exc
