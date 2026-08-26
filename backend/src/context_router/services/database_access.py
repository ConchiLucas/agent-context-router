from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal, cast

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
from context_router.repositories.database_environment_repository import (
    DatabaseEnvironment,
    DatabaseEnvironmentConfigRecord,
    DatabaseEnvironmentRepositoryError,
    DatabaseEnvironmentStore,
)
from context_router.repositories.task_repository import TaskReader, TaskRepositoryError
from context_router.schemas.context import PreparedDatabase
from context_router.services.local_workspace_mapping import (
    LocalWorkspaceMappingError,
    LocalWorkspaceMappingService,
)
from context_router.services.project_registry import ProjectRegistry, ProjectRegistryError

DatabaseEnvironmentSelection = Literal["workspace_default", "task_explicit", "task_description"]


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
        database_environment_repository: DatabaseEnvironmentStore | None = None,
        local_mapping: LocalWorkspaceMappingService | None = None,
    ) -> None:
        self._settings = settings
        self._registry = registry
        self._task_repository = task_repository
        self._data_source_repository = data_source_repository
        self._connector_registry = connector_registry
        self._database_environment_repository = database_environment_repository
        self._local_mapping = local_mapping
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
            raise DatabaseAccessError("database_not_found", "当前工作空间没有这个数据库别名")
        try:
            task = self._task_repository.get_task(task_id)
        except TaskRepositoryError as exc:
            raise DatabaseAccessError("task_not_found", "任务不存在，请重新 prepare") from exc
        if getattr(task, "scope", "project") == "workspace":
            workspace_id = getattr(task, "workspace_id", None)
            workspace_key = getattr(task, "workspace_key", None)
            if not workspace_id:
                raise DatabaseAccessError(
                    "workspace_unavailable",
                    "任务缺少工作空间快照，请重新 prepare",
                )
            if self._local_mapping is not None:
                try:
                    self._local_mapping.require_full_access(
                        cwd=task.cwd,
                        workspace_id=workspace_id,
                    )
                except LocalWorkspaceMappingError as exc:
                    raise DatabaseAccessError("documents_only", str(exc)) from exc
            try:
                self._registry.get_workspace_snapshot_for_task(
                    workspace_id=workspace_id,
                    workspace_key=workspace_key,
                )
            except ProjectRegistryError as exc:
                raise DatabaseAccessError(
                    "workspace_unavailable",
                    "任务绑定的工作空间当前不可用，请重新 prepare",
                ) from exc
            database = self._resolve_workspace_database(
                workspace_id=workspace_id,
                mcp_alias=normalized_alias,
                task_environment=task.database_environment,
                task_environment_revision=task.database_environment_revision,
                database_environment_selection=task.database_environment_selection,
            )
        else:
            try:
                project = self._registry.get_snapshot_for_task(
                    project_id=task.project_id,
                    project_key=task.project_key,
                )
            except ProjectRegistryError as exc:
                raise DatabaseAccessError(
                    "project_unavailable",
                    "任务绑定的项目当前不可用，请重新 prepare",
                ) from exc
            if (
                project.workspace_id is not None
                and self.get_active_workspace_environment(project.workspace_id) is not None
            ):
                raise DatabaseAccessError(
                    "environment_changed",
                    "工作空间已配置环境，旧项目任务请重新 prepare",
                )
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

    def resolve_workspace_database(
        self,
        *,
        workspace_id: str,
        environment: str,
        mcp_alias: str,
        object_type: DatabaseObjectType | None = None,
        require_query: bool = False,
    ) -> ResolvedDatabaseAccess:
        """Resolve a browser read against an explicit Workspace environment.

        Unlike MCP database calls this path has no task snapshot.  It is only
        used by constrained, server-generated read views, so the caller must
        provide the environment explicitly and still receives the same
        availability, capability, and hard-limit policy checks as an MCP call.
        """
        if not self._settings.database_tools_enabled:
            raise DatabaseAccessError("database_tools_disabled", "数据库工具当前已关闭")
        alias = mcp_alias.strip().casefold()
        selected_environment = environment.strip().casefold()
        if not alias:
            raise DatabaseAccessError("database_not_found", "当前工作空间没有这个数据库别名")
        if not selected_environment or not self.has_workspace_environment(
            workspace_id, selected_environment
        ):
            raise DatabaseAccessError("environment_changed", "工作空间没有配置所选环境")

        selector = self.get_active_workspace_environment(workspace_id)
        database = self._resolve_workspace_database(
            workspace_id=workspace_id,
            mcp_alias=alias,
            task_environment=selected_environment if selector is not None else None,
            task_environment_revision=selector.revision if selector is not None else None,
            database_environment_selection="task_explicit" if selector is not None else None,
        )
        self._ensure_available(database)
        try:
            capabilities = self._connector_registry.capabilities(database.engine)
        except ConnectorRegistryError as exc:
            raise DatabaseAccessError(exc.code, "这个数据库类型暂不支持只读查询") from exc
        if require_query and not capabilities.execute_readonly_query:
            raise DatabaseAccessError("engine_not_supported", "这个数据库暂不支持只读查询")
        if object_type is not None and not capabilities.supports_object_type(object_type):
            raise DatabaseAccessError("engine_not_supported", "这个数据库暂不支持所请求的对象类型")
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

        return self._prepare_database_records(records)

    def get_active_database_environment(
        self,
        workspace_id: str,
    ) -> DatabaseEnvironmentConfigRecord | None:
        config = self.get_active_workspace_environment(workspace_id)
        if config is None or not self._database_mappings_configured(workspace_id):
            return None
        return config

    def get_active_workspace_environment(
        self,
        workspace_id: str,
    ) -> DatabaseEnvironmentConfigRecord | None:
        repository = self._database_environment_repository
        if repository is None:
            return None
        try:
            snapshot = repository.get_environment_snapshot(workspace_id)
        except DatabaseEnvironmentRepositoryError as exc:
            raise DatabaseAccessError(
                "database_environment_unavailable",
                "工作空间环境配置暂时不可用",
            ) from exc
        if not snapshot.selector_configured:
            return None
        config = snapshot.config
        if config.active_environment is None or config.revision < 1:
            raise DatabaseAccessError(
                "database_environment_unavailable",
                "工作空间环境配置不完整",
            )
        return config

    def has_workspace_environment(self, workspace_id: str, environment: str) -> bool:
        repository = self._database_environment_repository
        if repository is None:
            return environment == "local"
        has_environment = getattr(repository, "has_environment", None)
        if not callable(has_environment):
            # Compatibility for repository adapters created before dynamic
            # Workspace environments. Their saved task/config pair remains the
            # source of truth until the adapter is upgraded.
            return True
        try:
            return bool(has_environment(workspace_id, environment))
        except DatabaseEnvironmentRepositoryError as exc:
            raise DatabaseAccessError(
                "database_environment_unavailable",
                "工作空间环境配置暂时不可用",
            ) from exc

    def get_active_environment_payload(
        self,
        workspace_id: str,
        *,
        environment: DatabaseEnvironment,
        revision: int,
        database_environment_selection: DatabaseEnvironmentSelection | None = None,
    ) -> object:
        repository = self._database_environment_repository
        if repository is None:
            raise DatabaseAccessError(
                "database_environment_unavailable",
                "工作空间环境配置暂时不可用",
            )
        try:
            snapshot = repository.get_environment_snapshot(workspace_id)
        except DatabaseEnvironmentRepositoryError as exc:
            raise DatabaseAccessError(
                "database_environment_unavailable",
                "工作空间环境 JSON 暂时不可用",
            ) from exc
        config = snapshot.config if snapshot.selector_configured else None
        selected_environment = self._validated_task_environment(
            workspace_id,
            config,
            task_environment=environment,
            task_environment_revision=revision,
            database_environment_selection=database_environment_selection,
        )
        if selected_environment is None:
            raise DatabaseAccessError(
                "environment_changed",
                "任务缺少环境选择，请重新 prepare",
            )
        if selected_environment not in snapshot.payloads.environments:
            raise DatabaseAccessError(
                "environment_config_not_configured",
                "当前环境尚未维护通用环境 JSON",
            )
        return snapshot.payloads.environments[selected_environment]

    def validate_task_environment(
        self,
        workspace_id: str,
        *,
        task_environment: str | None,
        task_environment_revision: int | None,
        database_environment_selection: DatabaseEnvironmentSelection | None,
    ) -> DatabaseEnvironment | None:
        """Validate a task environment snapshot without reading any environment payload."""
        selector = self.get_active_workspace_environment(workspace_id)
        selected = self._validated_task_environment(
            workspace_id,
            selector,
            task_environment=task_environment,
            task_environment_revision=task_environment_revision,
            database_environment_selection=database_environment_selection,
        )
        if selector is not None and selected is None:
            raise DatabaseAccessError(
                "environment_changed",
                "工作空间已配置环境，请重新 prepare",
            )
        return selected

    def list_prepared_workspace_databases(
        self,
        workspace_id: str,
        *,
        database_environment: str | None = None,
        database_environment_revision: int | None = None,
        database_environment_selection: DatabaseEnvironmentSelection | None = None,
    ) -> list[PreparedDatabase]:
        if not self._settings.database_tools_enabled:
            return []
        selector = self.get_active_workspace_environment(workspace_id)
        selected_environment = self._validated_task_environment(
            workspace_id,
            selector,
            task_environment=database_environment,
            task_environment_revision=database_environment_revision,
            database_environment_selection=database_environment_selection,
        )
        if selected_environment is None and selector is not None:
            selected_environment = selector.active_environment

        if selector is not None and self._database_mappings_configured(workspace_id):
            if selected_environment is None:
                raise DatabaseAccessError(
                    "environment_changed",
                    "任务缺少环境选择，请重新 prepare",
                )
            records = self._list_environment_database_records(
                workspace_id=workspace_id,
                environment=selected_environment,
            )
            return self._prepare_database_records(
                records,
                environment=selected_environment,
            )
        try:
            records = self._data_source_repository.list_workspace_databases_for_mcp(workspace_id)
        except DataSourceRepositoryError as exc:
            raise DatabaseAccessError(
                "database_summary_unavailable",
                "工作空间数据库摘要暂时不可用",
            ) from exc
        return self._prepare_database_records(records)

    def list_task_workspace_databases(
        self,
        workspace_id: str,
        *,
        database_environment: str | None = None,
        database_environment_revision: int | None = None,
        database_environment_selection: DatabaseEnvironmentSelection | None = None,
    ) -> list[ResolvedProjectDatabase]:
        """Resolve the physical database records authorized by a task environment snapshot."""
        selector = self.get_active_workspace_environment(workspace_id)
        selected_environment = self._validated_task_environment(
            workspace_id,
            selector,
            task_environment=database_environment,
            task_environment_revision=database_environment_revision,
            database_environment_selection=database_environment_selection,
        )
        if selected_environment is None and selector is not None:
            raise DatabaseAccessError(
                "environment_changed",
                "任务缺少环境选择，请重新 prepare",
            )
        if selector is not None and self._database_mappings_configured(workspace_id):
            if selected_environment is None:  # pragma: no cover - guarded above
                raise DatabaseAccessError(
                    "environment_changed",
                    "任务缺少环境选择，请重新 prepare",
                )
            return self._list_environment_database_records(
                workspace_id=workspace_id,
                environment=selected_environment,
            )
        try:
            return self._data_source_repository.list_workspace_databases_for_mcp(workspace_id)
        except DataSourceRepositoryError as exc:
            raise DatabaseAccessError(
                "database_summary_unavailable",
                "工作空间数据库摘要暂时不可用",
            ) from exc

    def _prepare_database_records(
        self,
        records: list[ResolvedProjectDatabase],
        *,
        environment: str | None = None,
    ) -> list[PreparedDatabase]:
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
                    project_id=record.project_id,
                    project_name=record.project_name,
                    project_kind=record.project_kind,
                    environment=environment,
                )
            )
        return prepared

    def _resolve_workspace_database(
        self,
        *,
        workspace_id: str,
        mcp_alias: str,
        task_environment: str | None,
        task_environment_revision: int | None,
        database_environment_selection: DatabaseEnvironmentSelection | None,
    ) -> ResolvedProjectDatabase:
        config = self.get_active_workspace_environment(workspace_id)
        selected_environment = self._validated_task_environment(
            workspace_id,
            config,
            task_environment=task_environment,
            task_environment_revision=task_environment_revision,
            database_environment_selection=database_environment_selection,
        )
        if selected_environment is None:
            if config is not None:
                raise DatabaseAccessError(
                    "environment_changed",
                    "工作空间已配置环境，请重新 prepare",
                )
            try:
                return self._data_source_repository.get_workspace_database_by_alias(
                    workspace_id=workspace_id,
                    mcp_alias=mcp_alias,
                )
            except DataSourceRepositoryError as exc:
                raise DatabaseAccessError(
                    "database_not_found",
                    "当前工作空间没有这个数据库别名",
                ) from exc

        if config is None:
            raise DatabaseAccessError(
                "environment_changed",
                "工作空间环境配置已变化，请重新 prepare",
            )
        if not self._database_mappings_configured(workspace_id):
            try:
                return self._data_source_repository.get_workspace_database_by_alias(
                    workspace_id=workspace_id,
                    mcp_alias=mcp_alias,
                )
            except DataSourceRepositoryError as exc:
                raise DatabaseAccessError(
                    "database_not_found",
                    "当前工作空间没有这个数据库别名",
                ) from exc
        repository = self._database_environment_repository
        if repository is None:
            raise DatabaseAccessError(
                "database_environment_unavailable",
                "数据库环境映射暂时不可用",
            )
        try:
            target = repository.resolve_mapping(
                workspace_id=workspace_id,
                environment=selected_environment,
                mcp_alias=mcp_alias,
            )
            database = self._data_source_repository.get_database_by_link_id(target.link_id)
        except DatabaseEnvironmentRepositoryError as exc:
            raise DatabaseAccessError(
                "database_not_found",
                "当前环境没有这个数据库别名",
            ) from exc
        except DataSourceRepositoryError as exc:
            raise DatabaseAccessError(
                "database_not_found",
                "当前环境映射的数据库授权不存在",
            ) from exc
        return self._logical_database_record(
            database,
            workspace_id=workspace_id,
            project_id=target.project_id,
            mcp_alias=target.mcp_alias,
            logical_name=target.logical_name,
        )

    def _list_environment_database_records(
        self,
        *,
        workspace_id: str,
        environment: DatabaseEnvironment,
    ) -> list[ResolvedProjectDatabase]:
        repository = self._database_environment_repository
        if repository is None:
            raise DatabaseAccessError(
                "database_environment_unavailable",
                "数据库环境映射暂时不可用",
            )
        try:
            targets = repository.list_mapping_targets(
                workspace_id=workspace_id,
                environment=environment,
            )
            records = [
                self._logical_database_record(
                    self._data_source_repository.get_database_by_link_id(target.link_id),
                    workspace_id=workspace_id,
                    project_id=target.project_id,
                    mcp_alias=target.mcp_alias,
                    logical_name=target.logical_name,
                )
                for target in targets
            ]
        except DatabaseEnvironmentRepositoryError as exc:
            raise DatabaseAccessError(
                "database_summary_unavailable",
                "工作空间数据库环境摘要暂时不可用",
            ) from exc
        except DataSourceRepositoryError as exc:
            raise DatabaseAccessError(
                "database_summary_unavailable",
                "工作空间数据库授权摘要暂时不可用",
            ) from exc
        return sorted(records, key=lambda item: (item.mcp_alias.casefold(), item.link_id))

    def _validated_task_environment(
        self,
        workspace_id: str,
        selector: DatabaseEnvironmentConfigRecord | None,
        *,
        task_environment: str | None,
        task_environment_revision: int | None,
        database_environment_selection: DatabaseEnvironmentSelection | None,
    ) -> DatabaseEnvironment | None:
        selection = database_environment_selection
        if selection is None:
            if task_environment is None:
                if task_environment_revision is not None:
                    raise DatabaseAccessError(
                        "environment_changed",
                        "任务环境快照不完整，请重新 prepare",
                    )
                return None
            selection = "workspace_default"
        elif selection not in {"workspace_default", "task_explicit", "task_description"}:
            raise DatabaseAccessError(
                "environment_changed",
                "任务环境选择模式无效，请重新 prepare",
            )

        if (
            task_environment is None
            or task_environment_revision is None
            or selector is None
            or selector.revision != task_environment_revision
        ):
            raise DatabaseAccessError(
                "environment_changed",
                "环境已切换或配置已更新，请重新 prepare",
            )
        if selection == "workspace_default" and selector.active_environment != task_environment:
            raise DatabaseAccessError(
                "environment_changed",
                "环境已切换或配置已更新，请重新 prepare",
            )
        if not self.has_workspace_environment(workspace_id, task_environment):
            raise DatabaseAccessError(
                "environment_changed",
                "工作空间已删除该环境，请重新 prepare",
            )
        return cast(DatabaseEnvironment, task_environment)

    def list_workspace_environments(self, workspace_id: str):
        repository = self._database_environment_repository
        if repository is None:
            return []
        try:
            return repository.list_environments(workspace_id)
        except DatabaseEnvironmentRepositoryError as exc:
            raise DatabaseAccessError(
                "database_environment_unavailable",
                "工作空间环境配置暂时不可用",
            ) from exc

    def _current_environment_config(
        self,
        workspace_id: str,
    ) -> DatabaseEnvironmentConfigRecord | None:
        repository = self._database_environment_repository
        if repository is None:
            return None
        try:
            return repository.get_active_config(workspace_id)
        except DatabaseEnvironmentRepositoryError as exc:
            raise DatabaseAccessError(
                "database_environment_unavailable",
                "工作空间数据库环境配置暂时不可用",
            ) from exc

    @staticmethod
    def _logical_database_record(
        database: ResolvedProjectDatabase,
        *,
        workspace_id: str,
        project_id: str,
        mcp_alias: str,
        logical_name: str,
    ) -> ResolvedProjectDatabase:
        if database.workspace_id != workspace_id or database.project_id != project_id:
            raise DatabaseAccessError(
                "database_not_available",
                "数据库环境映射与项目授权不一致",
            )
        return replace(
            database,
            mcp_alias=mcp_alias,
            alias=logical_name,
        )

    @classmethod
    def _ensure_available(cls, database: ResolvedProjectDatabase) -> None:
        if not cls._is_available(database):
            raise DatabaseAccessError(
                "database_not_available",
                "这个数据库当前不可用于 MCP 只读查询",
            )

    @staticmethod
    def _is_available(database: ResolvedProjectDatabase) -> bool:
        return bool(
            database.readonly
            and database.database_available
            and not database.database_system
            and database.mcp_alias
        )

    def _database_mappings_configured(self, workspace_id: str) -> bool:
        repository = self._database_environment_repository
        if repository is None:
            return False
        try:
            return bool(repository.list_mappings(workspace_id))
        except DatabaseEnvironmentRepositoryError as exc:
            raise DatabaseAccessError(
                "database_environment_unavailable",
                "工作空间数据库环境映射暂时不可用",
            ) from exc
