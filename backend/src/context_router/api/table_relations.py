from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status

from context_router.schemas.table_relations import (
    TableRelationAutomaticWhitelistFileContent,
    TableRelationAutomaticWhitelistFileList,
    TableRelationAutomaticWhitelistRuleCode,
    TableRelationBuildStatus,
    TableRelationContextResult,
    TableRelationDefaultDatabaseConfiguration,
    TableRelationDefaultDatabaseUpdate,
    TableRelationSqlWhitelistConfiguration,
    TableRelationSqlWhitelistUpdate,
    TableRelationTableList,
    TableRelationWarningList,
)
from context_router.services.table_relations import (
    TableRelationService,
    TableRelationServiceError,
)

router = APIRouter(prefix="/workspaces/{workspace_id}/table-relations", tags=["table-relations"])


def _service(request: Request) -> TableRelationService:
    return request.app.state.table_relation_service


@router.get("/status", response_model=TableRelationBuildStatus)
def get_table_relation_status(
    workspace_id: str,
    request: Request,
) -> TableRelationBuildStatus:
    return _call(lambda: _service(request).get_status(workspace_id))


@router.get(
    "/default-databases",
    response_model=TableRelationDefaultDatabaseConfiguration,
)
def get_table_relation_default_databases(
    workspace_id: str,
    request: Request,
) -> TableRelationDefaultDatabaseConfiguration:
    return _call(lambda: _service(request).get_default_database_configuration(workspace_id))


@router.put(
    "/default-databases",
    response_model=TableRelationDefaultDatabaseConfiguration,
)
def replace_table_relation_default_databases(
    workspace_id: str,
    payload: TableRelationDefaultDatabaseUpdate,
    request: Request,
) -> TableRelationDefaultDatabaseConfiguration:
    return _call(
        lambda: _service(request).replace_default_databases(
            workspace_id=workspace_id,
            expected_revision=payload.expected_revision,
            defaults=[(item.project_id, item.project_database_id) for item in payload.defaults],
        )
    )


@router.post("/rebuild", response_model=TableRelationBuildStatus)
def rebuild_table_relations(
    workspace_id: str,
    request: Request,
    failed_only: bool = Query(default=False),
) -> TableRelationBuildStatus:
    return _call(lambda: _service(request).rebuild(workspace_id, failed_only=failed_only))


@router.post(
    "/projects/{project_id}/rebuild",
    response_model=TableRelationBuildStatus,
)
def rebuild_project_table_relations(
    workspace_id: str,
    project_id: str,
    request: Request,
) -> TableRelationBuildStatus:
    return _call(
        lambda: _service(request).rebuild(
            workspace_id,
            project_id=project_id,
        )
    )


