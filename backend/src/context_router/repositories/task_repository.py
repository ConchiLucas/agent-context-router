from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import psycopg


class TaskRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TaskRecord:
    id: int
    project_key: str
    project_name: str
    task: str
    cwd: str
    agent_name: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TaskListRecord(TaskRecord):
    read_call_count: int


class TaskWriter(Protocol):
    def create_task(
        self,
        *,
        project_key: str,
        project_name: str,
        task: str,
        cwd: str,
        agent_name: str | None,
    ) -> int: ...


class TaskReader(Protocol):
    def get_task(self, task_id: int) -> TaskRecord: ...

    def list_tasks(self, project_key: str, *, limit: int = 30) -> list[TaskListRecord]: ...


class TaskStore(TaskWriter, TaskReader, Protocol):
    pass


class PostgresTaskRepository:
    def __init__(self, database_url: str | None) -> None:
        self._database_url = database_url.strip() if database_url else None

    def create_task(
        self,
        *,
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
                        project_key,
                        project_name,
                        task,
                        cwd,
                        agent_name
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (project_key, project_name, task, cwd, agent_name),
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
                    SELECT id, project_key, project_name, task, cwd, agent_name, created_at
                    FROM mcp_tasks
                    WHERE id = %s
                    """,
                    (task_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise TaskRepositoryError("任务记录读取失败") from exc

        if row is None:
            raise TaskRepositoryError("任务不存在")
        return TaskRecord(
            id=int(row[0]),
            project_key=str(row[1]),
            project_name=str(row[2]),
            task=str(row[3]),
            cwd=str(row[4]),
            agent_name=str(row[5]) if row[5] is not None else None,
            created_at=row[6],
        )

    def list_tasks(self, project_key: str, *, limit: int = 30) -> list[TaskListRecord]:
        if not self._database_url:
            raise TaskRepositoryError("任务数据库尚未配置")

        safe_limit = min(max(limit, 1), 100)
        try:
            with psycopg.connect(self._database_url) as connection:
                rows = connection.execute(
                    """
                    SELECT
                        task.id,
                        task.project_key,
                        task.project_name,
                        task.task,
                        task.cwd,
                        task.agent_name,
                        task.created_at,
                        COUNT(read_call.id) AS read_call_count
                    FROM mcp_tasks AS task
                    LEFT JOIN mcp_document_read_calls AS read_call
                        ON read_call.task_id = task.id
                    WHERE task.project_key = %s
                    GROUP BY task.id
                    ORDER BY task.id DESC
                    LIMIT %s
                    """,
                    (project_key, safe_limit),
                ).fetchall()
        except psycopg.Error as exc:
            raise TaskRepositoryError("任务列表读取失败") from exc

        return [
            TaskListRecord(
                id=int(row[0]),
                project_key=str(row[1]),
                project_name=str(row[2]),
                task=str(row[3]),
                cwd=str(row[4]),
                agent_name=str(row[5]) if row[5] is not None else None,
                created_at=row[6],
                read_call_count=int(row[7]),
            )
            for row in rows
        ]
