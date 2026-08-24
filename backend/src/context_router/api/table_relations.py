from __future__ import annotations

import logging
from time import perf_counter_ns
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
from context_router.schemas.relation_records import (
    RelationRecordSearchInput,
    RelationRecordSearchResult,
)
from context_router.schemas.table_relations import (
    TableRelationDetail,
    TableRelationStatus,
    TableRelationTableDetail,
    TableRelationTableList,
    TableRelationTableUpdates,
    TableRelationTableWrites,
)
from context_router.services.relation_record_explorer import (
    RelationRecordExplorerError,
    RelationRecordExplorerService,
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
logger = logging.getLogger(__name__)
_WORKSPACE_MISSING = "工作空间不存在"


def _workspace_store(request: Request) -> WorkspaceStore:
    return request.app.state.workspace_repository


def _reader(request: Request) -> TableRelationReader:
    return request.app.state.table_relation_repository


def _service(request: Request) -> TableRelationQueryService:
    return TableRelationQueryService(reader=_reader(request))


def _context_service(request: Request) -> TableRelationContextService:
    return request.app.state.table_relation_context_service


def _record_service(request: Request) -> RelationRecordExplorerService:
    return RelationRecordExplorerService(
        relation_query=_service(request),
        database_access=request.app.state.database_access_service,
        connector_manager=request.app.state.connector_manager,
        result_formatter=request.app.state.database_result_formatter,
    )


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


@router.post(
    "/{workspace_id}/relation-records/search",
    response_model=RelationRecordSearchResult,
)
def search_relation_records(
    workspace_id: str,
    payload: RelationRecordSearchInput,
    request: Request,
) -> RelationRecordSearchResult:
    """Search only relation-key columns and return direct related table rows."""
    started_ns = perf_counter_ns()
    try:
        _require_workspace(request, workspace_id, payload.environment)
        result = _record_service(request).search(workspace_id=workspace_id, request=payload)
        if payload.ai_query_record_id and payload.page == 1 and payload.edge_id is None:
            try:
                request.app.state.ai_data_visualization_service.record_execution(
                    record_id=payload.ai_query_record_id,
                    workspace_id=workspace_id,
                    environment=payload.environment,
                    succeeded=True,
                    result_card_count=len(result.cards),
                    result_row_count=sum(card.page.total_rows for card in result.cards),
                    duration_ms=max(0, (perf_counter_ns() - started_ns) // 1_000_000),
                )
            except Exception:
                logger.warning("Unable to persist AI data query execution summary", exc_info=True)
        return result
    except RelationRecordExplorerError as exc:
        if payload.ai_query_record_id and payload.page == 1 and payload.edge_id is None:
            try:
                request.app.state.ai_data_visualization_service.record_execution(
                    record_id=payload.ai_query_record_id,
                    workspace_id=workspace_id,
                    environment=payload.environment,
                    succeeded=False,
                    result_card_count=None,
                    result_row_count=None,
                    duration_ms=max(0, (perf_counter_ns() - started_ns) // 1_000_000),
                    error_summary=str(exc),
                )
            except Exception:
                logger.warning("Unable to persist failed AI data query summary", exc_info=True)
        code = (
            status.HTTP_404_NOT_FOUND
            if exc.code in {"relation_not_found"}
            else status.HTTP_400_BAD_REQUEST
        )
        if exc.code in {"connection_failed", "query_timeout"}:
            code = status.HTTP_503_SERVICE_UNAVAILABLE
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    except (
        TableRelationNotFoundError,
        TableRelationRepositoryError,
        WorkspaceRepositoryError,
    ) as exc:
        raise _http_error(exc) from exc


@router.get("/{workspace_id}/table-relations/status", response_model=TableRelationStatus)
def get_table_relation_status(
    workspace_id: str,
    request: Request,
) -> TableRelationStatus:
    try:
        _require_workspace(request, workspace_id, None)
        return _service(request).get_status(workspace_id)
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
    database_key: str | None = None,
    only_related: bool = True,
    search: str | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> TableRelationTableList:
    try:
        _require_workspace(request, workspace_id, None)
        return _service(request).list_tables(
            workspace_id,
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
) -> TableRelationTableDetail:
    try:
        _require_workspace(request, workspace_id, None)
        return _service(request).get_table_detail(
            workspace_id,
            database_key=database_key,
            schema_name=schema_name,
            table_name=table_name,
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
) -> TableRelationTableWrites:
    try:
        _require_workspace(request, workspace_id, None)
        return _service(request).get_table_writes(
            workspace_id,
            database_key=database_key,
            schema_name=schema_name,
            table_name=table_name,
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
) -> TableRelationTableUpdates:
    try:
        _require_workspace(request, workspace_id, None)
        return _service(request).get_table_updates(
            workspace_id,
            database_key=database_key,
            schema_name=schema_name,
            table_name=table_name,
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
) -> TableRelationDetail:
    try:
        _require_workspace(request, workspace_id, None)
        return _service(request).get_relation_detail(
            workspace_id,
            database_key=database_key,
            schema_name=schema_name,
            table_name=table_name,
            edge_id=edge_id,
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
    mode: Literal["default", "full"] = Query(default="default"),
) -> dict[str, object]:
    try:
        _require_workspace(request, workspace_id, None)
        return _context_service(request).read_for_workspace(
            workspace_id=workspace_id,
            database_key=database_key,
            schema_name=schema_name,
            table_name=table_name,
            mode=mode,
        )
    except TableRelationContextError as exc:
        raise _context_http_error(exc) from exc
    except WorkspaceRepositoryError as exc:
        raise _http_error(exc) from exc
