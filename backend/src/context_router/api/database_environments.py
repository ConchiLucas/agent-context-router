from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response, status

from context_router.repositories.data_source_repository import (
    DataSourceDatabaseRecord,
    DataSourceRecord,
    DataSourceRepositoryError,
    DataSourceStore,
    ProjectDatabaseLinkRecord,
)
from context_router.repositories.database_environment_repository import (
    DatabaseEnvironmentMappingRecord,
    DatabaseEnvironmentMappingWrite,
    DatabaseEnvironmentRepositoryError,
    DatabaseEnvironmentStore,
    EnvironmentDatabaseTargetWrite,
)
from context_router.repositories.workspace_repository import (
    WorkspaceRepositoryError,
    WorkspaceStore,
)
from context_router.schemas.database_environments import (
    DatabaseEnvironmentCandidates,
    DatabaseEnvironmentMappingCounts,
    DatabaseEnvironmentMappingSummary,
    DatabaseEnvironmentMappingsUpdate,
    DatabaseEnvironmentSwitchUpdate,
    DatabaseEnvironmentTargetPair,
    DatabaseEnvironmentTargetSummary,
    EnvironmentJsonPair,
    ProjectDatabaseEnvironmentMappings,
    WorkspaceDatabaseEnvironmentMappings,
    WorkspaceEnvironmentConfig,
    WorkspaceEnvironmentConfigUpdate,
    WorkspaceEnvironmentDatabaseTargetsUpdate,
    WorkspaceEnvironmentList,
    WorkspaceEnvironmentOption,
    WorkspaceEnvironmentUpsert,
)
from context_router.services.project_registry import ProjectRegistry

router = APIRouter(prefix="/workspaces", tags=["database-environments"])
_INVALID_ALIAS_CHARACTERS = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class _TargetContext:
    project_id: str
    target: DatabaseEnvironmentTargetSummary


@dataclass(frozen=True, slots=True)
class _WorkspaceCatalog:
    projects: dict[str, tuple[str, str]]
    targets: dict[str, _TargetContext]
    candidates: dict[str, dict[str, list[DatabaseEnvironmentTargetSummary]]]


def _environment_store(request: Request) -> DatabaseEnvironmentStore:
    return request.app.state.database_environment_repository


def _data_source_store(request: Request) -> DataSourceStore:
    return request.app.state.data_source_repository


def _workspace_store(request: Request) -> WorkspaceStore:
    return request.app.state.workspace_repository


def _registry(request: Request) -> ProjectRegistry:
    return request.app.state.project_registry


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, DatabaseEnvironmentRepositoryError):
        if exc.code == "database_environment_revision_conflict":
            return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
        if exc.code == "database_mapping_not_found":
            return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get(
    "/{workspace_id}/environments",
    response_model=WorkspaceEnvironmentList,
)
def list_workspace_environments(
    workspace_id: str,
    request: Request,
    response: Response,
) -> WorkspaceEnvironmentList:
    response.headers["Cache-Control"] = "no-store"
    try:
        _workspace_store(request).get_workspace(workspace_id)
        records = _environment_store(request).list_environments(workspace_id)
    except (DatabaseEnvironmentRepositoryError, WorkspaceRepositoryError) as exc:
        raise _http_error(exc) from exc
    return WorkspaceEnvironmentList(
        workspace_id=workspace_id,
        default_environment="local",
        environments=[
            WorkspaceEnvironmentOption(
                key=record.key,
                display_name=record.display_name,
                is_default=record.is_default,
                sort_order=record.sort_order,
            )
            for record in records
        ],
    )


@router.put(
    "/{workspace_id}/environments/{environment}",
    response_model=WorkspaceEnvironmentOption,
)
def upsert_workspace_environment(
    workspace_id: str,
    environment: str,
    payload: WorkspaceEnvironmentUpsert,
    request: Request,
) -> WorkspaceEnvironmentOption:
    try:
        _workspace_store(request).get_workspace(workspace_id)
        record = _environment_store(request).upsert_environment(
            workspace_id=workspace_id,
            environment=environment,
            display_name=payload.display_name,
            sort_order=payload.sort_order,
        )
    except (DatabaseEnvironmentRepositoryError, WorkspaceRepositoryError) as exc:
        raise _http_error(exc) from exc
    return WorkspaceEnvironmentOption(
        key=record.key,
        display_name=record.display_name,
        is_default=record.is_default,
        sort_order=record.sort_order,
    )


