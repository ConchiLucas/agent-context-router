from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, status

from context_router.repositories.database_environment_repository import (
    DatabaseEnvironmentStore,
)
from context_router.repositories.table_relation_repository import (
    TableRelationReader,
    TableRelationRepositoryError,
)
from context_router.repositories.workspace_repository import (
    WorkspaceRepositoryError,
    WorkspaceStore,
)
from context_router.schemas.table_relations import (
    TableRelationDetail,
    TableRelationEnvironment,
    TableRelationStatus,
    TableRelationTableDetail,
    TableRelationTableList,
    TableRelationTableUpdates,
    TableRelationTableWrites,
)
from context_router.services.table_relation_context import (
    TableRelationContextError,
    TableRelationContextService,
)
from context_router.services.table_relation_query import (
    TableRelationNotFoundError,
    TableRelationQueryService,
)

router = APIRouter(prefix="/workspaces", tags=["table-relations"])
_WORKSPACE_MISSING = "工作空间不存在"


def _workspace_store(request: Request) -> WorkspaceStore:
    return request.app.state.workspace_repository


def _reader(request: Request) -> TableRelationReader:
    return request.app.state.table_relation_repository


def _service(request: Request) -> TableRelationQueryService:
    return TableRelationQueryService(reader=_reader(request))


def _context_service(request: Request) -> TableRelationContextService:
    return request.app.state.table_relation_context_service


def _context_http_error(exc: TableRelationContextError) -> HTTPException:
    if exc.code in {"task_not_found", "workspace_not_found", "table_relation_table_not_found"}:
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if exc.code == "table_relation_generation_missing":
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _require_workspace(
    request: Request,
    workspace_id: str,
    environment: str | None,
) -> None:
    _workspace_store(request).get_workspace(workspace_id)
    if environment is None:
        return
    environments: DatabaseEnvironmentStore | None = getattr(
        request.app.state,
        "database_environment_repository",
        None,
    )
    if environments is None:
        return
    if not environments.has_environment(workspace_id, environment):
        raise TableRelationRepositoryError("工作空间没有配置所选环境")


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, TableRelationNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    # WorkspaceRepositoryError carries no error code, so a missing workspace is
    # only distinguishable from a read failure by its message.
    if isinstance(exc, WorkspaceRepositoryError) and str(exc) == _WORKSPACE_MISSING:
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, TableRelationRepositoryError) and exc.code == "table_relation_unavailable":
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/{workspace_id}/table-relations/status", response_model=TableRelationStatus)
def get_table_relation_status(
    workspace_id: str,
    request: Request,
    environment: TableRelationEnvironment | None = None,
) -> TableRelationStatus:
    try:
        _require_workspace(request, workspace_id, environment)
        return _service(request).get_status(workspace_id, environment=environment)
    except (
        TableRelationNotFoundError,
        TableRelationRepositoryError,
        WorkspaceRepositoryError,
    ) as exc:
        raise _http_error(exc) from exc