@router.get(
    "/automatic-whitelist",
    response_model=TableRelationAutomaticWhitelistFileList,
)
def list_workspace_automatic_whitelist_files(
    workspace_id: str,
    request: Request,
    rule: TableRelationAutomaticWhitelistRuleCode,
    project_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> TableRelationAutomaticWhitelistFileList:
    return _call(
        lambda: _service(request).list_automatic_whitelist_files(
            workspace_id=workspace_id,
            project_id=project_id,
            rule_code=rule,
            limit=limit,
            offset=offset,
        )
    )


@router.get(
    "/automatic-whitelist/file",
    response_model=TableRelationAutomaticWhitelistFileContent,
)
def get_workspace_automatic_whitelist_file_content(
    workspace_id: str,
    request: Request,
    rule: TableRelationAutomaticWhitelistRuleCode,
    project_id: Annotated[str, Query(min_length=1, max_length=64)],
    source_path: Annotated[str, Query(min_length=1, max_length=1000)],
) -> TableRelationAutomaticWhitelistFileContent:
    return _call(
        lambda: _service(request).get_automatic_whitelist_file_content(
            workspace_id=workspace_id,
            project_id=project_id,
            rule_code=rule,
            source_path=source_path,
        )
    )


@router.get(
    "/projects/{project_id}/sql-whitelist",
    response_model=TableRelationSqlWhitelistConfiguration,
)
def get_project_sql_whitelist(
    workspace_id: str,
    project_id: str,
    request: Request,
) -> TableRelationSqlWhitelistConfiguration:
    return _call(lambda: _service(request).get_sql_whitelist(workspace_id, project_id))


@router.put(
    "/projects/{project_id}/sql-whitelist",
    response_model=TableRelationSqlWhitelistConfiguration,
)
def replace_project_sql_whitelist(
    workspace_id: str,
    project_id: str,
    payload: TableRelationSqlWhitelistUpdate,
    request: Request,
) -> TableRelationSqlWhitelistConfiguration:
    return _call(
        lambda: _service(request).replace_sql_whitelist(
            workspace_id=workspace_id,
            project_id=project_id,
            paths=payload.paths,
        )
    )


@router.get(
    "/projects/{project_id}/automatic-whitelist",
    response_model=TableRelationAutomaticWhitelistFileList,
)
def list_project_automatic_whitelist_files(
    workspace_id: str,
    project_id: str,
    request: Request,
    rule: TableRelationAutomaticWhitelistRuleCode,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> TableRelationAutomaticWhitelistFileList:
    return _call(
        lambda: _service(request).list_automatic_whitelist_files(
            workspace_id=workspace_id,
            project_id=project_id,
            rule_code=rule,
            limit=limit,
            offset=offset,
        )
    )


@router.get(
    "/projects/{project_id}/automatic-whitelist/file",
    response_model=TableRelationAutomaticWhitelistFileContent,
)
def get_project_automatic_whitelist_file_content(
    workspace_id: str,
    project_id: str,
    request: Request,
    rule: TableRelationAutomaticWhitelistRuleCode,
    source_path: Annotated[str, Query(min_length=1, max_length=1000)],
) -> TableRelationAutomaticWhitelistFileContent:
    return _call(
        lambda: _service(request).get_automatic_whitelist_file_content(
            workspace_id=workspace_id,
            project_id=project_id,
            rule_code=rule,
            source_path=source_path,
        )
    )


@router.get("/tables", response_model=TableRelationTableList)
def list_table_relation_tables(
    workspace_id: str,
    request: Request,
    q: str = Query(default="", max_length=255),
    limit: int = Query(default=200, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> TableRelationTableList:
    return _call(
        lambda: _service(request).list_tables(
            workspace_id,
            q,
            limit=limit,
            offset=offset,
        )
    )


@router.get("/warnings", response_model=TableRelationWarningList)
def list_table_relation_warnings(
    workspace_id: str,
    request: Request,
    code: str | None = Query(default=None, max_length=64),
    project_id: str | None = Query(default=None, max_length=64),
    disposition: Literal["attention", "expected"] | None = Query(default=None),
    q: str = Query(default="", max_length=255),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> TableRelationWarningList:
    return _call(
        lambda: _service(request).list_warnings(
            workspace_id,
            code=code,
            project_id=project_id,
            disposition=disposition,
            query=q,
            limit=limit,
            offset=offset,
        )
    )


@router.get("/context", response_model=TableRelationContextResult)
def get_table_relation_context(
    workspace_id: str,
    request: Request,
    table: str = Query(min_length=1, max_length=255),
    database_key: str | None = Query(default=None, max_length=64),
    schema: str | None = Query(default=None, max_length=255),
    include_evidence: bool = True,
) -> TableRelationContextResult:
    return _call(
        lambda: _service(request).context_for_workspace(
            workspace_id=workspace_id,
            table=table,
            database_key=database_key,
            schema=schema,
            detail_level="full" if include_evidence else "compact",
        )
    )


def _call[T](operation: Callable[[], T]) -> T:
    try:
        return operation()
    except TableRelationServiceError as exc:
        response_status = (
            status.HTTP_409_CONFLICT
            if exc.code
            in {
                "table_relation_index_not_ready",
                "table_relation_ambiguous_table",
                "table_relation_build_failed",
                "table_relation_default_database_revision_conflict",
            }
            else status.HTTP_404_NOT_FOUND
            if exc.code
            in {
                "table_relation_project_not_found",
                "table_relation_table_not_found",
            }
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(
            status_code=response_status,
            detail=f"{exc.code}: {exc}",
        ) from exc