@router.delete(
    "/{workspace_id}/environments/{environment}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_workspace_environment(
    workspace_id: str,
    environment: str,
    request: Request,
) -> Response:
    try:
        _workspace_store(request).get_workspace(workspace_id)
        _environment_store(request).delete_environment(
            workspace_id=workspace_id,
            environment=environment,
        )
    except (DatabaseEnvironmentRepositoryError, WorkspaceRepositoryError) as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/{workspace_id}/environments/{environment}/database-mappings",
    status_code=status.HTTP_204_NO_CONTENT,
)
def replace_workspace_environment_database_mappings(
    workspace_id: str,
    environment: str,
    payload: WorkspaceEnvironmentDatabaseTargetsUpdate,
    request: Request,
) -> Response:
    try:
        _workspace_store(request).get_workspace(workspace_id)
        _environment_store(request).replace_environment_targets(
            workspace_id=workspace_id,
            environment=environment,
            targets=[
                EnvironmentDatabaseTargetWrite(
                    id=item.id or uuid4().hex,
                    workspace_id=workspace_id,
                    project_id=item.project_id,
                    logical_name=item.logical_name,
                    mcp_alias=item.mcp_alias,
                    link_id=item.link_id,
                )
                for item in payload.targets
            ],
        )
    except (DatabaseEnvironmentRepositoryError, WorkspaceRepositoryError) as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{workspace_id}/database-environment-mappings",
    response_model=WorkspaceDatabaseEnvironmentMappings,
)
def get_database_environment_mappings(
    workspace_id: str,
    request: Request,
) -> WorkspaceDatabaseEnvironmentMappings:
    try:
        return _build_response(request, workspace_id)
    except (
        DataSourceRepositoryError,
        DatabaseEnvironmentRepositoryError,
        WorkspaceRepositoryError,
    ) as exc:
        raise _http_error(exc) from exc


@router.put(
    "/{workspace_id}/database-environment-mappings",
    response_model=WorkspaceDatabaseEnvironmentMappings,
)
def replace_database_environment_mappings(
    workspace_id: str,
    payload: DatabaseEnvironmentMappingsUpdate,
    request: Request,
) -> WorkspaceDatabaseEnvironmentMappings:
    try:
        catalog = _workspace_catalog(request, workspace_id)
        mappings: list[DatabaseEnvironmentMappingWrite] = []
        for item in payload.mappings:
            if item.targets.test is None or item.targets.uat is None:
                raise DatabaseEnvironmentRepositoryError(
                    "每条环境映射必须同时选择 Test 和 UAT 数据库"
                )
            mappings.append(
                DatabaseEnvironmentMappingWrite(
                    id=item.id or uuid4().hex,
                    workspace_id=workspace_id,
                    project_id=item.project_id,
                    logical_name=item.logical_name,
                    mcp_alias=item.mcp_alias,
                    test_link_id=item.targets.test,
                    uat_link_id=item.targets.uat,
                )
            )
        _validate_against_catalog(catalog, mappings)
        _environment_store(request).replace_mappings(
            workspace_id=workspace_id,
            expected_revision=payload.expected_revision,
            mappings=mappings,
        )
        return _build_response(request, workspace_id)
    except (
        DataSourceRepositoryError,
        DatabaseEnvironmentRepositoryError,
        WorkspaceRepositoryError,
    ) as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/{workspace_id}/database-environment",
    response_model=WorkspaceDatabaseEnvironmentMappings,
)
def switch_database_environment(
    workspace_id: str,
    payload: DatabaseEnvironmentSwitchUpdate,
    request: Request,
) -> WorkspaceDatabaseEnvironmentMappings:
    try:
        catalog = _workspace_catalog(request, workspace_id)
        store = _environment_store(request)
        records = store.list_mappings(workspace_id)
        if records:
            _validate_against_catalog(
                catalog,
                [_mapping_write(record) for record in records],
            )
        store.switch_environment(
            workspace_id=workspace_id,
            environment=payload.environment,
            expected_revision=payload.expected_revision,
        )
        return _build_response(request, workspace_id)
    except (
        DataSourceRepositoryError,
        DatabaseEnvironmentRepositoryError,
        WorkspaceRepositoryError,
    ) as exc:
        raise _http_error(exc) from exc


@router.get(
    "/{workspace_id}/environment-config",
    response_model=WorkspaceEnvironmentConfig,
)
def get_workspace_environment_config(
    workspace_id: str,
    request: Request,
    response: Response,
) -> WorkspaceEnvironmentConfig:
    try:
        response.headers["Cache-Control"] = "no-store"
        _workspace_store(request).get_workspace(workspace_id)
        return _build_environment_config_response(request, workspace_id)
    except (
        DatabaseEnvironmentRepositoryError,
        WorkspaceRepositoryError,
    ) as exc:
        raise _http_error(exc) from exc


