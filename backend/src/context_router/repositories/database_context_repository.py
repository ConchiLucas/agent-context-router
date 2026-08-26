from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import psycopg


class DatabaseContextRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DatabaseContextRecord:
    id: str
    task_id: int
    workspace_id: str
    environment: str
    environment_revision: int
    database_alias: str
    project_database_link_id: str
    physical_database: str
    source_type: str
    source_id: str | None
    created_at: datetime
    expires_at: datetime


class DatabaseContextStore(Protocol):
    def create(self, record: DatabaseContextRecord) -> DatabaseContextRecord: ...

    def get(self, context_id: str) -> DatabaseContextRecord | None: ...


class InMemoryDatabaseContextRepository:
    def __init__(self) -> None:
        self._records: dict[str, DatabaseContextRecord] = {}

    def create(self, record: DatabaseContextRecord) -> DatabaseContextRecord:
        self._records[record.id] = record
        return record

    def get(self, context_id: str) -> DatabaseContextRecord | None:
        record = self._records.get(context_id)
        if record is None or record.expires_at <= datetime.now(UTC):
            return None
        return record


class PostgresDatabaseContextRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url.strip()

    def create(self, record: DatabaseContextRecord) -> DatabaseContextRecord:
        try:
            with psycopg.connect(self._database_url) as connection:
                connection.execute(
                    """
                    INSERT INTO mcp_database_contexts (
                        id, task_id, workspace_id, environment, environment_revision,
                        database_alias, project_database_link_id, physical_database,
                        source_type, source_id, created_at, expires_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        record.id,
                        record.task_id,
                        record.workspace_id,
                        record.environment,
                        record.environment_revision,
                        record.database_alias,
                        record.project_database_link_id,
                        record.physical_database,
                        record.source_type,
                        record.source_id,
                        record.created_at,
                        record.expires_at,
                    ),
                )
        except psycopg.Error as exc:
            raise DatabaseContextRepositoryError("数据库上下文保存失败") from exc
        return record

    def get(self, context_id: str) -> DatabaseContextRecord | None:
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    """
                    SELECT id, task_id, workspace_id, environment, environment_revision,
                           database_alias, project_database_link_id, physical_database,
                           source_type, source_id, created_at, expires_at
                    FROM mcp_database_contexts
                    WHERE id = %s AND expires_at > CURRENT_TIMESTAMP
                    """,
                    (context_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise DatabaseContextRepositoryError("数据库上下文读取失败") from exc
        if row is None:
            return None
        return DatabaseContextRecord(
            id=str(row[0]),
            task_id=int(row[1]),
            workspace_id=str(row[2]),
            environment=str(row[3]),
            environment_revision=int(row[4]),
            database_alias=str(row[5]),
            project_database_link_id=str(row[6]),
            physical_database=str(row[7]),
            source_type=str(row[8]),
            source_id=str(row[9]) if row[9] is not None else None,
            created_at=row[10],
            expires_at=row[11],
        )
