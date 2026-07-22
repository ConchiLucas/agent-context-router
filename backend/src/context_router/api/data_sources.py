from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response, status

from context_router.repositories.data_source_repository import (
    DataSourceDatabaseRecord,
    DataSourceRecord,
    DataSourceRepositoryError,
    DataSourceStore,
    ProjectDatabaseLinkRecord,
)
from context_router.schemas.data_sources import (
    DataSourceCreate,
    DataSourceDatabaseCreate,
    DataSourceDatabaseSummary,
    DataSourceDatabaseSyncResult,
    DataSourceDatabaseUpdate,
    DataSourcePasswordReveal,
    DataSourceSummary,
    DataSourceUpdate,
    ProjectDatabaseLinkCreate,
    ProjectDatabaseLinkSummary,
    ProjectDatabaseLinkUpdate,
    ProjectDatabaseOption,
    ProjectDatabaseSelectionUpdate,
    ProjectDataSourceOption,
    ProjectDataSourceOptions,
)
from context_router.services.database_discovery import discover_databases
from context_router.services.project_registry import ProjectRegistry

router = APIRouter(tags=["data-sources"])
_SECRET_KEYS = {"password", "passwd", "secret", "token", "api_key", "private_key"}


def _store(request: Request) -> DataSourceStore:
    return request.app.state.data_source_repository


def _registry(request: Request) -> ProjectRegistry:
    return request.app.state.project_registry


def _http_error(exc: DataSourceRepositoryError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _public_config(config: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in config.items() if key.lower() not in _SECRET_KEYS}


def _merged_config(previous: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(previous)
    for key, value in incoming.items():
        if key.lower() in _SECRET_KEYS and (value is None or value == ""):
            continue
        merged[key] = value
    return merged


def _source_summary(record: DataSourceRecord) -> DataSourceSummary:
    values = {field: getattr(record, field) for field in record.__dataclass_fields__}
    values["connection_config"] = _public_config(record.connection_config)
    return DataSourceSummary(**values)


def _database_summary(record: DataSourceDatabaseRecord) -> DataSourceDatabaseSummary:
    return DataSourceDatabaseSummary(
        **{field: getattr(record, field) for field in record.__dataclass_fields__}
    )


def _link_summary(record: ProjectDatabaseLinkRecord) -> ProjectDatabaseLinkSummary:
    return ProjectDatabaseLinkSummary(
        **{field: getattr(record, field) for field in record.__dataclass_fields__}
    )


def _project_name(request: Request, project_id: str) -> str:
    project = next(
        (item for item in _registry(request).list_projects() if item.id == project_id),
        None,
    )
    if project is None:
        raise DataSourceRepositoryError("项目不存在")
    return project.name


def _project_data_source_options(request: Request, project_id: str) -> ProjectDataSourceOptions:
    project_name = _project_name(request, project_id)
    store = _store(request)
    links = store.list_links(project_id=project_id)
    link_by_database = {link.database_id: link for link in links}
    sources: list[ProjectDataSourceOption] = []
    for source in store.list_data_sources():
        databases = []
        for database in store.list_databases(source.id):
            link = link_by_database.get(database.id)
            databases.append(
                ProjectDatabaseOption(
                    id=database.id,
                    remote_name=database.remote_name,
                    display_name=database.display_name,
                    namespace_type=database.namespace_type,
                    available=database.available,
                    selected=link is not None,
                    link_id=link.id if link is not None else None,
                )
            )
        sources.append(
            ProjectDataSourceOption(
                id=source.id,
                name=source.name,
                category=source.category,
                engine=source.engine,
                enabled=source.enabled,
                databases=databases,
            )
        )
    return ProjectDataSourceOptions(
        project_id=project_id,
        project_name=project_name,
        selected_source_count=len({link.data_source_id for link in links}),
        selected_database_count=len(links),
        sources=sources,
    )


@router.get("/data-sources", response_model=list[DataSourceSummary])
def list_data_sources(request: Request) -> list[DataSourceSummary]:
    try:
        return [_source_summary(item) for item in _store(request).list_data_sources()]
    except DataSourceRepositoryError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/data-sources",
    response_model=DataSourceSummary,
    status_code=status.HTTP_201_CREATED,
)
def create_data_source(payload: DataSourceCreate, request: Request) -> DataSourceSummary:
    now = datetime.now(UTC)
    record = DataSourceRecord(
        id=uuid4().hex,
        name=payload.name.strip(),
        category=payload.category.strip(),
        engine=payload.engine,
        description=payload.description.strip(),
        connection_config=payload.connection_config,
        enabled=payload.enabled,
        config_version=1,
        database_count=0,
        project_count=0,
        created_at=now,
        updated_at=now,
    )
    try:
        _store(request).create_data_source(record)
        return _source_summary(_store(request).get_data_source(record.id))
    except DataSourceRepositoryError as exc:
        raise _http_error(exc) from exc


@router.put("/data-sources/{data_source_id}", response_model=DataSourceSummary)
def update_data_source(
    data_source_id: str, payload: DataSourceUpdate, request: Request
) -> DataSourceSummary:
    try:
        previous = _store(request).get_data_source(data_source_id)
        record = replace(
            previous,
            name=payload.name.strip(),
            category=payload.category.strip(),
            engine=payload.engine,
            description=payload.description.strip(),
            connection_config=_merged_config(previous.connection_config, payload.connection_config),
            enabled=payload.enabled,
            config_version=previous.config_version + 1,
            updated_at=datetime.now(UTC),
        )
        _store(request).update_data_source(record)
        return _source_summary(_store(request).get_data_source(data_source_id))
    except DataSourceRepositoryError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/data-sources/{data_source_id}/reveal-password",
    response_model=DataSourcePasswordReveal,
)
def reveal_data_source_password(
    data_source_id: str,
    request: Request,
    response: Response,
) -> DataSourcePasswordReveal:
    try:
        source = _store(request).get_data_source(data_source_id)
        password = source.connection_config.get("password")
        if password is None:
            password = source.connection_config.get("passwd", "")
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        return DataSourcePasswordReveal(password=str(password or ""))
    except DataSourceRepositoryError as exc:
        raise _http_error(exc) from exc


