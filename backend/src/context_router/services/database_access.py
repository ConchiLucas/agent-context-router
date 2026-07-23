from __future__ import annotations

from dataclasses import dataclass

from context_router.config import Settings
from context_router.database.errors import DatabaseAccessError
from context_router.database.models import (
    ConnectorCapabilities,
    ConnectorSpec,
    DatabaseObjectType,
    EffectiveQueryPolicy,
)
from context_router.database.policy import (
    QueryPolicyError,
    QueryPolicyHardLimits,
    build_effective_policy,
)
from context_router.database.registry import ConnectorRegistry, ConnectorRegistryError
from context_router.repositories.data_source_repository import (
    DataSourceRepositoryError,
    DataSourceStore,
    ResolvedProjectDatabase,
)
from context_router.repositories.task_repository import TaskReader, TaskRepositoryError
from context_router.schemas.context import PreparedDatabase
from context_router.services.project_registry import ProjectRegistry, ProjectRegistryError


@dataclass(frozen=True, slots=True)
class ResolvedDatabaseAccess:
    database: ResolvedProjectDatabase
    spec: ConnectorSpec
    policy: EffectiveQueryPolicy
    capabilities: ConnectorCapabilities


class DatabaseAccessService:
    def __init__(
        self,
        *,
        settings: Settings,
        registry: ProjectRegistry,
        task_repository: TaskReader,
        data_source_repository: DataSourceStore,
        connector_registry: ConnectorRegistry,
    ) -> None:
        self._settings = settings
        self._registry = registry
        self._task_repository = task_repository
        self._data_source_repository = data_source_repository
        self._connector_registry = connector_registry
        self._hard_limits = QueryPolicyHardLimits(
            max_rows=settings.database_max_rows,
            max_result_bytes=settings.database_max_result_bytes,
            max_query_timeout_ms=settings.database_max_query_timeout_ms,
        )

    def resolve(
        self,
        *,
        task_id: int,
        mcp_alias: str,
        object_type: DatabaseObjectType | None = None,
        require_query: bool = False,
    ) -> ResolvedDatabaseAccess:
        if not self._settings.database_tools_enabled:
            raise DatabaseAccessError(
                "database_tools_disabled",
                "数据库工具当前已关闭",
            )
        normalized_alias = mcp_alias.strip().casefold()
        if not normalized_alias:
            raise DatabaseAccessError("database_not_found", "当前项目没有这个数据库别名")
        try:
            task = self._task_repository.get_task(task_id)
        except TaskRepositoryError as exc:
            raise DatabaseAccessError("task_not_found", "任务不存在，请重新 prepare") from exc
        try:
            project = self._registry.get_snapshot_by_project_key(task.project_key)
        except ProjectRegistryError as exc:
            raise DatabaseAccessError(
                "project_unavailable",
                "任务绑定的项目当前不可用，请重新 prepare",
            ) from exc
        try:
            database = self._data_source_repository.get_project_database_by_alias(
                project_id=project.id,
                mcp_alias=normalized_alias,
            )
        except DataSourceRepositoryError as exc:
            raise DatabaseAccessError(
                "database_not_found",
                "当前项目没有这个数据库别名",
            ) from exc

        self._ensure_available(database)
        try:
            capabilities = self._connector_registry.capabilities(database.engine)
        except ConnectorRegistryError as exc:
            raise DatabaseAccessError(exc.code, "这个数据库类型暂不支持 MCP 查询") from exc
        if require_query and not capabilities.execute_readonly_query:
            raise DatabaseAccessError("engine_not_supported", "这个数据库暂不支持只读查询")
        if object_type is not None and not capabilities.supports_object_type(object_type):
            raise DatabaseAccessError(
                "engine_not_supported",
                "这个数据库暂不支持所请求的对象类型",
            )

        try:
            policy = build_effective_policy(
                engine=database.engine,
                current_database=database.database_remote_name,
                readonly=database.readonly,
                allowed_schemas=database.allowed_schemas,
                max_rows=database.max_rows,
                max_result_bytes=database.max_result_bytes,
                query_timeout_ms=database.query_timeout_ms,
                hard_limits=self._hard_limits,
            )
        except QueryPolicyError as exc:
            raise DatabaseAccessError(exc.code, str(exc)) from exc

        return ResolvedDatabaseAccess(
            database=database,
            spec=ConnectorSpec(
                data_source_id=database.data_source_id,
                config_version=database.config_version,
                database_id=database.database_id,
                database_updated_at=database.database_updated_at,
                engine=database.engine,
                remote_name=database.database_remote_name,
                connection_config=database.connection_config,
            ),
            policy=policy,
            capabilities=capabilities,
        )

    def list_prepared_databases(self, project_id: str) -> list[PreparedDatabase]:
        if not self._settings.database_tools_enabled:
            return []
        try:
            records = self._data_source_repository.list_project_databases_for_mcp(project_id)
        except DataSourceRepositoryError as exc:
            raise DatabaseAccessError(
                "database_summary_unavailable",
                "项目数据库摘要暂时不可用",
            ) from exc

        prepared: list[PreparedDatabase] = []
        for record in records:
            if not self._is_available(record):
                continue
            try:
                capabilities = self._connector_registry.capabilities(record.engine)
            except ConnectorRegistryError:
                continue
            names: list[str] = []
            if any(
                (
                    capabilities.search_schemas,
                    capabilities.search_tables,
                    capabilities.search_views,
                    capabilities.search_columns,
                    capabilities.search_indexes,
                )
            ):
                names.append("search_objects")
            if capabilities.execute_readonly_query:
                names.append("execute_query")
            if not names:
                continue
            prepared.append(
                PreparedDatabase(
                    database=record.mcp_alias,
                    engine=record.engine,
                    name=record.database_display_name or record.database_remote_name,
                    purpose=record.purpose,
                    readonly=True,
                    capabilities=names,
                )
            )
        return prepared

    @classmethod
    def _ensure_available(cls, database: ResolvedProjectDatabase) -> None:
        if not cls._is_available(database):
            raise DatabaseAccessError(
                "database_not_available",
                "这个项目数据库当前不可用于 MCP 只读查询",
            )

    @staticmethod
    def _is_available(database: ResolvedProjectDatabase) -> bool:
        return bool(
            database.project_enabled
            and database.link_enabled
            and database.readonly
            and database.source_enabled
            and database.database_available
            and not database.database_system
            and database.mcp_alias
        )