@router.put(
    "/{workspace_id}/environment-config",
    response_model=WorkspaceEnvironmentConfig,
)
def replace_workspace_environment_config(
    workspace_id: str,
    payload: WorkspaceEnvironmentConfigUpdate,
    request: Request,
    response: Response,
) -> WorkspaceEnvironmentConfig:
    try:
        response.headers["Cache-Control"] = "no-store"
        _workspace_store(request).get_workspace(workspace_id)
        _environment_store(request).replace_environment_payloads(
            workspace_id=workspace_id,
            expected_revision=payload.expected_revision,
            environments={
                "test": payload.environments.test,
                "uat": payload.environments.uat,
            },
        )
        return _build_environment_config_response(request, workspace_id)
    except (
        DatabaseEnvironmentRepositoryError,
        WorkspaceRepositoryError,
    ) as exc:
        raise _http_error(exc) from exc


def _build_environment_config_response(
    request: Request,
    workspace_id: str,
) -> WorkspaceEnvironmentConfig:
    store = _environment_store(request)
    snapshot = store.get_environment_snapshot(workspace_id)
    config = snapshot.config
    values = snapshot.payloads.environments
    active_config = (
        values.get(config.active_environment)
        if snapshot.payloads.configured
        and snapshot.selector_configured
        and config.active_environment is not None
        else None
    )
    return WorkspaceEnvironmentConfig(
        workspace_id=workspace_id,
        configured=snapshot.payloads.configured,
        active_environment=(config.active_environment if snapshot.selector_configured else None),
        revision=config.revision,
        environments=EnvironmentJsonPair(
            test=values.get("test", {}),
            uat=values.get("uat", {}),
        ),
        active_config=active_config,
    )


def _build_response(
    request: Request,
    workspace_id: str,
) -> WorkspaceDatabaseEnvironmentMappings:
    catalog = _workspace_catalog(request, workspace_id)
    environment_store = _environment_store(request)
    config = environment_store.get_active_config(workspace_id)
    records = environment_store.list_mappings(workspace_id)
    records_by_project: dict[str, list[DatabaseEnvironmentMappingRecord]] = defaultdict(list)
    for record in records:
        records_by_project[record.project_id].append(record)
    mappings_configured = bool(records)

    project_results: list[ProjectDatabaseEnvironmentMappings] = []
    suggested_aliases: set[str] = set()
    for project_id, (project_name, project_kind) in catalog.projects.items():
        candidates = catalog.candidates.get(
            project_id,
            {"test": [], "uat": []},
        )
        if records_by_project.get(project_id):
            mappings = [
                _saved_mapping_summary(record, catalog)
                for record in records_by_project.get(project_id, [])
            ]
        else:
            mappings = _suggested_mapping_summaries(
                project_id=project_id,
                project_name=project_name,
                candidates=candidates,
                used_aliases=suggested_aliases,
            )
        if not mappings and not candidates["test"] and not candidates["uat"]:
            continue
        project_results.append(
            ProjectDatabaseEnvironmentMappings(
                project_id=project_id,
                project_name=project_name,
                project_kind=project_kind,  # type: ignore[arg-type]
                mappings=mappings,
                candidates=DatabaseEnvironmentCandidates(
                    test=candidates["test"],
                    uat=candidates["uat"],
                ),
            )
        )

    all_mappings = [mapping for project in project_results for mapping in project.mappings]
    complete_count = sum(
        mapping.targets.test is not None
        and mapping.targets.uat is not None
        and not mapping.issues
        or mapping.status == "suggested"
        and not mapping.issues
        for mapping in all_mappings
    )
    return WorkspaceDatabaseEnvironmentMappings(
        workspace_id=workspace_id,
        configured=mappings_configured,
        active_environment=config.active_environment,
        revision=config.revision,
        summary=DatabaseEnvironmentMappingCounts(
            mapping_count=len(all_mappings),
            complete_count=complete_count,
            issue_count=sum(bool(mapping.issues) for mapping in all_mappings),
        ),
        projects=project_results,
    )