@router.delete("/data-sources/{data_source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_data_source(data_source_id: str, request: Request) -> Response:
    try:
        _store(request).delete_data_source(data_source_id)
    except DataSourceRepositoryError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/data-sources/{data_source_id}/databases",
    response_model=list[DataSourceDatabaseSummary],
)
def list_databases(data_source_id: str, request: Request) -> list[DataSourceDatabaseSummary]:
    try:
        return [_database_summary(item) for item in _store(request).list_databases(data_source_id)]
    except DataSourceRepositoryError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/data-sources/{data_source_id}/databases/sync",
    response_model=DataSourceDatabaseSyncResult,
)
def sync_databases(
    data_source_id: str,
    request: Request,
) -> DataSourceDatabaseSyncResult:
    try:
        store = _store(request)
        source = store.get_data_source(data_source_id)
        existing = store.list_databases(data_source_id)
        existing_names = {database.remote_name for database in existing}
        discovered = discover_databases(source)
        discovery_method = "pg_database" if source.engine == "postgresql" else "SHOW DATABASES"
        now = datetime.now(UTC)
        records = [
            DataSourceDatabaseRecord(
                id=uuid4().hex,
                data_source_id=data_source_id,
                remote_name=database.name,
                display_name=database.name,
                namespace_type="database",
                available=True,
                system_database=database.system_database,
                metadata={"discovery": discovery_method},
                project_count=0,
                created_at=now,
                updated_at=now,
            )
            for database in discovered
        ]
        store.sync_databases(data_source_id, records)
        databases = store.list_databases(data_source_id)
        return DataSourceDatabaseSyncResult(
            discovered_count=len(discovered),
            created_count=sum(1 for database in discovered if database.name not in existing_names),
            unavailable_count=sum(1 for database in databases if not database.available),
            databases=[_database_summary(database) for database in databases],
        )
    except DataSourceRepositoryError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/data-sources/{data_source_id}/databases",
    response_model=DataSourceDatabaseSummary,
    status_code=status.HTTP_201_CREATED,
)
def create_database(
    data_source_id: str, payload: DataSourceDatabaseCreate, request: Request
) -> DataSourceDatabaseSummary:
    now = datetime.now(UTC)
    record = DataSourceDatabaseRecord(
        id=uuid4().hex,
        data_source_id=data_source_id,
        remote_name=payload.remote_name.strip(),
        display_name=payload.display_name.strip(),
        namespace_type=payload.namespace_type,
        available=payload.available,
        system_database=payload.system_database,
        metadata=payload.metadata,
        project_count=0,
        created_at=now,
        updated_at=now,
    )
    try:
        _store(request).create_database(record)
        return _database_summary(_store(request).get_database(record.id))
    except DataSourceRepositoryError as exc:
        raise _http_error(exc) from exc


