from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from context_router.repositories.data_source_repository import ResolvedProjectDatabase
from context_router.repositories.database_context_repository import (
    DatabaseContextRecord,
    DatabaseContextRepositoryError,
    DatabaseContextStore,
)
from context_router.repositories.task_repository import TaskRepositoryError, TaskStore
from context_router.services.database_access import (
    DatabaseAccessError,
    DatabaseAccessService,
    ResolvedDatabaseAccess,
)
from context_router.services.value_mapping import ValueMappingError, ValueMappingService


class DatabaseContextError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class DatabaseContextService:
    def __init__(
        self,
        *,
        contexts: DatabaseContextStore,
        tasks: TaskStore,
        access: DatabaseAccessService,
        value_mappings: ValueMappingService,
        ttl_minutes: int = 60,
    ) -> None:
        self._contexts = contexts
        self._tasks = tasks
        self._access = access
        self._value_mappings = value_mappings
        self._ttl = timedelta(minutes=max(5, ttl_minutes))

    def resolve_target(
        self,
        *,
        task_id: int,
        mapping_id: str | None,
        table_name: str | None,
        business_hint: str | None,
    ) -> dict[str, object]:
        task = self._task(task_id)
        if task.workspace_id is None or task.database_environment is None:
            raise DatabaseContextError(
                "task_database_context_unavailable",
                "任务没有可用的工作空间数据库环境，请重新 prepare",
            )

        if mapping_id:
            try:
                source = self._value_mappings.source_for_task(mapping_id, task_id=task_id)
            except ValueMappingError as exc:
                raise DatabaseContextError(exc.code, str(exc)) from exc
            context = self._create(
                task_id=task_id,
                database_alias=str(source["database_alias"]),
                source_type="value_mapping",
                source_id=mapping_id,
            )
            return {
                "task_id": task_id,
                "status": "resolved",
                "database_context_id": context.id,
                "environment": context.environment,
                "database": self._public_database(context),
                "source": {
                    "type": "value_mapping",
                    "id": mapping_id,
                    "schema_name": source["schema_name"],
                    "table_name": source["table_name"],
                },
            }

        try:
            records = self._access.list_task_workspace_databases(
                task.workspace_id,
                database_environment=task.database_environment,
                database_environment_revision=task.database_environment_revision,
                database_environment_selection=task.database_environment_selection,
            )
        except DatabaseAccessError as exc:
            raise DatabaseContextError(exc.code, str(exc)) from exc
        available = [
            record
            for record in records
            if record.mcp_alias
            and record.readonly
            and record.database_available
            and not record.database_system
        ]
        if not available:
            raise DatabaseContextError(
                "database_not_found",
                "当前任务环境没有可用的只读数据库",
            )
        query = " ".join(part.strip() for part in (table_name or "", business_hint or "") if part)
        folded_tokens = [token for token in query.casefold().replace("_", " ").split() if token]
        scored: list[tuple[int, ResolvedProjectDatabase]] = []
        for record in available:
            haystack = " ".join(
                (
                    record.mcp_alias,
                    record.alias,
                    record.purpose,
                    record.database_display_name,
                    record.project_name,
                )
            ).casefold()
            scored.append((sum(1 for token in folded_tokens if token in haystack), record))
        positive = [item for item in scored if item[0] > 0]
        candidates = positive if positive else scored
        candidates.sort(key=lambda item: (-item[0], item[1].mcp_alias))
        if len(candidates) == 1 or (
            candidates and len(candidates) > 1 and candidates[0][0] > candidates[1][0]
        ):
            selected = candidates[0][1]
            context = self._create(
                task_id=task_id,
                database_alias=selected.mcp_alias,
                source_type="task_database_resolution",
                source_id=None,
            )
            return {
                "task_id": task_id,
                "status": "resolved",
                "database_context_id": context.id,
                "environment": context.environment,
                "database": self._public_database(context),
                "source": {"type": "task_database_resolution"},
            }

        resolved_candidates = [
            self._create(
                task_id=task_id,
                database_alias=record.mcp_alias,
                source_type="database_candidate",
                source_id=None,
            )
            for _, record in candidates[:20]
        ]
        return {
            "task_id": task_id,
            "status": "needs_database_resolution",
            "environment": task.database_environment,
            "message": "数据库目标不唯一，请根据项目和用途选择 database_context_id",
            "candidates": [
                {"database_context_id": item.id, **self._public_database(item)}
                for item in resolved_candidates
            ],
        }

    def access_for_context(
        self,
        *,
        task_id: int,
        database_context_id: str,
        require_query: bool = False,
    ) -> ResolvedDatabaseAccess:
        try:
            context = self._contexts.get(database_context_id)
        except DatabaseContextRepositoryError as exc:
            raise DatabaseContextError("database_context_unavailable", str(exc)) from exc
        if context is None:
            raise DatabaseContextError(
                "database_context_expired",
                "数据库上下文不存在或已过期，请重新解析数据库目标",
            )
        if context.task_id != task_id:
            raise DatabaseContextError(
                "database_context_task_mismatch",
                "数据库上下文不属于当前任务",
            )
        task = self._task(task_id)
        if (
            task.workspace_id != context.workspace_id
            or task.database_environment != context.environment
            or task.database_environment_revision != context.environment_revision
        ):
            raise DatabaseContextError(
                "database_context_stale",
                "任务环境已变化，请重新 prepare 并解析数据库目标",
            )
        try:
            access = self._access.resolve(
                task_id=task_id,
                mcp_alias=context.database_alias,
                require_query=require_query,
            )
        except DatabaseAccessError as exc:
            raise DatabaseContextError(exc.code, str(exc)) from exc
        if (
            access.database.link_id != context.project_database_link_id
            or access.database.database_remote_name != context.physical_database
        ):
            raise DatabaseContextError(
                "database_context_stale",
                "数据库环境映射已变化，请重新解析数据库目标",
            )
        return access

    def alias_for_context(self, *, task_id: int, database_context_id: str) -> str:
        return self.access_for_context(
            task_id=task_id,
            database_context_id=database_context_id,
        ).database.mcp_alias

    def _create(
        self,
        *,
        task_id: int,
        database_alias: str,
        source_type: str,
        source_id: str | None,
    ) -> DatabaseContextRecord:
        task = self._task(task_id)
        if (
            task.workspace_id is None
            or task.database_environment is None
            or task.database_environment_revision is None
        ):
            raise DatabaseContextError(
                "task_database_context_unavailable",
                "任务缺少数据库环境快照，请重新 prepare",
            )
        try:
            access = self._access.resolve(task_id=task_id, mcp_alias=database_alias)
        except DatabaseAccessError as exc:
            raise DatabaseContextError(exc.code, str(exc)) from exc
        now = datetime.now(UTC)
        record = DatabaseContextRecord(
            id=str(uuid4()),
            task_id=task_id,
            workspace_id=task.workspace_id,
            environment=task.database_environment,
            environment_revision=task.database_environment_revision,
            database_alias=access.database.mcp_alias,
            project_database_link_id=access.database.link_id,
            physical_database=access.database.database_remote_name,
            source_type=source_type,
            source_id=source_id,
            created_at=now,
            expires_at=now + self._ttl,
        )
        try:
            return self._contexts.create(record)
        except DatabaseContextRepositoryError as exc:
            raise DatabaseContextError("database_context_unavailable", str(exc)) from exc

    def _task(self, task_id: int):
        try:
            return self._tasks.get_task(task_id)
        except TaskRepositoryError as exc:
            raise DatabaseContextError("task_not_found", "任务不存在，请重新 prepare") from exc

    @staticmethod
    def _public_database(context: DatabaseContextRecord) -> dict[str, object]:
        return {
            "alias": context.database_alias,
            "physical_name": context.physical_database,
            "project_database_link_id": context.project_database_link_id,
            "expires_at": context.expires_at.isoformat(),
        }
