from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status

from context_router.repositories.mcp_tool_call_repository import McpToolCallStatus
from context_router.schemas.mcp_traces import McpTraceDetail, McpTraceSummary
from context_router.services.mcp_trace import McpTraceService, McpTraceServiceError

router = APIRouter(prefix="/mcp-traces", tags=["mcp-traces"])


def _service(request: Request) -> McpTraceService:
    return request.app.state.mcp_trace_service


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


@router.get(
    "",
    response_model=list[McpTraceSummary],
    response_model_exclude_none=True,
)
def list_mcp_traces(
    request: Request,
    project_id: str | None = Query(default=None),
    agent_name: str | None = Query(default=None, max_length=64),
    server_name: str | None = Query(default=None, max_length=64),
    tool_name: str | None = Query(default=None, max_length=128),
    call_status: Annotated[McpToolCallStatus | None, Query(alias="status")] = None,
    keyword: str | None = Query(default=None, max_length=500),
    limit: int = Query(default=30, ge=1, le=100),
) -> list[McpTraceSummary]:
    try:
        return _service(request).list_traces(
            project_id=project_id,
            agent_name=agent_name,
            server_name=server_name,
            tool_name=tool_name,
            status=call_status,
            keyword=keyword,
            limit=limit,
        )
    except McpTraceServiceError as exc:
        raise _bad_request(str(exc)) from exc


@router.get(
    "/{task_id}",
    response_model=McpTraceDetail,
    response_model_exclude_none=True,
)
def get_mcp_trace(task_id: int, request: Request) -> McpTraceDetail:
    try:
        return _service(request).get_trace(task_id)
    except McpTraceServiceError as exc:
        raise _bad_request(str(exc)) from exc