@router.put(
    "/data-sources/{data_source_id}/databases/{database_id}",
    response_model=DataSourceDatabaseSummary,
)
def update_database(
    data_source_id: str,
    database_id: str,
    payload: DataSourceDatabaseUpdate,
    request: Request,
) -> DataSourceDatabaseSummary:
    try:
        previous = _store(request).get_database(database_id)
        if previous.data_source_id != data_source_id:
            raise DataSourceRepositoryError("数据库不属于这个数据源")
        record = replace(
            previous,
            remote_name=payload.remote_name.strip(),
            display_name=payload.display_name.strip(),
            namespace_type=payload.namespace_type,
            available=payload.available,
            system_database=payload.system_database,
            metadata=payload.metadata,
            updated_at=datetime.now(UTC),
        )
        _store(request).update_database(record)
        return _database_summary(_store(request).get_database(database_id))
    except DataSourceRepositoryError as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/data-sources/{data_source_id}/databases/{database_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_database(data_source_id: str, database_id: str, request: Request) -> Response:
    try:
        database = _store(request).get_database(database_id)
        if database.data_source_id != data_source_id:
            raise DataSourceRepositoryError("数据库不属于这个数据源")
        _store(request).delete_database(database_id)
    except DataSourceRepositoryError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/data-sources/databases/{database_id}/projects",
    response_model=list[ProjectDatabaseLinkSummary],
)
def list_database_projects(database_id: str, request: Request) -> list[ProjectDatabaseLinkSummary]:
    try:
        _store(request).get_database(database_id)
        return [_link_summary(item) for item in _store(request).list_links(database_id=database_id)]
    except DataSourceRepositoryError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/data-sources/databases/{database_id}/projects",
    response_model=ProjectDatabaseLinkSummary,
    status_code=status.HTTP_201_CREATED,
)
def create_database_project_link(
    database_id: str, payload: ProjectDatabaseLinkCreate, request: Request
) -> ProjectDatabaseLinkSummary:
    try:
        database = _store(request).get_database(database_id)
        source = _store(request).get_data_source(database.data_source_id)
        project_name = _project_name(request, payload.project_id)
        now = datetime.now(UTC)
        record = ProjectDatabaseLinkRecord(
            id=uuid4().hex,
            project_id=payload.project_id,
            project_name=project_name,
            database_id=database_id,
            database_name=database.remote_name,
            data_source_id=source.id,
            data_source_name=source.name,
            engine=source.engine,
            alias=payload.alias.strip(),
            purpose=payload.purpose.strip(),
            enabled=payload.enabled,
            readonly=payload.readonly,
            allowed_schemas=payload.allowed_schemas,
            max_rows=payload.max_rows,
            max_result_bytes=payload.max_result_bytes,
            query_timeout_ms=payload.query_timeout_ms,
            created_at=now,
            updated_at=now,
        )
        _store(request).create_link(record)
        return _link_summary(record)
    except DataSourceRepositoryError as exc:
        raise _http_error(exc) from exc


