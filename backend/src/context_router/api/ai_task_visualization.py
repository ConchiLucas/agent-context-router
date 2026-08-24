from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status

from context_router.schemas.ai_task_visualization import (
    AiTaskDisplayStatus,
    AiTaskTimeline,
    AiTaskVisualizationDetail,
    AiTaskVisualizationList,
)
from context_router.services.ai_task_visualization import (
    AiTaskVisualizationError,
    AiTaskVisualizationService,
)

router = APIRouter(prefix="/ai-visualization/tasks", tags=["ai-task-visualization"])


def _service(request: Request) -> AiTaskVisualizationService:
    return request.app.state.ai_task_visualization_service


def _http_error(exc: AiTaskVisualizationError) -> HTTPException:
    if exc.code == "task_not_found":
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("", response_model=AiTaskVisualizationList, response_model_exclude_none=True)
def list_ai_tasks(
    request: Request,
    workspace_id: str | None = Query(default=None, max_length=36),
    environment: str | None = Query(default=None, max_length=32),
    agent_name: str | None = Query(default=None, max_length=64),
    task_status: Annotated[AiTaskDisplayStatus | None, Query(alias="status")] = None,
    keyword: str | None = Query(default=None, max_length=500),
    limit: int = Query(default=30, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=500),
) -> AiTaskVisualizationList:
    try:
        return _service(request).list_tasks(
            workspace_id=workspace_id,
            environment=environment,
            agent_name=agent_name,
            status=task_status,
            keyword=keyword,
            limit=limit,
            cursor=cursor,
        )
    except AiTaskVisualizationError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/{task_id}/timeline",
    response_model=AiTaskTimeline,
    response_model_exclude_none=True,
)
def get_ai_task_timeline(
    task_id: int,
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=500),
    event_type: Literal[
        "mcp_call",
        "data_query",
        "interface_request",
        "log_investigation",
        "task_result",
    ]
    | None = Query(default=None),
) -> AiTaskTimeline:
    try:
        _service(request).get_task(task_id)
        return _service(request).timeline(
            task_id,
            limit=limit,
            cursor=cursor,
            event_type=event_type,
        )
    except AiTaskVisualizationError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/{task_id}",
    response_model=AiTaskVisualizationDetail,
    response_model_exclude_none=True,
)
def get_ai_task(task_id: int, request: Request) -> AiTaskVisualizationDetail:
    try:
        return _service(request).get_task(task_id)
    except AiTaskVisualizationError as exc:
        raise _http_error(exc) from exc
