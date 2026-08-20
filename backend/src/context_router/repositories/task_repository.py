from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

import psycopg

DatabaseEnvironmentSelection = Literal["workspace_default", "task_explicit"]
_ENVIRONMENT_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


class TaskRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TaskRecord:
    id: int
    project_id: str | None
    project_key: str
    project_name: str
    task: str
    cwd: str
    agent_name: str | None
    created_at: datetime
    scope: Literal["project", "workspace"] = "project"
    workspace_id: str | None = None
    workspace_key: str | None = None
    workspace_name: str | None = None
    active_project_id: str | None = None
    active_project_name: str | None = None
    active_project_kind: Literal["frontend", "backend"] | None = None
    database_environment: str | None = None
    database_environment_revision: int | None = None
    database_environment_selection: DatabaseEnvironmentSelection | None = None


@dataclass(frozen=True, slots=True)
class TaskListRecord(TaskRecord):
    read_call_count: int = 0


class TaskWriter(Protocol):
    def create_task(
        self,
        *,
        project_id: str,
        project_key: str,
        project_name: str,
        task: str,
        cwd: str,
        agent_name: str | None,
    ) -> int: ...

    def create_workspace_task(
        self,
        *,
        workspace_id: str,
        workspace_key: str,
        workspace_name: str,
        task: str,
        cwd: str,
        agent_name: str | None,
        active_project_id: str | None = None,
        active_project_name: str | None = None,
        active_project_kind: Literal["frontend", "backend"] | None = None,
        database_environment: str | None = None,
        database_environment_revision: int | None = None,
        database_environment_selection: DatabaseEnvironmentSelection | None = None,
    ) -> int: ...


class TaskReader(Protocol):
    def get_task(self, task_id: int) -> TaskRecord: ...

    def list_tasks(
        self,
        project_key: str,
        *,
        project_id: str | None = None,
        limit: int = 30,
        include_system: bool = False,
    ) -> list[TaskListRecord]: ...

    def list_workspace_tasks(
        self,
        workspace_id: str,
        *,
        workspace_key: str | None = None,
        limit: int = 30,
        include_system: bool = False,
    ) -> list[TaskListRecord]: ...


class TaskStore(TaskWriter, TaskReader, Protocol):
    pass


