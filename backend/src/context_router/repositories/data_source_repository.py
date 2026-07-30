from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Literal, Protocol

import psycopg
from psycopg.types.json import Jsonb

from context_router.repositories.project_repository import (
    ProjectRepositoryError,
    ProjectStore,
)


class DataSourceRepositoryError(RuntimeError):
    pass


_MCP_ALIAS_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_INVALID_ALIAS_CHARACTERS = re.compile(r"[^a-z0-9]+")


def _normalize_alias_candidate(value: str) -> str | None:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = _INVALID_ALIAS_CHARACTERS.sub("_", ascii_value).strip("_")
    if not slug:
        return None
    if not slug[0].isalpha():
        slug = f"db_{slug}"
    return slug[:64].rstrip("_")


def _stable_link_token(link_id: str) -> str:
    normalized = re.sub(r"[^a-z0-9]", "", link_id.lower())
    if len(normalized) >= 8:
        return normalized
    return hashlib.sha256(link_id.encode()).hexdigest()


def _generate_mcp_alias(
    *,
    record: ProjectDatabaseLinkRecord,
    database: DataSourceDatabaseRecord,
    used_aliases: set[str],
) -> str:
    base = next(
        (
            candidate
            for candidate in (
                _normalize_alias_candidate(record.alias),
                _normalize_alias_candidate(database.display_name),
                _normalize_alias_candidate(database.remote_name),
            )
            if candidate is not None
        ),
        f"db_{_stable_link_token(record.id)[:8]}",
    )
    if base.casefold() not in used_aliases:
        return base

    token = _stable_link_token(record.id)
    suffix_candidates = [token[:length] for length in range(8, len(token) + 1, 4)]
    digest = hashlib.sha256(record.id.encode()).hexdigest()
    suffix_candidates.extend(digest[:length] for length in range(8, len(digest) + 1, 4))
    for suffix in suffix_candidates:
        candidate = f"{base[: 63 - len(suffix)].rstrip('_')}_{suffix}"
        if candidate.casefold() not in used_aliases:
            return candidate
    raise DataSourceRepositoryError("无法生成唯一的 MCP 数据库别名")


def _prepare_link_alias(
    record: ProjectDatabaseLinkRecord,
    *,
    database: DataSourceDatabaseRecord,
    used_aliases: set[str],
) -> ProjectDatabaseLinkRecord:
    if record.mcp_alias is None:
        mcp_alias = _generate_mcp_alias(
            record=record,
            database=database,
            used_aliases=used_aliases,
        )
    else:
        mcp_alias = record.mcp_alias.strip()
        if not _MCP_ALIAS_PATTERN.fullmatch(mcp_alias):
            raise DataSourceRepositoryError("MCP 数据库别名格式不正确")
        if mcp_alias.casefold() in used_aliases:
            raise DataSourceRepositoryError("工作空间内 MCP 数据库别名已存在")
    return replace(record, mcp_alias=mcp_alias)


def _link_alias_key(record: ProjectDatabaseLinkRecord) -> str:
    if record.mcp_alias is None:
        raise DataSourceRepositoryError("项目数据库尚未配置 MCP 别名")
    return record.mcp_alias.casefold()


def _link_workspace_id(record: ProjectDatabaseLinkRecord) -> str:
    # Compatibility for in-memory callers created before Workspace existed.
    return record.workspace_id or record.project_id


@dataclass(frozen=True, slots=True)
class DataSourceRecord:
    id: str
    name: str
    category: str
    engine: str
    description: str
    connection_config: dict[str, Any]
    enabled: bool
    config_version: int
    database_count: int
    project_count: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DataSourceDatabaseRecord:
    id: str
    data_source_id: str
    remote_name: str
    display_name: str
    namespace_type: str
    available: bool
    system_database: bool
    metadata: dict[str, Any]
    project_count: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ProjectDatabaseLinkRecord:
    id: str
    project_id: str
    project_name: str
    database_id: str
    database_name: str
    data_source_id: str
    data_source_name: str
    engine: str
    alias: str
    mcp_alias: str | None
    purpose: str
    enabled: bool
    readonly: bool
    allowed_schemas: list[str]
    max_rows: int
    max_result_bytes: int
    query_timeout_ms: int
    created_at: datetime
    updated_at: datetime
    workspace_id: str | None = None
    workspace_enabled: bool = True
    project_kind: str = "backend"


@dataclass(frozen=True, slots=True)
class ResolvedProjectDatabase:
    link_id: str
    workspace_id: str
    workspace_enabled: bool
    project_id: str
    project_name: str
    project_kind: str
    mcp_alias: str
    alias: str
    purpose: str
    link_enabled: bool
    readonly: bool
    allowed_schemas: list[str]
    max_rows: int
    max_result_bytes: int
    query_timeout_ms: int
    link_created_at: datetime
    link_updated_at: datetime
    database_id: str
    database_remote_name: str
    database_display_name: str
    namespace_type: str
    database_available: bool
    database_system: bool
    database_metadata: dict[str, Any]
    database_created_at: datetime
    database_updated_at: datetime
    data_source_id: str
    data_source_name: str
    data_source_category: str
    engine: str
    data_source_description: str
    connection_config: dict[str, Any]
    source_enabled: bool
    config_version: int
    source_created_at: datetime
    source_updated_at: datetime


WorkspaceDataSourceAssignmentStatus = Literal[
    "active",
    "workspace_disabled",
    "source_disabled",
    "database_unavailable",
    "system_database",
    "link_disabled",
    "not_readonly",
    "missing_mcp_alias",
]


@dataclass(frozen=True, slots=True)
class WorkspaceDataSourceAssignmentRecord:
    link_id: str
    project_id: str
    project_name: str
    project_kind: str
    database_id: str
    database_name: str
    database_display_name: str
    mcp_alias: str | None
    alias: str
    purpose: str
    status: WorkspaceDataSourceAssignmentStatus
    workspace_enabled: bool
    link_enabled: bool
    readonly: bool
    database_available: bool
    database_system: bool
    source_enabled: bool


@dataclass(frozen=True, slots=True)
class WorkspaceDataSourceUsageRecord:
    id: str
    name: str
    category: str
    engine: str
    enabled: bool
    database_count: int
    assignment_count: int
    project_count: int
    assignments: list[WorkspaceDataSourceAssignmentRecord]


@dataclass(frozen=True, slots=True)
class WorkspaceDataSourceSummaryRecord:
    workspace_id: str
    workspace_enabled: bool
    source_count: int
    database_count: int
    assignment_count: int
    project_count: int
    sources: list[WorkspaceDataSourceUsageRecord]


@dataclass(frozen=True, slots=True)
class _WorkspaceDataSourceIdentity:
    id: str
    name: str
    category: str
    engine: str
    enabled: bool


