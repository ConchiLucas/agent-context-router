from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import psycopg


class AiDataQueryRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AiDataQueryRecordData:
    id: str
    workspace_id: str
    source: str
    description: str
    environment: str
    database_key: str
    schema_name: str
    table_name: str
    keyword: str
    created_at: datetime


class AiDataQueryStore(Protocol):
    def create(self, record: AiDataQueryRecordData) -> AiDataQueryRecordData: ...

    def latest(self) -> AiDataQueryRecordData | None: ...

    def history(self, *, limit: int) -> list[AiDataQueryRecordData]: ...


class InMemoryAiDataQueryRepository:
    def __init__(self) -> None:
        self._records: list[AiDataQueryRecordData] = []

    def create(self, record: AiDataQueryRecordData) -> AiDataQueryRecordData:
        self._records.append(record)
        return record

    def latest(self) -> AiDataQueryRecordData | None:
        return self._ordered()[0] if self._records else None

    def history(self, *, limit: int) -> list[AiDataQueryRecordData]:
        return self._ordered()[:limit]

    def _ordered(self) -> list[AiDataQueryRecordData]:
        return sorted(self._records, key=lambda item: (item.created_at, item.id), reverse=True)


class PostgresAiDataQueryRepository:
    _SELECT = """
        SELECT id, workspace_id, source, description, environment,
               database_key, schema_name, table_name, keyword, created_at
        FROM ai_data_query_records
    """

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url.strip()

    def create(self, record: AiDataQueryRecordData) -> AiDataQueryRecordData:
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    """
                    INSERT INTO ai_data_query_records
                        (id, workspace_id, source, description, environment,
                         database_key, schema_name, table_name, keyword, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, workspace_id, source, description, environment,
                              database_key, schema_name, table_name, keyword, created_at
                    """,
                    (
                        record.id,
                        record.workspace_id,
                        record.source,
                        record.description,
                        record.environment,
                        record.database_key,
                        record.schema_name,
                        record.table_name,
                        record.keyword,
                        record.created_at,
                    ),
                ).fetchone()
        except psycopg.Error as exc:
            raise AiDataQueryRepositoryError("AI 数据查询条件保存失败") from exc
        if row is None:
            raise AiDataQueryRepositoryError("AI 数据查询条件保存失败")
        return self._record(row)

    def latest(self) -> AiDataQueryRecordData | None:
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    self._SELECT + " ORDER BY created_at DESC, id DESC LIMIT 1"
                ).fetchone()
        except psycopg.Error as exc:
            raise AiDataQueryRepositoryError("最新 AI 数据查询条件读取失败") from exc
        return self._record(row) if row is not None else None

    def history(self, *, limit: int) -> list[AiDataQueryRecordData]:
        try:
            with psycopg.connect(self._database_url) as connection:
                rows = connection.execute(
                    self._SELECT + " ORDER BY created_at DESC, id DESC LIMIT %s",
                    (limit,),
                ).fetchall()
        except psycopg.Error as exc:
            raise AiDataQueryRepositoryError("AI 数据查询历史读取失败") from exc
        return [self._record(row) for row in rows]

    @staticmethod
    def _record(row: tuple[object, ...]) -> AiDataQueryRecordData:
        return AiDataQueryRecordData(
            id=str(row[0]),
            workspace_id=str(row[1]),
            source=str(row[2]),
            description=str(row[3]),
            environment=str(row[4]),
            database_key=str(row[5]),
            schema_name=str(row[6]),
            table_name=str(row[7]),
            keyword=str(row[8]),
            created_at=row[9] if isinstance(row[9], datetime) else datetime.now(UTC),
        )
