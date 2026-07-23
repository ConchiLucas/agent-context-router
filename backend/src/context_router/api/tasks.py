from fastapi import APIRouter, HTTPException, Query, Request, status

from context_router.repositories.database_call_repository import (
    DatabaseCallRepositoryError,
    DatabaseCallStore,
)
from context_router.repositories.document_read_repository import (
    DocumentReadRepositoryError,
    DocumentReadStore,
)
from context_router.repositories.task_repository import (
    TaskReader,
    TaskRepositoryError,
)
from context_router.schemas.context import (
    ContextDatabaseCallHistoryItem,
    ContextReadHistoryCall,
    ContextReadHistoryItem,
    ContextTaskReadHistory,
    ContextTaskSummary,
)
from context_router.services.project_registry import ProjectRegistry, ProjectRegistryError

router = APIRouter(tags=["tasks"])


def _registry(request: Request) -> ProjectRegistry:
    return request.app.state.project_registry


def _task_repository(request: Request) -> TaskReader:
    return request.app.state.task_repository


def _read_repository(request: Request) -> DocumentReadStore:
    return request.app.state.document_read_repository


def _database_call_repository(request: Request) -> DatabaseCallStore:
    return request.app.state.database_call_repository


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


@router.get(
    "/projects/{project_id}/tasks",
    response_model=list[ContextTaskSummary],
    response_model_exclude_none=True,
)
def list_project_tasks(
    project_id: str,
    request: Request,
    limit: int = Query(default=30, ge=1, le=100),
    include_system: bool = Query(default=False),
) -> list[ContextTaskSummary]:
    try:
        project = _registry(request).get_snapshot(project_id)
        records = _task_repository(request).list_tasks(
            project.project_key,
            limit=limit,
            include_system=include_system,
        )
    except (ProjectRegistryError, TaskRepositoryError) as exc:
        raise _bad_request(str(exc)) from exc

    return [
        ContextTaskSummary(
            task_id=record.id,
            task=record.task,
            cwd=record.cwd,
            agent_name=record.agent_name,
            created_at=record.created_at,
            read_call_count=record.read_call_count,
        )
        for record in records
    ]


@router.get(
    "/tasks/{task_id}/document-reads",
    response_model=ContextTaskReadHistory,
    response_model_exclude_none=True,
)
def get_task_document_reads(task_id: int, request: Request) -> ContextTaskReadHistory:
    try:
        task = _task_repository(request).get_task(task_id)
        calls = _read_repository(request).list_read_calls(task_id)
        database_calls = _database_call_repository(request).list_calls(task_id)
    except (
        TaskRepositoryError,
        DocumentReadRepositoryError,
        DatabaseCallRepositoryError,
    ) as exc:
        raise _bad_request(str(exc)) from exc

    return ContextTaskReadHistory(
        task_id=task.id,
        task=task.task,
        project_name=task.project_name,
        agent_name=task.agent_name,
        created_at=task.created_at,
        calls=[
            ContextReadHistoryCall(
                read_call_id=call.id,
                created_at=call.created_at,
                documents=[
                    ContextReadHistoryItem(
                        position=item.position,
                        document_id=item.document_id,
                        path=item.document_path,
                        section=item.requested_section,
                        status=item.status,
                        error_code=item.error_code,
                    )
                    for item in call.items
                ],
            )
            for call in calls
        ],
        database_calls=[
            ContextDatabaseCallHistoryItem(
                database_call_id=call.id,
                operation=call.operation,
                database=call.database_alias,
                engine=call.engine,
                status=call.status,
                object_type=call.object_type,
                statement_type=call.statement_type,
                duration_ms=call.duration_ms,
                returned_count=call.returned_count,
                result_bytes=call.result_bytes,
                truncated=call.truncated,
                error_code=call.error_code,
                created_at=call.created_at,
            )
            for call in database_calls
        ],
    )