def _workspace_assignment_status(
    *,
    workspace_enabled: bool,
    source_enabled: bool,
    database_available: bool,
    database_system: bool,
    link_enabled: bool,
    readonly: bool,
    mcp_alias: str | None,
) -> WorkspaceDataSourceAssignmentStatus:
    if not workspace_enabled:
        return "workspace_disabled"
    if not source_enabled:
        return "source_disabled"
    if not database_available:
        return "database_unavailable"
    if database_system:
        return "system_database"
    if not link_enabled:
        return "link_disabled"
    if not readonly:
        return "not_readonly"
    if mcp_alias is None:
        return "missing_mcp_alias"
    return "active"


def _workspace_data_source_summary(
    *,
    workspace_id: str,
    workspace_enabled: bool,
    assignments: list[tuple[_WorkspaceDataSourceIdentity, WorkspaceDataSourceAssignmentRecord]],
) -> WorkspaceDataSourceSummaryRecord:
    grouped: dict[
        str,
        tuple[_WorkspaceDataSourceIdentity, list[WorkspaceDataSourceAssignmentRecord]],
    ] = {}
    for source, assignment in assignments:
        grouped.setdefault(source.id, (source, []))[1].append(assignment)

    sources: list[WorkspaceDataSourceUsageRecord] = []
    for source, source_assignments in grouped.values():
        ordered_assignments = sorted(
            source_assignments,
            key=lambda item: (
                item.project_name.casefold(),
                item.project_id,
                item.database_name.casefold(),
                item.database_id,
                item.link_id,
            ),
        )
        sources.append(
            WorkspaceDataSourceUsageRecord(
                id=source.id,
                name=source.name,
                category=source.category,
                engine=source.engine,
                enabled=source.enabled,
                database_count=len({item.database_id for item in source_assignments}),
                assignment_count=len(source_assignments),
                project_count=len({item.project_id for item in source_assignments}),
                assignments=ordered_assignments,
            )
        )
    sources.sort(key=lambda item: (item.name.casefold(), item.id))

    return WorkspaceDataSourceSummaryRecord(
        workspace_id=workspace_id,
        workspace_enabled=workspace_enabled,
        source_count=len(sources),
        database_count=len(
            {
                assignment.database_id
                for _, source_assignments in grouped.values()
                for assignment in source_assignments
            }
        ),
        assignment_count=len(assignments),
        project_count=len({assignment.project_id for _, assignment in assignments}),
        sources=sources,
    )


class DataSourceStore(Protocol):
    def list_data_sources(self) -> list[DataSourceRecord]: ...
    def get_data_source(self, data_source_id: str) -> DataSourceRecord: ...
    def create_data_source(self, record: DataSourceRecord) -> None: ...
    def update_data_source(self, record: DataSourceRecord) -> None: ...
    def delete_data_source(self, data_source_id: str) -> None: ...
    def list_databases(self, data_source_id: str) -> list[DataSourceDatabaseRecord]: ...
    def get_database(self, database_id: str) -> DataSourceDatabaseRecord: ...
    def create_database(self, record: DataSourceDatabaseRecord) -> None: ...
    def update_database(self, record: DataSourceDatabaseRecord) -> None: ...
    def delete_database(self, database_id: str) -> None: ...
    def sync_databases(
        self, data_source_id: str, records: list[DataSourceDatabaseRecord]
    ) -> None: ...
    def list_links(
        self, *, project_id: str | None = None, database_id: str | None = None
    ) -> list[ProjectDatabaseLinkRecord]: ...
    def get_project_database_by_alias(
        self, *, project_id: str, mcp_alias: str
    ) -> ResolvedProjectDatabase: ...
    def get_database_by_link_id(self, link_id: str) -> ResolvedProjectDatabase: ...
    def list_project_databases_for_mcp(self, project_id: str) -> list[ResolvedProjectDatabase]: ...
    def get_workspace_database_by_alias(
        self, *, workspace_id: str, mcp_alias: str
    ) -> ResolvedProjectDatabase: ...
    def list_workspace_databases_for_mcp(
        self, workspace_id: str
    ) -> list[ResolvedProjectDatabase]: ...
    def create_link(self, record: ProjectDatabaseLinkRecord) -> ProjectDatabaseLinkRecord: ...
    def update_link(self, record: ProjectDatabaseLinkRecord) -> ProjectDatabaseLinkRecord: ...
    def delete_link(self, link_id: str) -> None: ...
    def replace_project_links(
        self, project_id: str, records: list[ProjectDatabaseLinkRecord]
    ) -> list[ProjectDatabaseLinkRecord]: ...
    def get_workspace_data_source_summary(
        self,
        workspace_id: str,
        *,
        workspace_enabled: bool | None = None,
    ) -> WorkspaceDataSourceSummaryRecord: ...