class PostgresTaskRepository:
    def __init__(self, database_url: str | None) -> None:
        self._database_url = database_url.strip() if database_url else None

    def create_task(
        self,
        *,
        project_id: str,
        project_key: str,
        project_name: str,
        task: str,
        cwd: str,
        agent_name: str | None,
    ) -> int:
        if not self._database_url:
            raise TaskRepositoryError("任务数据库尚未配置")

        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    """
                    INSERT INTO mcp_tasks (
                        scope,
                        project_id,
                        project_key,
                        project_name,
                        task,
                        cwd,
                        agent_name
                    )
                    VALUES ('project', %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (project_id, project_key, project_name, task, cwd, agent_name),
                ).fetchone()
        except psycopg.Error as exc:
            raise TaskRepositoryError("任务记录写入失败") from exc

        if row is None:
            raise TaskRepositoryError("任务记录写入后没有返回任务号")
        return int(row[0])

    def create_workspace_task(
        self,
        *,
        workspace_id: str,
        workspace_key: str,
        workspace_name: str,
        task: str,
        cwd: str,
        agent_name: str | None,
        active_project_id: str | None = None,
        active_project_name: str | None = None,
        active_project_kind: Literal["frontend", "backend"] | None = None,
        database_environment: str | None = None,
        database_environment_revision: int | None = None,
        database_environment_selection: DatabaseEnvironmentSelection | None = None,
    ) -> int:
        if not self._database_url:
            raise TaskRepositoryError("任务数据库尚未配置")
        if active_project_kind not in {None, "frontend", "backend"}:
            raise TaskRepositoryError("活动项目类型必须是 frontend 或 backend")
        if (database_environment is None) != (database_environment_revision is None):
            raise TaskRepositoryError("数据库环境和版本必须同时提供")
        if database_environment is not None and not _ENVIRONMENT_PATTERN.fullmatch(
            database_environment
        ):
            raise TaskRepositoryError(
                "数据库环境必须以小写字母开头，且只能包含小写字母、数字、下划线或连字符"
            )
        if database_environment_revision is not None and database_environment_revision < 1:
            raise TaskRepositoryError("数据库环境版本必须大于 0")
        if database_environment_selection not in {
            None,
            "workspace_default",
            "task_explicit",
        }:
            raise TaskRepositoryError("数据库环境选择方式必须是 workspace_default 或 task_explicit")
        if database_environment is None and database_environment_selection is not None:
            raise TaskRepositoryError("没有数据库环境时不能指定环境选择方式")
        normalized_environment_selection = database_environment_selection
        if database_environment is not None and normalized_environment_selection is None:
            normalized_environment_selection = "workspace_default"

        legacy_project_name = active_project_name or workspace_name
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    """
                    INSERT INTO mcp_tasks (
                        scope,
                        workspace_id,
                        workspace_key,
                        workspace_name,
                        active_project_id,
                        active_project_name,
                        active_project_kind,
                        database_environment,
                        database_environment_revision,
                        database_environment_selection,
                        project_id,
                        project_key,
                        project_name,
                        task,
                        cwd,
                        agent_name
                    )
                    VALUES (
                        'workspace', %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s
                    )
                    RETURNING id
                    """,
                    (
                        workspace_id,
                        workspace_key,
                        workspace_name,
                        active_project_id,
                        active_project_name,
                        active_project_kind,
                        database_environment,
                        database_environment_revision,
                        normalized_environment_selection,
                        active_project_id,
                        workspace_key,
                        legacy_project_name,
                        task,
                        cwd,
                        agent_name,
                    ),
                ).fetchone()
        except psycopg.Error as exc:
            raise TaskRepositoryError("任务记录写入失败") from exc

        if row is None:
            raise TaskRepositoryError("任务记录写入后没有返回任务号")
        return int(row[0])

    def get_task(self, task_id: int) -> TaskRecord:
        if not self._database_url:
            raise TaskRepositoryError("任务数据库尚未配置")

        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    """
                    SELECT
                        id,
                        project_id,
                        project_key,
                        project_name,
                        task,
                        cwd,
                        agent_name,
                        created_at,
                        scope,
                        workspace_id,
                        workspace_key,
                        workspace_name,
                        active_project_id,
                        active_project_name,
                        active_project_kind,
                        database_environment,
                        database_environment_revision,
                        database_environment_selection
                    FROM mcp_tasks
                    WHERE id = %s
                    """,
                    (task_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise TaskRepositoryError("任务记录读取失败") from exc

        if row is None:
            raise TaskRepositoryError("任务不存在")
        return self._task_record(row)

    def list_tasks(
        self,
        project_key: str,
        *,
        project_id: str | None = None,
        limit: int = 30,
        include_system: bool = False,
    ) -> list[TaskListRecord]:
        if not self._database_url:
            raise TaskRepositoryError("任务数据库尚未配置")

        safe_limit = min(max(limit, 1), 100)
        try:
            with psycopg.connect(self._database_url) as connection:
                rows = connection.execute(
                    """
                    SELECT
                        task.id,
                        task.project_id,
                        task.project_key,
                        task.project_name,
                        task.task,
                        task.cwd,
                        task.agent_name,
                        task.created_at,
                        task.scope,
                        task.workspace_id,
                        task.workspace_key,
                        task.workspace_name,
                        task.active_project_id,
                        task.active_project_name,
                        task.active_project_kind,
                        task.database_environment,
                        task.database_environment_revision,
                        task.database_environment_selection,
                        COUNT(read_call.id) AS read_call_count
                    FROM mcp_tasks AS task
                    LEFT JOIN mcp_document_read_calls AS read_call
                        ON read_call.task_id = task.id
                    WHERE task.scope = 'project'
                      AND (
                            task.project_id = %s
                            OR (task.project_id IS NULL AND task.project_key = %s)
                      )
                      AND (%s OR task.agent_name IS DISTINCT FROM 'connection-test')
                    GROUP BY task.id
                    HAVING COUNT(read_call.id) > 0
                        OR EXISTS (
                            SELECT 1
                            FROM mcp_database_calls AS database_call
                            WHERE database_call.task_id = task.id
                        )
                    ORDER BY task.id DESC
                    LIMIT %s
                    """,
                    (project_id, project_key, include_system, safe_limit),
                ).fetchall()
        except psycopg.Error as exc:
            raise TaskRepositoryError("任务列表读取失败") from exc

        return [self._task_list_record(row) for row in rows]

    def list_workspace_tasks(
        self,
        workspace_id: str,
        *,
        workspace_key: str | None = None,
        limit: int = 30,
        include_system: bool = False,
    ) -> list[TaskListRecord]:
        if not self._database_url:
            raise TaskRepositoryError("任务数据库尚未配置")

        safe_limit = min(max(limit, 1), 100)
        try:
            with psycopg.connect(self._database_url) as connection:
                rows = connection.execute(
                    """
                    SELECT
                        task.id,
                        task.project_id,
                        task.project_key,
                        task.project_name,
                        task.task,
                        task.cwd,
                        task.agent_name,
                        task.created_at,
                        task.scope,
                        task.workspace_id,
                        task.workspace_key,
                        task.workspace_name,
                        task.active_project_id,
                        task.active_project_name,
                        task.active_project_kind,
                        task.database_environment,
                        task.database_environment_revision,
                        task.database_environment_selection,
                        COUNT(read_call.id) AS read_call_count
                    FROM mcp_tasks AS task
                    LEFT JOIN mcp_document_read_calls AS read_call
                        ON read_call.task_id = task.id
                    WHERE (
                            task.workspace_id = %s
                            OR (
                                task.workspace_id IS NULL
                                AND %s::text IS NOT NULL
                                AND task.workspace_key = %s
                            )
                      )
                      AND (%s OR task.agent_name IS DISTINCT FROM 'connection-test')
                    GROUP BY task.id
                    HAVING COUNT(read_call.id) > 0
                        OR EXISTS (
                            SELECT 1
                            FROM mcp_database_calls AS database_call
                            WHERE database_call.task_id = task.id
                        )
                    ORDER BY task.id DESC
                    LIMIT %s
                    """,
                    (
                        workspace_id,
                        workspace_key,
                        workspace_key,
                        include_system,
                        safe_limit,
                    ),
                ).fetchall()
        except psycopg.Error as exc:
            raise TaskRepositoryError("工作空间任务列表读取失败") from exc

        return [self._task_list_record(row) for row in rows]

    @staticmethod
    def _task_record(row: tuple[object, ...]) -> TaskRecord:
        return TaskRecord(
            id=int(row[0]),
            project_id=str(row[1]) if row[1] is not None else None,
            project_key=str(row[2]),
            project_name=str(row[3]),
            task=str(row[4]),
            cwd=str(row[5]),
            agent_name=str(row[6]) if row[6] is not None else None,
            created_at=row[7],  # type: ignore[arg-type]
            scope=str(row[8]),  # type: ignore[arg-type]
            workspace_id=str(row[9]) if row[9] is not None else None,
            workspace_key=str(row[10]) if row[10] is not None else None,
            workspace_name=str(row[11]) if row[11] is not None else None,
            active_project_id=str(row[12]) if row[12] is not None else None,
            active_project_name=str(row[13]) if row[13] is not None else None,
            active_project_kind=str(row[14]) if row[14] is not None else None,  # type: ignore[arg-type]
            database_environment=str(row[15]) if row[15] is not None else None,
            database_environment_revision=int(row[16]) if row[16] is not None else None,
            database_environment_selection=(str(row[17]) if row[17] is not None else None),  # type: ignore[arg-type]
        )

    @classmethod
    def _task_list_record(cls, row: tuple[object, ...]) -> TaskListRecord:
        task = cls._task_record(row)
        return TaskListRecord(
            id=task.id,
            project_id=task.project_id,
            project_key=task.project_key,
            project_name=task.project_name,
            task=task.task,
            cwd=task.cwd,
            agent_name=task.agent_name,
            created_at=task.created_at,
            scope=task.scope,
            workspace_id=task.workspace_id,
            workspace_key=task.workspace_key,
            workspace_name=task.workspace_name,
            active_project_id=task.active_project_id,
            active_project_name=task.active_project_name,
            active_project_kind=task.active_project_kind,
            database_environment=task.database_environment,
            database_environment_revision=task.database_environment_revision,
            database_environment_selection=task.database_environment_selection,
            read_call_count=int(row[18]),
        )