@router.get(
    "/{workspace_id}/table-relations/tables",
    response_model=TableRelationTableList,
)
def list_table_relation_tables(
    workspace_id: str,
    request: Request,
    environment: TableRelationEnvironment | None = None,
    database_key: str | None = None,
    only_related: bool = True,
    search: str | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> TableRelationTableList:
    try:
        _require_workspace(request, workspace_id, environment)
        return _service(request).list_tables(
            workspace_id,
            environment=environment,
            database_key=database_key,
            only_related=only_related,
            search=search,
            limit=limit,
            offset=offset,
        )
    except (
        TableRelationNotFoundError,
        TableRelationRepositoryError,
        WorkspaceRepositoryError,
    ) as exc:
        raise _http_error(exc) from exc


@router.get(
    "/{workspace_id}/table-relations/table",
    response_model=TableRelationTableDetail,
)
def get_table_relation_detail(
    workspace_id: str,
    request: Request,
    database_key: str = Query(min_length=1, max_length=64),
    schema_name: str = Query(min_length=1, max_length=255),
    table_name: str = Query(min_length=1, max_length=255),
    environment: TableRelationEnvironment | None = None,
) -> TableRelationTableDetail:
    try:
        _require_workspace(request, workspace_id, environment)
        return _service(request).get_table_detail(
            workspace_id,
            database_key=database_key,
            schema_name=schema_name,
            table_name=table_name,
            environment=environment,
        )
    except (
        TableRelationNotFoundError,
        TableRelationRepositoryError,
        WorkspaceRepositoryError,
    ) as exc:
        raise _http_error(exc) from exc


# Fetched per table rather than folded into the table's relation list: persist
# snippets are only opened from the header button, and a table with no recorded
# writes should not pay for an empty payload on every row click.
@router.get(
    "/{workspace_id}/table-relations/table/writes",
    response_model=TableRelationTableWrites,
)
def get_table_relation_writes(
    workspace_id: str,
    request: Request,
    database_key: str = Query(min_length=1, max_length=64),
    schema_name: str = Query(min_length=1, max_length=255),
    table_name: str = Query(min_length=1, max_length=255),
    environment: TableRelationEnvironment | None = None,
) -> TableRelationTableWrites:
    try:
        _require_workspace(request, workspace_id, environment)
        return _service(request).get_table_writes(
            workspace_id,
            database_key=database_key,
            schema_name=schema_name,
            table_name=table_name,
            environment=environment,
        )
    except (
        TableRelationNotFoundError,
        TableRelationRepositoryError,
        WorkspaceRepositoryError,
    ) as exc:
        raise _http_error(exc) from exc


# Fetched per table rather than folded into the table's relation list: persist
# snippets are only opened from the header button, and a table with no recorded
# updates should not pay for an empty payload on every row click.
@router.get(
    "/{workspace_id}/table-relations/table/updates",
    response_model=TableRelationTableUpdates,
)
def get_table_relation_updates(
    workspace_id: str,
    request: Request,
    database_key: str = Query(min_length=1, max_length=64),
    schema_name: str = Query(min_length=1, max_length=255),
    table_name: str = Query(min_length=1, max_length=255),
    environment: TableRelationEnvironment | None = None,
) -> TableRelationTableUpdates:
    try:
        _require_workspace(request, workspace_id, environment)
        return _service(request).get_table_updates(
            workspace_id,
            database_key=database_key,
            schema_name=schema_name,
            table_name=table_name,
            environment=environment,
        )
    except (
        TableRelationNotFoundError,
        TableRelationRepositoryError,
        WorkspaceRepositoryError,
    ) as exc:
        raise _http_error(exc) from exc


# Fetched per relation rather than folded into the table response: the evidence
# behind one verdict is far bigger than the row that summarises it, and a table
# with a dozen relations would be paying for twelve probes to render none of them.
@router.get(
    "/{workspace_id}/table-relations/relation",
    response_model=TableRelationDetail,
)
def get_table_relation_evidence(
    workspace_id: str,
    request: Request,
    edge_id: str = Query(min_length=1, max_length=32),
    database_key: str = Query(min_length=1, max_length=64),
    schema_name: str = Query(min_length=1, max_length=255),
    table_name: str = Query(min_length=1, max_length=255),
    environment: TableRelationEnvironment | None = None,
) -> TableRelationDetail:
    try:
        _require_workspace(request, workspace_id, environment)
        return _service(request).get_relation_detail(
            workspace_id,
            database_key=database_key,
            schema_name=schema_name,
            table_name=table_name,
            edge_id=edge_id,
            environment=environment,
        )
    except (
        TableRelationNotFoundError,
        TableRelationRepositoryError,
        WorkspaceRepositoryError,
    ) as exc:
        raise _http_error(exc) from exc


@router.get("/{workspace_id}/table-relations/table/mcp")
def get_table_relation_mcp_preview(
    workspace_id: str,
    request: Request,
    database_key: str = Query(min_length=1, max_length=64),
    schema_name: str = Query(min_length=1, max_length=255),
    table_name: str = Query(min_length=1, max_length=255),
    environment: TableRelationEnvironment | None = None,
    mode: Literal["default", "full"] = Query(default="default"),
) -> dict[str, object]:
    try:
        _require_workspace(request, workspace_id, environment)
        return _context_service(request).read_for_workspace(
            workspace_id=workspace_id,
            database_key=database_key,
            schema_name=schema_name,
            table_name=table_name,
            environment=environment,
            mode=mode,
        )
    except TableRelationContextError as exc:
        raise _context_http_error(exc) from exc
    except WorkspaceRepositoryError as exc:
        raise _http_error(exc) from exc