def _workspace_catalog(request: Request, workspace_id: str) -> _WorkspaceCatalog:
    _workspace_store(request).get_workspace(workspace_id)
    projects = {
        project.id: (project.name, project.project_kind)
        for project in _registry(request).list_workspace_projects(workspace_id)
        if project.project_kind == "backend"
    }
    store = _data_source_store(request)
    sources = {source.id: source for source in store.list_data_sources()}
    databases = {
        database.id: database
        for source in sources.values()
        for database in store.list_databases(source.id)
    }
    targets: dict[str, _TargetContext] = {}
    candidates: dict[str, dict[str, list[DatabaseEnvironmentTargetSummary]]] = {}
    for project_id in projects:
        project_candidates: dict[str, list[DatabaseEnvironmentTargetSummary]] = {
            "test": [],
            "uat": [],
        }
        for link in store.list_links(project_id=project_id):
            database = databases.get(link.database_id)
            source = sources.get(link.data_source_id)
            if database is None or source is None:
                continue
            target = _target_summary(link, database, source)
            targets[link.id] = _TargetContext(project_id=project_id, target=target)
            environment = _database_environment(database.remote_name)
            if environment is not None:
                project_candidates[environment].append(target)
        for values in project_candidates.values():
            values.sort(key=lambda item: (item.database_name.casefold(), item.link_id))
        candidates[project_id] = project_candidates
    return _WorkspaceCatalog(projects=projects, targets=targets, candidates=candidates)


def _target_summary(
    link: ProjectDatabaseLinkRecord,
    database: DataSourceDatabaseRecord,
    source: DataSourceRecord,
) -> DatabaseEnvironmentTargetSummary:
    return DatabaseEnvironmentTargetSummary(
        link_id=link.id,
        database_id=link.database_id,
        database_name=database.remote_name,
        database_display_name=database.display_name,
        data_source_id=link.data_source_id,
        data_source_name=link.data_source_name,
        engine=link.engine,
        namespace_type=database.namespace_type,
        mcp_alias=link.mcp_alias,
        available=database.available,
        readonly=link.readonly,
        system_database=database.system_database,
    )


def _saved_mapping_summary(
    record: DatabaseEnvironmentMappingRecord,
    catalog: _WorkspaceCatalog,
) -> DatabaseEnvironmentMappingSummary:
    test = _target_from_catalog(catalog, record.project_id, record.targets.get("test"))
    uat = _target_from_catalog(catalog, record.project_id, record.targets.get("uat"))
    issues = _mapping_issues(test, uat)
    return DatabaseEnvironmentMappingSummary(
        id=record.id,
        logical_name=record.logical_name,
        mcp_alias=record.mcp_alias,
        status="complete" if not issues else "invalid",
        targets=DatabaseEnvironmentTargetPair(test=test, uat=uat),
        suggested_targets=DatabaseEnvironmentTargetPair(test=test, uat=uat),
        issues=issues,
    )


def _suggested_mapping_summaries(
    *,
    project_id: str,
    project_name: str,
    candidates: dict[str, list[DatabaseEnvironmentTargetSummary]],
    used_aliases: set[str],
) -> list[DatabaseEnvironmentMappingSummary]:
    grouped: dict[str, dict[str, list[DatabaseEnvironmentTargetSummary]]] = defaultdict(
        lambda: {"test": [], "uat": []}
    )
    names: dict[str, str] = {}
    for environment in ("test", "uat"):
        for target in candidates[environment]:
            suffix = _database_suffix(target.database_name, environment)
            if suffix is None:
                continue
            key = suffix.casefold()
            names.setdefault(key, suffix)
            grouped[key][environment].append(target)

    results: list[DatabaseEnvironmentMappingSummary] = []
    for key in sorted(grouped):
        matches = grouped[key]
        test = matches["test"][0] if len(matches["test"]) == 1 else None
        uat = matches["uat"][0] if len(matches["uat"]) == 1 else None
        issues: list[str] = []
        if len(matches["test"]) != 1:
            issues.append(
                "没有唯一的 Test 数据库" if not matches["test"] else "存在多个同后缀 Test 数据库"
            )
        if len(matches["uat"]) != 1:
            issues.append(
                "没有唯一的 UAT 数据库" if not matches["uat"] else "存在多个同后缀 UAT 数据库"
            )
        issues.extend(_mapping_issues(test, uat))
        alias = _unique_alias(
            _generated_alias(project_name, names[key]),
            used_aliases,
        )
        used_aliases.add(alias.casefold())
        results.append(
            DatabaseEnvironmentMappingSummary(
                id=None,
                logical_name=names[key],
                mcp_alias=alias,
                status="suggested" if not issues else "incomplete",
                targets=DatabaseEnvironmentTargetPair(),
                suggested_targets=DatabaseEnvironmentTargetPair(test=test, uat=uat),
                issues=list(dict.fromkeys(issues)),
            )
        )
    return results