@router.put(
    "/data-sources/databases/{database_id}/projects/{link_id}",
    response_model=ProjectDatabaseLinkSummary,
)
def update_database_project_link(
    database_id: str,
    link_id: str,
    payload: ProjectDatabaseLinkUpdate,
    request: Request,
) -> ProjectDatabaseLinkSummary:
    try:
        previous = next(
            (
                item
                for item in _store(request).list_links(database_id=database_id)
                if item.id == link_id
            ),
            None,
        )
        if previous is None:
            raise DataSourceRepositoryError("项目数据库关联不存在")
        project_name = _project_name(request, payload.project_id)
        record = replace(
            previous,
            project_id=payload.project_id,
            project_name=project_name,
            alias=payload.alias.strip(),
            purpose=payload.purpose.strip(),
            enabled=payload.enabled,
            readonly=payload.readonly,
            allowed_schemas=payload.allowed_schemas,
            max_rows=payload.max_rows,
            max_result_bytes=payload.max_result_bytes,
            query_timeout_ms=payload.query_timeout_ms,
            updated_at=datetime.now(UTC),
        )
        _store(request).update_link(record)
        return _link_summary(record)
    except DataSourceRepositoryError as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/data-sources/databases/{database_id}/projects/{link_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_database_project_link(database_id: str, link_id: str, request: Request) -> Response:
    try:
        if not any(
            item.id == link_id for item in _store(request).list_links(database_id=database_id)
        ):
            raise DataSourceRepositoryError("项目数据库关联不存在")
        _store(request).delete_link(link_id)
    except DataSourceRepositoryError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/projects/{project_id}/databases",
    response_model=list[ProjectDatabaseLinkSummary],
)
def list_project_databases(project_id: str, request: Request) -> list[ProjectDatabaseLinkSummary]:
    try:
        _project_name(request, project_id)
        return [_link_summary(item) for item in _store(request).list_links(project_id=project_id)]
    except DataSourceRepositoryError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/projects/{project_id}/data-source-options",
    response_model=ProjectDataSourceOptions,
)
def get_project_data_source_options(project_id: str, request: Request) -> ProjectDataSourceOptions:
    try:
        return _project_data_source_options(request, project_id)
    except DataSourceRepositoryError as exc:
        raise _http_error(exc) from exc


@router.put(
    "/projects/{project_id}/databases",
    response_model=ProjectDataSourceOptions,
)
def replace_project_databases(
    project_id: str,
    payload: ProjectDatabaseSelectionUpdate,
    request: Request,
) -> ProjectDataSourceOptions:
    try:
        project_name = _project_name(request, project_id)
        if len(payload.database_ids) != len(set(payload.database_ids)):
            raise DataSourceRepositoryError("数据库选择中存在重复项")

        store = _store(request)
        sources = store.list_data_sources()
        source_by_id = {source.id: source for source in sources}
        database_by_id: dict[str, DataSourceDatabaseRecord] = {}
        for source in sources:
            for database in store.list_databases(source.id):
                database_by_id[database.id] = database

        missing = [item for item in payload.database_ids if item not in database_by_id]
        if missing:
            raise DataSourceRepositoryError("选择中包含不存在的数据库")

        existing_by_database = {
            link.database_id: link for link in store.list_links(project_id=project_id)
        }
        now = datetime.now(UTC)
        records: list[ProjectDatabaseLinkRecord] = []
        for database_id in payload.database_ids:
            existing = existing_by_database.get(database_id)
            if existing is not None:
                records.append(existing)
                continue
            database = database_by_id[database_id]
            source = source_by_id[database.data_source_id]
            if not source.enabled:
                raise DataSourceRepositoryError(f"数据源“{source.name}”已停用")
            if not database.available:
                raise DataSourceRepositoryError(f"数据库“{database.remote_name}”当前不可用")
            records.append(
                ProjectDatabaseLinkRecord(
                    id=uuid4().hex,
                    project_id=project_id,
                    project_name=project_name,
                    database_id=database.id,
                    database_name=database.remote_name,
                    data_source_id=source.id,
                    data_source_name=source.name,
                    engine=source.engine,
                    alias=database.display_name or database.remote_name,
                    purpose="项目数据源访问",
                    enabled=True,
                    readonly=True,
                    allowed_schemas=[],
                    max_rows=1000,
                    max_result_bytes=2_000_000,
                    query_timeout_ms=15_000,
                    created_at=now,
                    updated_at=now,
                )
            )
        store.replace_project_links(project_id, records)
        return _project_data_source_options(request, project_id)
    except DataSourceRepositoryError as exc:
        raise _http_error(exc) from exc