class InMemoryDataSourceRepository:
    def __init__(self, project_repository: ProjectStore | None = None) -> None:
        self._sources: dict[str, DataSourceRecord] = {}
        self._databases: dict[str, DataSourceDatabaseRecord] = {}
        self._links: dict[str, ProjectDatabaseLinkRecord] = {}
        self._project_repository = project_repository

    def bind_project_repository(self, project_repository: ProjectStore) -> None:
        self._project_repository = project_repository
        self._synchronize_project_links()

    def _synchronize_project_links(self) -> None:
        if self._project_repository is None:
            return
        synchronized: dict[str, ProjectDatabaseLinkRecord] = {}
        for link_id, link in self._links.items():
            try:
                project = self._project_repository.get_project(link.project_id)
            except ProjectRepositoryError:
                continue
            synchronized[link_id] = replace(
                link,
                project_name=project.name,
                workspace_id=project.workspace_id,
                workspace_enabled=project.workspace_enabled,
                project_kind=project.project_kind,
            )
        self._links = synchronized

    def list_data_sources(self) -> list[DataSourceRecord]:
        return [self._hydrate_source(item) for item in self._sources.values()]

    def get_data_source(self, data_source_id: str) -> DataSourceRecord:
        record = self._sources.get(data_source_id)
        if record is None:
            raise DataSourceRepositoryError("数据源不存在")
        return self._hydrate_source(record)

    def create_data_source(self, record: DataSourceRecord) -> None:
        if any(item.name == record.name for item in self._sources.values()):
            raise DataSourceRepositoryError("数据源名称已存在")
        self._sources[record.id] = record

    def update_data_source(self, record: DataSourceRecord) -> None:
        self.get_data_source(record.id)
        if any(
            item.id != record.id and item.name == record.name for item in self._sources.values()
        ):
            raise DataSourceRepositoryError("数据源名称已存在")
        self._sources[record.id] = record

    def delete_data_source(self, data_source_id: str) -> None:
        self.get_data_source(data_source_id)
        database_ids = {
            item.id for item in self._databases.values() if item.data_source_id == data_source_id
        }
        self._links = {
            key: item for key, item in self._links.items() if item.database_id not in database_ids
        }
        self._databases = {
            key: item
            for key, item in self._databases.items()
            if item.data_source_id != data_source_id
        }
        del self._sources[data_source_id]

    def list_databases(self, data_source_id: str) -> list[DataSourceDatabaseRecord]:
        self.get_data_source(data_source_id)
        return [
            self._hydrate_database(item)
            for item in self._databases.values()
            if item.data_source_id == data_source_id
        ]

    def get_database(self, database_id: str) -> DataSourceDatabaseRecord:
        record = self._databases.get(database_id)
        if record is None:
            raise DataSourceRepositoryError("数据库不存在")
        return self._hydrate_database(record)

    def create_database(self, record: DataSourceDatabaseRecord) -> None:
        self.get_data_source(record.data_source_id)
        if any(
            item.data_source_id == record.data_source_id and item.remote_name == record.remote_name
            for item in self._databases.values()
        ):
            raise DataSourceRepositoryError("该数据源下已经存在同名数据库")
        self._databases[record.id] = record

    def update_database(self, record: DataSourceDatabaseRecord) -> None:
        self.get_database(record.id)
        if any(
            item.id != record.id
            and item.data_source_id == record.data_source_id
            and item.remote_name == record.remote_name
            for item in self._databases.values()
        ):
            raise DataSourceRepositoryError("该数据源下已经存在同名数据库")
        self._databases[record.id] = record

    def delete_database(self, database_id: str) -> None:
        self.get_database(database_id)
        self._links = {
            key: item for key, item in self._links.items() if item.database_id != database_id
        }
        del self._databases[database_id]

    def sync_databases(self, data_source_id: str, records: list[DataSourceDatabaseRecord]) -> None:
        self.get_data_source(data_source_id)
        discovered_by_name = {record.remote_name: record for record in records}
        existing_by_name = {
            record.remote_name: record
            for record in self._databases.values()
            if record.data_source_id == data_source_id
        }
        now = max((record.updated_at for record in records), default=None)
        for existing in existing_by_name.values():
            if existing.remote_name not in discovered_by_name:
                self._databases[existing.id] = replace(
                    existing,
                    available=False,
                    updated_at=now or existing.updated_at,
                )
        for discovered in records:
            existing = existing_by_name.get(discovered.remote_name)
            if existing is None:
                self._databases[discovered.id] = discovered
                continue
            self._databases[existing.id] = replace(
                existing,
                namespace_type=discovered.namespace_type,
                available=True,
                system_database=discovered.system_database,
                metadata=discovered.metadata,
                updated_at=discovered.updated_at,
            )

    def list_links(
        self, *, project_id: str | None = None, database_id: str | None = None
    ) -> list[ProjectDatabaseLinkRecord]:
        self._synchronize_project_links()
        return [
            item
            for item in self._links.values()
            if (project_id is None or item.project_id == project_id)
            and (database_id is None or item.database_id == database_id)
        ]

    def get_project_database_by_alias(
        self, *, project_id: str, mcp_alias: str
    ) -> ResolvedProjectDatabase:
        self._synchronize_project_links()
        matches = [
            link
            for link in self._links.values()
            if link.project_id == project_id
            and link.mcp_alias is not None
            and link.mcp_alias.casefold() == mcp_alias.casefold()
        ]
        if len(matches) != 1:
            raise DataSourceRepositoryError("项目数据库不存在")
        return self._resolved_record(matches[0])

    def get_database_by_link_id(self, link_id: str) -> ResolvedProjectDatabase:
        self._synchronize_project_links()
        link = self._links.get(link_id)
        if link is None:
            raise DataSourceRepositoryError("项目数据库不存在")
        return self._resolved_record(link)

    def list_project_databases_for_mcp(self, project_id: str) -> list[ResolvedProjectDatabase]:
        self._synchronize_project_links()
        records = [
            self._resolved_record(link)
            for link in self._links.values()
            if link.project_id == project_id and link.mcp_alias is not None
        ]
        return sorted(records, key=lambda item: (item.mcp_alias.casefold(), item.link_id))

    def get_workspace_database_by_alias(
        self, *, workspace_id: str, mcp_alias: str
    ) -> ResolvedProjectDatabase:
        self._synchronize_project_links()
        matches = [
            link
            for link in self._links.values()
            if _link_workspace_id(link) == workspace_id
            and link.mcp_alias is not None
            and link.mcp_alias.casefold() == mcp_alias.casefold()
        ]
        if len(matches) != 1:
            raise DataSourceRepositoryError("工作空间数据库不存在")
        return self._resolved_record(matches[0])

    def list_workspace_databases_for_mcp(self, workspace_id: str) -> list[ResolvedProjectDatabase]:
        self._synchronize_project_links()
        records = [
            self._resolved_record(link)
            for link in self._links.values()
            if _link_workspace_id(link) == workspace_id and link.mcp_alias is not None
        ]
        return sorted(records, key=lambda item: (item.mcp_alias.casefold(), item.link_id))

    def create_link(self, record: ProjectDatabaseLinkRecord) -> ProjectDatabaseLinkRecord:
        database = self.get_database(record.database_id)
        if any(
            item.project_id == record.project_id and item.database_id == record.database_id
            for item in self._links.values()
        ):
            raise DataSourceRepositoryError("项目已经关联这个数据库")
        used_aliases = {
            item.mcp_alias.casefold()
            for item in self._links.values()
            if _link_workspace_id(item) == _link_workspace_id(record) and item.mcp_alias is not None
        }
        saved_record = _prepare_link_alias(
            record,
            database=database,
            used_aliases=used_aliases,
        )
        self._links[saved_record.id] = saved_record
        return saved_record

    def update_link(self, record: ProjectDatabaseLinkRecord) -> ProjectDatabaseLinkRecord:
        self._synchronize_project_links()
        if record.id not in self._links:
            raise DataSourceRepositoryError("项目数据库关联不存在")
        database = self.get_database(record.database_id)
        if any(
            item.id != record.id
            and item.project_id == record.project_id
            and item.database_id == record.database_id
            for item in self._links.values()
        ):
            raise DataSourceRepositoryError("项目已经关联这个数据库")
        used_aliases = {
            item.mcp_alias.casefold()
            for item in self._links.values()
            if item.id != record.id
            and _link_workspace_id(item) == _link_workspace_id(record)
            and item.mcp_alias is not None
        }
        saved_record = _prepare_link_alias(
            record,
            database=database,
            used_aliases=used_aliases,
        )
        self._links[saved_record.id] = saved_record
        return saved_record

    def delete_link(self, link_id: str) -> None:
        self._synchronize_project_links()
        if link_id not in self._links:
            raise DataSourceRepositoryError("项目数据库关联不存在")
        del self._links[link_id]

    def replace_project_links(
        self, project_id: str, records: list[ProjectDatabaseLinkRecord]
    ) -> list[ProjectDatabaseLinkRecord]:
        self._synchronize_project_links()
        if any(record.project_id != project_id for record in records):
            raise DataSourceRepositoryError("项目数据库关联不属于当前项目")
        if len({record.database_id for record in records}) != len(records):
            raise DataSourceRepositoryError("项目数据库关联中存在重复数据库")

        database_by_id = {
            record.database_id: self.get_database(record.database_id) for record in records
        }
        workspace_ids = {_link_workspace_id(record) for record in records}
        if len(workspace_ids) > 1:
            raise DataSourceRepositoryError("项目数据库关联不属于同一工作空间")
        workspace_id = next(iter(workspace_ids), None)
        used_aliases = {
            item.mcp_alias.casefold()
            for item in self._links.values()
            if item.project_id != project_id
            and _link_workspace_id(item) == workspace_id
            and item.mcp_alias is not None
        }
        saved_by_id: dict[str, ProjectDatabaseLinkRecord] = {}
        for record in records:
            if record.mcp_alias is None:
                continue
            saved = _prepare_link_alias(
                record,
                database=database_by_id[record.database_id],
                used_aliases=used_aliases,
            )
            saved_by_id[record.id] = saved
            used_aliases.add(_link_alias_key(saved))
        for record in records:
            if record.id in saved_by_id:
                continue
            saved = _prepare_link_alias(
                record,
                database=database_by_id[record.database_id],
                used_aliases=used_aliases,
            )
            saved_by_id[record.id] = saved
            used_aliases.add(_link_alias_key(saved))

        saved_records = [saved_by_id[record.id] for record in records]
        retained = {key: item for key, item in self._links.items() if item.project_id != project_id}
        retained.update({record.id: record for record in saved_records})
        self._links = retained
        return saved_records

    def get_workspace_data_source_summary(
        self,
        workspace_id: str,
        *,
        workspace_enabled: bool | None = None,
    ) -> WorkspaceDataSourceSummaryRecord:
        self._synchronize_project_links()
        links = [link for link in self._links.values() if _link_workspace_id(link) == workspace_id]
        resolved_workspace_enabled = (
            workspace_enabled
            if workspace_enabled is not None
            else all(link.workspace_enabled for link in links)
        )

        assignments: list[
            tuple[_WorkspaceDataSourceIdentity, WorkspaceDataSourceAssignmentRecord]
        ] = []
        for link in links:
            database = self._databases.get(link.database_id)
            if database is None:
                raise DataSourceRepositoryError("数据库不存在")
            source = self._sources.get(database.data_source_id)
            if source is None:
                raise DataSourceRepositoryError("数据源不存在")
            assignment = WorkspaceDataSourceAssignmentRecord(
                link_id=link.id,
                project_id=link.project_id,
                project_name=link.project_name,
                project_kind=link.project_kind,
                database_id=database.id,
                database_name=database.remote_name,
                database_display_name=database.display_name,
                mcp_alias=link.mcp_alias,
                alias=link.alias,
                purpose=link.purpose,
                status=_workspace_assignment_status(
                    workspace_enabled=resolved_workspace_enabled,
                    source_enabled=source.enabled,
                    database_available=database.available,
                    database_system=database.system_database,
                    link_enabled=link.enabled,
                    readonly=link.readonly,
                    mcp_alias=link.mcp_alias,
                ),
                workspace_enabled=resolved_workspace_enabled,
                link_enabled=link.enabled,
                readonly=link.readonly,
                database_available=database.available,
                database_system=database.system_database,
                source_enabled=source.enabled,
            )
            assignments.append(
                (
                    _WorkspaceDataSourceIdentity(
                        id=source.id,
                        name=source.name,
                        category=source.category,
                        engine=source.engine,
                        enabled=source.enabled,
                    ),
                    assignment,
                )
            )
        return _workspace_data_source_summary(
            workspace_id=workspace_id,
            workspace_enabled=resolved_workspace_enabled,
            assignments=assignments,
        )

    def _hydrate_source(self, record: DataSourceRecord) -> DataSourceRecord:
        self._synchronize_project_links()
        database_ids = {
            item.id for item in self._databases.values() if item.data_source_id == record.id
        }
        project_ids = {
            item.project_id for item in self._links.values() if item.database_id in database_ids
        }
        return replace(
            record,
            database_count=len(database_ids),
            project_count=len(project_ids),
        )

    def _hydrate_database(self, record: DataSourceDatabaseRecord) -> DataSourceDatabaseRecord:
        self._synchronize_project_links()
        return replace(
            record,
            project_count=sum(1 for item in self._links.values() if item.database_id == record.id),
        )

    def _resolved_record(self, link: ProjectDatabaseLinkRecord) -> ResolvedProjectDatabase:
        if link.mcp_alias is None:
            raise DataSourceRepositoryError("项目数据库尚未配置 MCP 别名")
        database = self._databases.get(link.database_id)
        if database is None:
            raise DataSourceRepositoryError("数据库不存在")
        source = self._sources.get(database.data_source_id)
        if source is None:
            raise DataSourceRepositoryError("数据源不存在")
        return ResolvedProjectDatabase(
            link_id=link.id,
            workspace_id=_link_workspace_id(link),
            workspace_enabled=link.workspace_enabled,
            project_id=link.project_id,
            project_name=link.project_name,
            project_kind=link.project_kind,
            mcp_alias=link.mcp_alias,
            alias=link.alias,
            purpose=link.purpose,
            link_enabled=link.enabled,
            readonly=link.readonly,
            allowed_schemas=list(link.allowed_schemas),
            max_rows=link.max_rows,
            max_result_bytes=link.max_result_bytes,
            query_timeout_ms=link.query_timeout_ms,
            link_created_at=link.created_at,
            link_updated_at=link.updated_at,
            database_id=database.id,
            database_remote_name=database.remote_name,
            database_display_name=database.display_name,
            namespace_type=database.namespace_type,
            database_available=database.available,
            database_system=database.system_database,
            database_metadata=dict(database.metadata),
            database_created_at=database.created_at,
            database_updated_at=database.updated_at,
            data_source_id=source.id,
            data_source_name=source.name,
            data_source_category=source.category,
            engine=source.engine,
            data_source_description=source.description,
            connection_config=dict(source.connection_config),
            source_enabled=source.enabled,
            config_version=source.config_version,
            source_created_at=source.created_at,
            source_updated_at=source.updated_at,
        )


class PostgresDataSourceRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url.strip()

    def list_data_sources(self) -> list[DataSourceRecord]:
        with self._connect("数据源读取失败") as connection:
            rows = connection.execute(
                self._source_select() + " GROUP BY source.id ORDER BY source.created_at, source.id"
            ).fetchall()
        return [self._source_record(row) for row in rows]

    def get_data_source(self, data_source_id: str) -> DataSourceRecord:
        with self._connect("数据源读取失败") as connection:
            row = connection.execute(
                self._source_select() + " WHERE source.id = %s GROUP BY source.id",
                (data_source_id,),
            ).fetchone()
        if row is None:
            raise DataSourceRepositoryError("数据源不存在")
        return self._source_record(row)

    def create_data_source(self, record: DataSourceRecord) -> None:
        try:
            with psycopg.connect(self._database_url) as connection:
                connection.execute(
                    """INSERT INTO data_sources
                    (id, name, category, engine, description, connection_config, enabled,
                     config_version)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        record.id,
                        record.name,
                        record.category,
                        record.engine,
                        record.description,
                        Jsonb(record.connection_config),
                        record.enabled,
                        record.config_version,
                    ),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise DataSourceRepositoryError("数据源名称已存在") from exc
        except psycopg.Error as exc:
            raise DataSourceRepositoryError("数据源写入失败") from exc

    def update_data_source(self, record: DataSourceRecord) -> None:
        try:
            with psycopg.connect(self._database_url) as connection:
                cursor = connection.execute(
                    """UPDATE data_sources SET name=%s, category=%s, engine=%s,
                    description=%s, connection_config=%s, enabled=%s, config_version=%s,
                    updated_at=CURRENT_TIMESTAMP WHERE id=%s""",
                    (
                        record.name,
                        record.category,
                        record.engine,
                        record.description,
                        Jsonb(record.connection_config),
                        record.enabled,
                        record.config_version,
                        record.id,
                    ),
                )
                if cursor.rowcount == 0:
                    raise DataSourceRepositoryError("数据源不存在")
        except psycopg.errors.UniqueViolation as exc:
            raise DataSourceRepositoryError("数据源名称已存在") from exc
        except DataSourceRepositoryError:
            raise
        except psycopg.Error as exc:
            raise DataSourceRepositoryError("数据源更新失败") from exc

    def delete_data_source(self, data_source_id: str) -> None:
        self._delete("data_sources", data_source_id, "数据源不存在", "数据源删除失败")

    def list_databases(self, data_source_id: str) -> list[DataSourceDatabaseRecord]:
        self.get_data_source(data_source_id)
        with self._connect("数据库清单读取失败") as connection:
            rows = connection.execute(
                self._database_select()
                + " WHERE database.data_source_id=%s"
                + " GROUP BY database.id"
                + " ORDER BY database.system_database, database.remote_name",
                (data_source_id,),
            ).fetchall()
        return [self._database_record(row) for row in rows]

    def get_database(self, database_id: str) -> DataSourceDatabaseRecord:
        with self._connect("数据库读取失败") as connection:
            row = connection.execute(
                self._database_select() + " WHERE database.id=%s GROUP BY database.id",
                (database_id,),
            ).fetchone()
        if row is None:
            raise DataSourceRepositoryError("数据库不存在")
        return self._database_record(row)

    def create_database(self, record: DataSourceDatabaseRecord) -> None:
        try:
            with psycopg.connect(self._database_url) as connection:
                connection.execute(
                    """INSERT INTO data_source_databases
                    (id, data_source_id, remote_name, display_name, namespace_type,
                     available, system_database, metadata)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        record.id,
                        record.data_source_id,
                        record.remote_name,
                        record.display_name,
                        record.namespace_type,
                        record.available,
                        record.system_database,
                        Jsonb(record.metadata),
                    ),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise DataSourceRepositoryError("该数据源下已经存在同名数据库") from exc
        except psycopg.Error as exc:
            raise DataSourceRepositoryError("数据库写入失败") from exc

    def update_database(self, record: DataSourceDatabaseRecord) -> None:
        try:
            with psycopg.connect(self._database_url) as connection:
                cursor = connection.execute(
                    """UPDATE data_source_databases SET remote_name=%s, display_name=%s,
                    namespace_type=%s, available=%s, system_database=%s, metadata=%s,
                    updated_at=CURRENT_TIMESTAMP WHERE id=%s""",
                    (
                        record.remote_name,
                        record.display_name,
                        record.namespace_type,
                        record.available,
                        record.system_database,
                        Jsonb(record.metadata),
                        record.id,
                    ),
                )
                if cursor.rowcount == 0:
                    raise DataSourceRepositoryError("数据库不存在")
        except psycopg.errors.UniqueViolation as exc:
            raise DataSourceRepositoryError("该数据源下已经存在同名数据库") from exc
        except DataSourceRepositoryError:
            raise
        except psycopg.Error as exc:
            raise DataSourceRepositoryError("数据库更新失败") from exc

    def delete_database(self, database_id: str) -> None:
        self._delete("data_source_databases", database_id, "数据库不存在", "数据库删除失败")

    def sync_databases(self, data_source_id: str, records: list[DataSourceDatabaseRecord]) -> None:
        database_names = [record.remote_name for record in records]
        try:
            with psycopg.connect(self._database_url) as connection:
                if database_names:
                    connection.execute(
                        """UPDATE data_source_databases
                        SET available=false, updated_at=CURRENT_TIMESTAMP
                        WHERE data_source_id=%s AND NOT (remote_name=ANY(%s))""",
                        (data_source_id, database_names),
                    )
                for record in records:
                    connection.execute(
                        """INSERT INTO data_source_databases
                        (id, data_source_id, remote_name, display_name, namespace_type,
                         available, system_database, metadata)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (data_source_id, remote_name) DO UPDATE SET
                          namespace_type=EXCLUDED.namespace_type,
                          available=EXCLUDED.available,
                          system_database=EXCLUDED.system_database,
                          metadata=EXCLUDED.metadata,
                          updated_at=CURRENT_TIMESTAMP""",
                        (
                            record.id,
                            record.data_source_id,
                            record.remote_name,
                            record.display_name,
                            record.namespace_type,
                            record.available,
                            record.system_database,
                            Jsonb(record.metadata),
                        ),
                    )
        except psycopg.errors.ForeignKeyViolation as exc:
            raise DataSourceRepositoryError("数据源不存在") from exc
        except psycopg.Error as exc:
            raise DataSourceRepositoryError("数据库清单同步失败") from exc

    def list_links(
        self, *, project_id: str | None = None, database_id: str | None = None
    ) -> list[ProjectDatabaseLinkRecord]:
        where: list[str] = []
        params: list[str] = []
        if project_id is not None:
            where.append("link.project_id=%s")
            params.append(project_id)
        if database_id is not None:
            where.append("link.database_id=%s")
            params.append(database_id)
        suffix = (" WHERE " + " AND ".join(where)) if where else ""
        with self._connect("项目数据库关联读取失败") as connection:
            rows = connection.execute(
                self._link_select() + suffix + " ORDER BY link.created_at, link.id", params
            ).fetchall()
        return [self._link_record(row) for row in rows]

    def get_project_database_by_alias(
        self, *, project_id: str, mcp_alias: str
    ) -> ResolvedProjectDatabase:
        with self._connect("项目数据库关联读取失败") as connection:
            row = connection.execute(
                self._resolved_select()
                + " WHERE link.project_id=%s AND lower(link.mcp_alias)=lower(%s)",
                (project_id, mcp_alias),
            ).fetchone()
        if row is None:
            raise DataSourceRepositoryError("项目数据库不存在")
        return self._resolved_record(row)

    def get_database_by_link_id(self, link_id: str) -> ResolvedProjectDatabase:
        with self._connect("项目数据库关联读取失败") as connection:
            row = connection.execute(
                self._resolved_select() + " WHERE link.id=%s",
                (link_id,),
            ).fetchone()
        if row is None:
            raise DataSourceRepositoryError("项目数据库不存在")
        return self._resolved_record(row)

    def list_project_databases_for_mcp(self, project_id: str) -> list[ResolvedProjectDatabase]:
        with self._connect("项目数据库关联读取失败") as connection:
            rows = connection.execute(
                self._resolved_select()
                + " WHERE link.project_id=%s AND link.mcp_alias IS NOT NULL"
                + " ORDER BY lower(link.mcp_alias), link.id",
                (project_id,),
            ).fetchall()
        return [self._resolved_record(row) for row in rows]

    def get_workspace_database_by_alias(
        self, *, workspace_id: str, mcp_alias: str
    ) -> ResolvedProjectDatabase:
        with self._connect("工作空间数据库关联读取失败") as connection:
            row = connection.execute(
                self._resolved_select()
                + " WHERE link.workspace_id=%s AND lower(link.mcp_alias)=lower(%s)",
                (workspace_id, mcp_alias),
            ).fetchone()
        if row is None:
            raise DataSourceRepositoryError("工作空间数据库不存在")
        return self._resolved_record(row)

    def list_workspace_databases_for_mcp(self, workspace_id: str) -> list[ResolvedProjectDatabase]:
        with self._connect("工作空间数据库关联读取失败") as connection:
            rows = connection.execute(
                self._resolved_select()
                + " WHERE link.workspace_id=%s AND link.mcp_alias IS NOT NULL"
                + " ORDER BY lower(link.mcp_alias), link.id",
                (workspace_id,),
            ).fetchall()
        return [self._resolved_record(row) for row in rows]

    def get_workspace_data_source_summary(
        self,
        workspace_id: str,
        *,
        workspace_enabled: bool | None = None,
    ) -> WorkspaceDataSourceSummaryRecord:
        with self._connect("工作空间数据源汇总读取失败") as connection:
            workspace_row = connection.execute(
                "SELECT enabled FROM workspaces WHERE id=%s",
                (workspace_id,),
            ).fetchone()
            if workspace_row is None:
                raise DataSourceRepositoryError("工作空间不存在")
            resolved_workspace_enabled = bool(workspace_row[0])
            rows = connection.execute(
                """SELECT
                source.id, source.name, source.category, source.engine, source.enabled,
                link.id, project.id, project.name, project.project_kind,
                database.id, database.remote_name, database.display_name,
                database.available, database.system_database,
                link.mcp_alias, link.alias, link.purpose, link.enabled, link.readonly
                FROM document_projects AS project
                JOIN project_databases AS link ON link.project_id=project.id
                JOIN data_source_databases AS database ON database.id=link.database_id
                JOIN data_sources AS source ON source.id=database.data_source_id
                WHERE project.workspace_id=%s
                ORDER BY source.name, source.id, project.name, project.id,
                         database.remote_name, database.id, link.id""",
                (workspace_id,),
            ).fetchall()

        assignments: list[
            tuple[_WorkspaceDataSourceIdentity, WorkspaceDataSourceAssignmentRecord]
        ] = []
        for row in rows:
            source = _WorkspaceDataSourceIdentity(
                id=str(row[0]),
                name=str(row[1]),
                category=str(row[2]),
                engine=str(row[3]),
                enabled=bool(row[4]),
            )
            database_available = bool(row[12])
            database_system = bool(row[13])
            mcp_alias = str(row[14]) if row[14] is not None else None
            link_enabled = bool(row[17])
            readonly = bool(row[18])
            assignment = WorkspaceDataSourceAssignmentRecord(
                link_id=str(row[5]),
                project_id=str(row[6]),
                project_name=str(row[7]),
                project_kind=str(row[8]),
                database_id=str(row[9]),
                database_name=str(row[10]),
                database_display_name=str(row[11]),
                mcp_alias=mcp_alias,
                alias=str(row[15]),
                purpose=str(row[16]),
                status=_workspace_assignment_status(
                    workspace_enabled=resolved_workspace_enabled,
                    source_enabled=source.enabled,
                    database_available=database_available,
                    database_system=database_system,
                    link_enabled=link_enabled,
                    readonly=readonly,
                    mcp_alias=mcp_alias,
                ),
                workspace_enabled=resolved_workspace_enabled,
                link_enabled=link_enabled,
                readonly=readonly,
                database_available=database_available,
                database_system=database_system,
                source_enabled=source.enabled,
            )
            assignments.append((source, assignment))
        return _workspace_data_source_summary(
            workspace_id=workspace_id,
            workspace_enabled=resolved_workspace_enabled,
            assignments=assignments,
        )

    def create_link(self, record: ProjectDatabaseLinkRecord) -> ProjectDatabaseLinkRecord:
        database = self.get_database(record.database_id)
        try:
            with psycopg.connect(self._database_url) as connection:
                project_row = connection.execute(
                    "SELECT workspace_id FROM document_projects WHERE id=%s FOR UPDATE",
                    (record.project_id,),
                ).fetchone()
                if project_row is None:
                    raise DataSourceRepositoryError("项目不存在")
                workspace_id = str(project_row[0])
                used_aliases = {
                    str(row[0]).casefold()
                    for row in connection.execute(
                        """SELECT mcp_alias FROM project_databases
                        WHERE workspace_id=%s AND mcp_alias IS NOT NULL""",
                        (workspace_id,),
                    ).fetchall()
                }
                saved_record = _prepare_link_alias(
                    replace(record, workspace_id=workspace_id),
                    database=database,
                    used_aliases=used_aliases,
                )
                connection.execute(
                    """INSERT INTO project_databases
                    (id, workspace_id, project_id, database_id, alias, mcp_alias,
                     purpose, enabled, readonly,
                     allowed_schemas, max_rows, max_result_bytes, query_timeout_ms)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        saved_record.id,
                        workspace_id,
                        saved_record.project_id,
                        saved_record.database_id,
                        saved_record.alias,
                        saved_record.mcp_alias,
                        saved_record.purpose,
                        saved_record.enabled,
                        saved_record.readonly,
                        Jsonb(saved_record.allowed_schemas),
                        saved_record.max_rows,
                        saved_record.max_result_bytes,
                        saved_record.query_timeout_ms,
                    ),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise DataSourceRepositoryError(self._link_unique_error(exc)) from exc
        except psycopg.errors.ForeignKeyViolation as exc:
            raise DataSourceRepositoryError("项目或数据库不存在") from exc
        except DataSourceRepositoryError:
            raise
        except psycopg.Error as exc:
            raise DataSourceRepositoryError("项目数据库关联写入失败") from exc
        return saved_record

    def update_link(self, record: ProjectDatabaseLinkRecord) -> ProjectDatabaseLinkRecord:
        database = self.get_database(record.database_id)
        try:
            with psycopg.connect(self._database_url) as connection:
                project_row = connection.execute(
                    "SELECT workspace_id FROM document_projects WHERE id=%s FOR UPDATE",
                    (record.project_id,),
                ).fetchone()
                if project_row is None:
                    raise DataSourceRepositoryError("项目不存在")
                workspace_id = str(project_row[0])
                used_aliases = {
                    str(row[0]).casefold()
                    for row in connection.execute(
                        """SELECT mcp_alias FROM project_databases
                        WHERE workspace_id=%s AND id<>%s AND mcp_alias IS NOT NULL""",
                        (workspace_id, record.id),
                    ).fetchall()
                }
                saved_record = _prepare_link_alias(
                    replace(record, workspace_id=workspace_id),
                    database=database,
                    used_aliases=used_aliases,
                )
                cursor = connection.execute(
                    """UPDATE project_databases SET workspace_id=%s, project_id=%s,
                    alias=%s, mcp_alias=%s, purpose=%s, enabled=%s, readonly=%s,
                    allowed_schemas=%s, max_rows=%s, max_result_bytes=%s, query_timeout_ms=%s,
                    updated_at=CURRENT_TIMESTAMP WHERE id=%s""",
                    (
                        workspace_id,
                        saved_record.project_id,
                        saved_record.alias,
                        saved_record.mcp_alias,
                        saved_record.purpose,
                        saved_record.enabled,
                        saved_record.readonly,
                        Jsonb(saved_record.allowed_schemas),
                        saved_record.max_rows,
                        saved_record.max_result_bytes,
                        saved_record.query_timeout_ms,
                        saved_record.id,
                    ),
                )
                if cursor.rowcount == 0:
                    raise DataSourceRepositoryError("项目数据库关联不存在")
        except psycopg.errors.UniqueViolation as exc:
            raise DataSourceRepositoryError(self._link_unique_error(exc)) from exc
        except DataSourceRepositoryError:
            raise
        except psycopg.Error as exc:
            raise DataSourceRepositoryError("项目数据库关联更新失败") from exc
        return saved_record

    def delete_link(self, link_id: str) -> None:
        self._delete("project_databases", link_id, "项目数据库关联不存在", "项目数据库关联删除失败")

    def replace_project_links(
        self, project_id: str, records: list[ProjectDatabaseLinkRecord]
    ) -> list[ProjectDatabaseLinkRecord]:
        if any(record.project_id != project_id for record in records):
            raise DataSourceRepositoryError("项目数据库关联不属于当前项目")
        if len({record.database_id for record in records}) != len(records):
            raise DataSourceRepositoryError("项目数据库关联中存在重复数据库")
        database_ids = [record.database_id for record in records]
        try:
            with psycopg.connect(self._database_url) as connection:
                project_row = connection.execute(
                    "SELECT workspace_id FROM document_projects WHERE id=%s FOR UPDATE",
                    (project_id,),
                ).fetchone()
                if project_row is None:
                    raise DataSourceRepositoryError("项目不存在")
                workspace_id = str(project_row[0])
                records = [replace(record, workspace_id=workspace_id) for record in records]
                if database_ids:
                    connection.execute(
                        """DELETE FROM project_databases
                        WHERE project_id=%s AND NOT (database_id=ANY(%s))""",
                        (project_id, database_ids),
                    )
                else:
                    connection.execute(
                        "DELETE FROM project_databases WHERE project_id=%s",
                        (project_id,),
                    )

                databases = self._load_databases_for_alias(connection, database_ids)
                if len(databases) != len(set(database_ids)):
                    raise DataSourceRepositoryError("项目或数据库不存在")
                used_aliases = {
                    str(row[0]).casefold()
                    for row in connection.execute(
                        """SELECT mcp_alias FROM project_databases
                        WHERE workspace_id=%s AND project_id<>%s
                          AND mcp_alias IS NOT NULL""",
                        (workspace_id, project_id),
                    ).fetchall()
                }
                saved_by_id: dict[str, ProjectDatabaseLinkRecord] = {}
                for record in records:
                    if record.mcp_alias is None:
                        continue
                    saved = _prepare_link_alias(
                        record,
                        database=databases[record.database_id],
                        used_aliases=used_aliases,
                    )
                    saved_by_id[record.id] = saved
                    used_aliases.add(_link_alias_key(saved))
                for record in records:
                    if record.id in saved_by_id:
                        continue
                    saved = _prepare_link_alias(
                        record,
                        database=databases[record.database_id],
                        used_aliases=used_aliases,
                    )
                    saved_by_id[record.id] = saved
                    used_aliases.add(_link_alias_key(saved))

                saved_records = [saved_by_id[record.id] for record in records]
                connection.execute(
                    "UPDATE project_databases SET mcp_alias=NULL WHERE project_id=%s",
                    (project_id,),
                )
                for saved_record in saved_records:
                    connection.execute(
                        """INSERT INTO project_databases
                        (id, workspace_id, project_id, database_id, alias, mcp_alias,
                         purpose, enabled, readonly,
                         allowed_schemas, max_rows, max_result_bytes, query_timeout_ms)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (project_id, database_id) DO UPDATE SET
                          workspace_id=EXCLUDED.workspace_id,
                          mcp_alias=EXCLUDED.mcp_alias""",
                        (
                            saved_record.id,
                            workspace_id,
                            saved_record.project_id,
                            saved_record.database_id,
                            saved_record.alias,
                            saved_record.mcp_alias,
                            saved_record.purpose,
                            saved_record.enabled,
                            saved_record.readonly,
                            Jsonb(saved_record.allowed_schemas),
                            saved_record.max_rows,
                            saved_record.max_result_bytes,
                            saved_record.query_timeout_ms,
                        ),
                    )
        except psycopg.errors.UniqueViolation as exc:
            raise DataSourceRepositoryError(self._link_unique_error(exc)) from exc
        except psycopg.errors.ForeignKeyViolation as exc:
            raise DataSourceRepositoryError("项目或数据库不存在") from exc
        except DataSourceRepositoryError:
            raise
        except psycopg.Error as exc:
            raise DataSourceRepositoryError("项目数据库关联批量更新失败") from exc
        return saved_records

    def _delete(self, table: str, record_id: str, missing: str, failed: str) -> None:
        try:
            with psycopg.connect(self._database_url) as connection:
                cursor = connection.execute(f"DELETE FROM {table} WHERE id=%s", (record_id,))
                if cursor.rowcount == 0:
                    raise DataSourceRepositoryError(missing)
        except DataSourceRepositoryError:
            raise
        except psycopg.Error as exc:
            raise DataSourceRepositoryError(failed) from exc

    def _connect(self, message: str):
        try:
            return psycopg.connect(self._database_url)
        except psycopg.Error as exc:
            raise DataSourceRepositoryError(message) from exc

    @staticmethod
    def _load_databases_for_alias(
        connection: psycopg.Connection[Any], database_ids: list[str]
    ) -> dict[str, DataSourceDatabaseRecord]:
        if not database_ids:
            return {}
        rows = connection.execute(
            """SELECT id, data_source_id, remote_name, display_name, namespace_type,
            available, system_database, metadata, created_at, updated_at
            FROM data_source_databases WHERE id=ANY(%s)""",
            (database_ids,),
        ).fetchall()
        return {
            str(row[0]): DataSourceDatabaseRecord(
                id=str(row[0]),
                data_source_id=str(row[1]),
                remote_name=str(row[2]),
                display_name=str(row[3]),
                namespace_type=str(row[4]),
                available=bool(row[5]),
                system_database=bool(row[6]),
                metadata=dict(row[7]),
                project_count=0,
                created_at=row[8],
                updated_at=row[9],
            )
            for row in rows
        }

    @staticmethod
    def _link_unique_error(exc: psycopg.errors.UniqueViolation) -> str:
        if exc.diag.constraint_name == "uq_project_databases_workspace_mcp_alias":
            return "工作空间内 MCP 数据库别名已存在"
        return "项目已经关联这个数据库"

    @staticmethod
    def _source_select() -> str:
        return """SELECT source.id, source.name, source.category, source.engine,
        source.description, source.connection_config, source.enabled, source.config_version,
        COUNT(DISTINCT database.id), COUNT(DISTINCT link.project_id),
        source.created_at, source.updated_at
        FROM data_sources AS source
        LEFT JOIN data_source_databases AS database ON database.data_source_id=source.id
        LEFT JOIN project_databases AS link ON link.database_id=database.id"""

    @staticmethod
    def _database_select() -> str:
        return """SELECT database.id, database.data_source_id, database.remote_name,
        database.display_name, database.namespace_type, database.available,
        database.system_database, database.metadata, COUNT(link.id),
        database.created_at, database.updated_at
        FROM data_source_databases AS database
        LEFT JOIN project_databases AS link ON link.database_id=database.id"""

    @staticmethod
    def _link_select() -> str:
        return """SELECT link.id, link.project_id, project.name, link.database_id,
        database.remote_name, source.id, source.name, source.engine, link.alias,
        link.mcp_alias, link.purpose, link.enabled, link.readonly, link.allowed_schemas,
        link.max_rows, link.max_result_bytes, link.query_timeout_ms,
        link.created_at, link.updated_at, link.workspace_id, workspace.enabled,
        project.project_kind
        FROM project_databases AS link
        JOIN document_projects AS project ON project.id=link.project_id
        JOIN workspaces AS workspace ON workspace.id=link.workspace_id
        JOIN data_source_databases AS database ON database.id=link.database_id
        JOIN data_sources AS source ON source.id=database.data_source_id"""

    @staticmethod
    def _resolved_select() -> str:
        return """SELECT
        link.id, link.workspace_id, workspace.enabled, link.project_id,
        project.name, project.project_kind, link.mcp_alias, link.alias, link.purpose,
        link.enabled, link.readonly, link.allowed_schemas, link.max_rows,
        link.max_result_bytes, link.query_timeout_ms, link.created_at, link.updated_at,
        database.id, database.remote_name, database.display_name,
        database.namespace_type, database.available, database.system_database,
        database.metadata, database.created_at, database.updated_at,
        source.id, source.name, source.category, source.engine, source.description,
        source.connection_config, source.enabled, source.config_version,
        source.created_at, source.updated_at
        FROM project_databases AS link
        JOIN document_projects AS project ON project.id=link.project_id
        JOIN workspaces AS workspace ON workspace.id=link.workspace_id
        JOIN data_source_databases AS database ON database.id=link.database_id
        JOIN data_sources AS source ON source.id=database.data_source_id"""

    @staticmethod
    def _source_record(row: tuple[object, ...]) -> DataSourceRecord:
        return DataSourceRecord(
            str(row[0]),
            str(row[1]),
            str(row[2]),
            str(row[3]),
            str(row[4]),
            dict(row[5]),
            bool(row[6]),
            int(row[7]),
            int(row[8]),
            int(row[9]),
            row[10],
            row[11],
        )

    @staticmethod
    def _database_record(row: tuple[object, ...]) -> DataSourceDatabaseRecord:
        return DataSourceDatabaseRecord(
            str(row[0]),
            str(row[1]),
            str(row[2]),
            str(row[3]),
            str(row[4]),
            bool(row[5]),
            bool(row[6]),
            dict(row[7]),
            int(row[8]),
            row[9],
            row[10],
        )

    @staticmethod
    def _link_record(row: tuple[object, ...]) -> ProjectDatabaseLinkRecord:
        return ProjectDatabaseLinkRecord(
            str(row[0]),
            str(row[1]),
            str(row[2]),
            str(row[3]),
            str(row[4]),
            str(row[5]),
            str(row[6]),
            str(row[7]),
            str(row[8]),
            str(row[9]) if row[9] is not None else None,
            str(row[10]),
            bool(row[11]),
            bool(row[12]),
            list(row[13]),
            int(row[14]),
            int(row[15]),
            int(row[16]),
            row[17],
            row[18],
            workspace_id=str(row[19]),
            workspace_enabled=bool(row[20]),
            project_kind=str(row[21]),
        )

    @staticmethod
    def _resolved_record(row: tuple[object, ...]) -> ResolvedProjectDatabase:
        if row[6] is None:
            raise DataSourceRepositoryError("项目数据库尚未配置 MCP 别名")
        return ResolvedProjectDatabase(
            link_id=str(row[0]),
            workspace_id=str(row[1]),
            workspace_enabled=bool(row[2]),
            project_id=str(row[3]),
            project_name=str(row[4]),
            project_kind=str(row[5]),
            mcp_alias=str(row[6]),
            alias=str(row[7]),
            purpose=str(row[8]),
            link_enabled=bool(row[9]),
            readonly=bool(row[10]),
            allowed_schemas=list(row[11]),
            max_rows=int(row[12]),
            max_result_bytes=int(row[13]),
            query_timeout_ms=int(row[14]),
            link_created_at=row[15],
            link_updated_at=row[16],
            database_id=str(row[17]),
            database_remote_name=str(row[18]),
            database_display_name=str(row[19]),
            namespace_type=str(row[20]),
            database_available=bool(row[21]),
            database_system=bool(row[22]),
            database_metadata=dict(row[23]),
            database_created_at=row[24],
            database_updated_at=row[25],
            data_source_id=str(row[26]),
            data_source_name=str(row[27]),
            data_source_category=str(row[28]),
            engine=str(row[29]),
            data_source_description=str(row[30]),
            connection_config=dict(row[31]),
            source_enabled=bool(row[32]),
            config_version=int(row[33]),
            source_created_at=row[34],
            source_updated_at=row[35],
        )