def _mapping_issues(
    test: DatabaseEnvironmentTargetSummary | None,
    uat: DatabaseEnvironmentTargetSummary | None,
) -> list[str]:
    issues: list[str] = []
    if test is None:
        issues.append("缺少 Test 数据库")
    if uat is None:
        issues.append("缺少 UAT 数据库")
    for label, target in (("Test", test), ("UAT", uat)):
        if target is None:
            continue
        if not target.readonly:
            issues.append(f"{label} 数据库授权不是只读")
        if not target.available or target.system_database:
            issues.append(f"{label} 数据库当前不可用")
    if test is not None and uat is not None:
        if test.engine != uat.engine:
            issues.append("Test 与 UAT 数据库类型不一致")
        if test.namespace_type != uat.namespace_type:
            issues.append("Test 与 UAT 数据库命名空间类型不一致")
    return list(dict.fromkeys(issues))


def _validate_against_catalog(
    catalog: _WorkspaceCatalog,
    mappings: list[DatabaseEnvironmentMappingWrite],
) -> None:
    used: dict[str, set[str]] = {"test": set(), "uat": set()}
    for mapping in mappings:
        project = catalog.projects.get(mapping.project_id)
        if project is None or project[1] != "backend":
            raise DatabaseEnvironmentRepositoryError("仅后端项目可以配置数据库环境映射")
        test = _required_target(catalog, mapping.project_id, mapping.test_link_id)
        uat = _required_target(catalog, mapping.project_id, mapping.uat_link_id)
        if mapping.test_link_id in used["test"] or mapping.uat_link_id in used["uat"]:
            raise DatabaseEnvironmentRepositoryError("同一环境不能重复使用数据库授权")
        used["test"].add(mapping.test_link_id)
        used["uat"].add(mapping.uat_link_id)
        issues = _mapping_issues(test, uat)
        if issues:
            raise DatabaseEnvironmentRepositoryError("；".join(issues))


def _required_target(
    catalog: _WorkspaceCatalog,
    project_id: str,
    link_id: str,
) -> DatabaseEnvironmentTargetSummary:
    context = catalog.targets.get(link_id)
    if context is None:
        raise DatabaseEnvironmentRepositoryError("环境映射包含不存在的数据库授权")
    if context.project_id != project_id:
        raise DatabaseEnvironmentRepositoryError("数据库授权不属于当前项目")
    return context.target


def _target_from_catalog(
    catalog: _WorkspaceCatalog,
    project_id: str,
    link_id: str | None,
) -> DatabaseEnvironmentTargetSummary | None:
    if link_id is None:
        return None
    context = catalog.targets.get(link_id)
    if context is None or context.project_id != project_id:
        return None
    return context.target


def _mapping_write(record: DatabaseEnvironmentMappingRecord) -> DatabaseEnvironmentMappingWrite:
    test = record.targets.get("test")
    uat = record.targets.get("uat")
    if test is None or uat is None:
        raise DatabaseEnvironmentRepositoryError("数据库环境映射不完整，无法切换")
    return DatabaseEnvironmentMappingWrite(
        id=record.id,
        workspace_id=record.workspace_id,
        project_id=record.project_id,
        logical_name=record.logical_name,
        mcp_alias=record.mcp_alias,
        test_link_id=test,
        uat_link_id=uat,
    )


def _database_environment(database_name: str) -> str | None:
    normalized = database_name.casefold()
    for environment in ("test", "uat"):
        if normalized.startswith(f"{environment}_") and len(normalized) > len(environment) + 1:
            return environment
    return None


def _database_suffix(database_name: str, environment: str) -> str | None:
    prefix = f"{environment}_"
    if not database_name.casefold().startswith(prefix):
        return None
    suffix = database_name[len(prefix) :]
    return suffix or None


def _generated_alias(project_name: str, logical_name: str) -> str:
    project_slug = _alias_slug(project_name) or "project"
    logical_slug = _alias_slug(logical_name) or "db"
    project_tail = project_slug.rsplit("_", 1)[-1]
    suffix = "db" if project_tail == logical_slug else logical_slug
    alias = f"{project_slug}_{suffix}"
    if not alias[0].isalpha():
        alias = f"db_{alias}"
    return alias[:64].rstrip("_")


def _alias_slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    return _INVALID_ALIAS_CHARACTERS.sub("_", ascii_value).strip("_")


def _unique_alias(base: str, used_aliases: set[str]) -> str:
    if base.casefold() not in used_aliases:
        return base
    counter = 2
    while True:
        suffix = f"_{counter}"
        candidate = f"{base[: 64 - len(suffix)].rstrip('_')}{suffix}"
        if candidate.casefold() not in used_aliases:
            return candidate
        counter += 1
