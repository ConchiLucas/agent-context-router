from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

import psycopg

from context_router.services.visualization_security import VISUALIZATION_RETENTION_DAYS

AiDataQueryExecutionStatus = Literal["pending", "succeeded", "failed"]


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
    task_id: int | None = None
    tool_call_id: int | None = None
    idempotency_key: str = ""
    execution_status: AiDataQueryExecutionStatus = "pending"
    executed_at: datetime | None = None
    result_card_count: int | None = None
    result_row_count: int | None = None
    duration_ms: int | None = None
    error_summary: str | None = None
    updated_at: datetime | None = None


class AiDataQueryStore(Protocol):
    def upsert(self, record: AiDataQueryRecordData) -> AiDataQueryRecordData: ...

    def get(self, record_id: str) -> AiDataQueryRecordData | None: ...

    def latest(
        self,
        *,
        workspace_id: str | None,
        environment: str | None,
        task_id: int | None,
    ) -> AiDataQueryRecordData | None: ...

    def history(
        self,
        *,
        workspace_id: str | None,
        environment: str | None,
        source: str | None,
        task_id: int | None,
        limit: int,
    ) -> list[AiDataQueryRecordData]: ...

    def mark_execution(
        self,
        *,
        record_id: str,
        status: Literal["succeeded", "failed"],
        executed_at: datetime,
        result_card_count: int | None,
        result_row_count: int | None,
        duration_ms: int,
        error_summary: str | None,
    ) -> AiDataQueryRecordData | None: ...


class InMemoryAiDataQueryRepository:
    def __init__(self) -> None:
        self._records: dict[str, AiDataQueryRecordData] = {}

    def upsert(self, record: AiDataQueryRecordData) -> AiDataQueryRecordData:
        existing = next(
            (
                item
                for item in self._records.values()
                if item.idempotency_key == record.idempotency_key
            ),
            None,
        )
        stored = replace(
            record,
            id=existing.id if existing else record.id,
            created_at=existing.created_at if existing else record.created_at,
            updated_at=record.updated_at or record.created_at,
        )
        self._records[stored.id] = stored
        self._prune()
        return stored

    def get(self, record_id: str) -> AiDataQueryRecordData | None:
        return self._records.get(record_id)

    def latest(
        self,
        *,
        workspace_id: str | None,
        environment: str | None,
        task_id: int | None,
    ) -> AiDataQueryRecordData | None:
        records = self._filtered(workspace_id, environment, None, task_id)
        return records[0] if records else None

    def history(
        self,
        *,
        workspace_id: str | None,
        environment: str | None,
        source: str | None,
        task_id: int | None,
        limit: int,
    ) -> list[AiDataQueryRecordData]:
        return self._filtered(workspace_id, environment, source, task_id)[:limit]

    def mark_execution(
        self,
        *,
        record_id: str,
        status: Literal["succeeded", "failed"],
        executed_at: datetime,
        result_card_count: int | None,
        result_row_count: int | None,
        duration_ms: int,
        error_summary: str | None,
    ) -> AiDataQueryRecordData | None:
        current = self._records.get(record_id)
        if current is None:
            return None
        stored = replace(
            current,
            execution_status=status,
            executed_at=executed_at,
            result_card_count=result_card_count,
            result_row_count=result_row_count,
            duration_ms=duration_ms,
            error_summary=error_summary,
            updated_at=executed_at,
        )
        self._records[record_id] = stored
        return stored

    def _filtered(
        self,
        workspace_id: str | None,
        environment: str | None,
        source: str | None,
        task_id: int | None,
    ) -> list[AiDataQueryRecordData]:
        cutoff = datetime.now(UTC) - timedelta(days=VISUALIZATION_RETENTION_DAYS)
        return sorted(
            (
                item
                for item in self._records.values()
                if item.created_at >= cutoff
                and (workspace_id is None or item.workspace_id == workspace_id)
                and (environment is None or item.environment == environment)
                and (source is None or item.source == source)
                and (task_id is None or item.task_id == task_id)
            ),
            key=lambda item: (item.created_at, item.id),
            reverse=True,
        )

    def _prune(self) -> None:
        cutoff = datetime.now(UTC) - timedelta(days=VISUALIZATION_RETENTION_DAYS)
        self._records = {
            key: value for key, value in self._records.items() if value.created_at >= cutoff
        }


class PostgresAiDataQueryRepository:
    _SELECT = """
        SELECT id, workspace_id, source, description, environment,
               database_key, schema_name, table_name, keyword, created_at,
               task_id, tool_call_id, idempotency_key, execution_status,
               executed_at, result_card_count, result_row_count, duration_ms,
               error_summary, updated_at
        FROM ai_data_query_records
    """

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url.strip()

    def upsert(self, record: AiDataQueryRecordData) -> AiDataQueryRecordData:
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    """
                    INSERT INTO ai_data_query_records
                        (id, workspace_id, source, description, environment,
                         database_key, schema_name, table_name, keyword, created_at,
                         task_id, tool_call_id, idempotency_key, execution_status, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, 'pending', %s)
                    ON CONFLICT (idempotency_key) DO UPDATE SET
                        source=EXCLUDED.source,
                        description=EXCLUDED.description,
                        workspace_id=EXCLUDED.workspace_id,
                        environment=EXCLUDED.environment,
                        database_key=EXCLUDED.database_key,
                        schema_name=EXCLUDED.schema_name,
                        table_name=EXCLUDED.table_name,
                        keyword=EXCLUDED.keyword,
                        task_id=EXCLUDED.task_id,
                        tool_call_id=EXCLUDED.tool_call_id,
                        updated_at=EXCLUDED.updated_at
                    RETURNING id
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
                        record.task_id,
                        record.tool_call_id,
                        record.idempotency_key,
                        record.updated_at or record.created_at,
                    ),
                ).fetchone()
                if row is None:
                    raise AiDataQueryRepositoryError("AI 数据查询条件保存失败")
                connection.execute(
                    """DELETE FROM ai_data_query_records
                       WHERE created_at < CURRENT_TIMESTAMP - (%s * INTERVAL '1 day')""",
                    (VISUALIZATION_RETENTION_DAYS,),
                )
                stored = connection.execute(
                    self._SELECT + " WHERE id=%s",
                    (str(row[0]),),
                ).fetchone()
        except psycopg.Error as exc:
            raise AiDataQueryRepositoryError("AI 数据查询条件保存失败") from exc
        if stored is None:
            raise AiDataQueryRepositoryError("AI 数据查询条件保存后无法读取")
        return self._record(stored)

    def get(self, record_id: str) -> AiDataQueryRecordData | None:
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    self._SELECT + " WHERE id=%s",
                    (record_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise AiDataQueryRepositoryError("AI 数据查询条件读取失败") from exc
        return self._record(row) if row is not None else None

    def latest(
        self,
        *,
        workspace_id: str | None,
        environment: str | None,
        task_id: int | None,
    ) -> AiDataQueryRecordData | None:
        clauses, parameters = self._filters(workspace_id, environment, None, task_id)
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    f"{self._SELECT} WHERE {' AND '.join(clauses)} "
                    "ORDER BY created_at DESC, id DESC LIMIT 1",
                    tuple(parameters),
                ).fetchone()
        except psycopg.Error as exc:
            raise AiDataQueryRepositoryError("最新 AI 数据查询条件读取失败") from exc
        return self._record(row) if row is not None else None

    def history(
        self,
        *,
        workspace_id: str | None,
        environment: str | None,
        source: str | None,
        task_id: int | None,
        limit: int,
    ) -> list[AiDataQueryRecordData]:
        clauses, parameters = self._filters(workspace_id, environment, source, task_id)
        parameters.append(limit)
        try:
            with psycopg.connect(self._database_url) as connection:
                rows = connection.execute(
                    f"{self._SELECT} WHERE {' AND '.join(clauses)} "
                    "ORDER BY created_at DESC, id DESC LIMIT %s",
                    tuple(parameters),
                ).fetchall()
        except psycopg.Error as exc:
            raise AiDataQueryRepositoryError("AI 数据查询历史读取失败") from exc
        return [self._record(row) for row in rows]

    def mark_execution(
        self,
        *,
        record_id: str,
        status: Literal["succeeded", "failed"],
        executed_at: datetime,
        result_card_count: int | None,
        result_row_count: int | None,
        duration_ms: int,
        error_summary: str | None,
    ) -> AiDataQueryRecordData | None:
        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    """UPDATE ai_data_query_records
                       SET execution_status=%s, executed_at=%s,
                           result_card_count=%s, result_row_count=%s,
                           duration_ms=%s, error_summary=%s, updated_at=%s
                       WHERE id=%s
                       RETURNING id""",
                    (
                        status,
                        executed_at,
                        result_card_count,
                        result_row_count,
                        duration_ms,
                        error_summary,
                        executed_at,
                        record_id,
                    ),
                ).fetchone()
                stored = (
                    connection.execute(self._SELECT + " WHERE id=%s", (record_id,)).fetchone()
                    if row
                    else None
                )
        except psycopg.Error as exc:
            raise AiDataQueryRepositoryError("AI 数据查询执行摘要保存失败") from exc
        return self._record(stored) if stored is not None else None

    @staticmethod
    def _filters(
        workspace_id: str | None,
        environment: str | None,
        source: str | None,
        task_id: int | None,
    ) -> tuple[list[str], list[object]]:
        clauses = ["created_at >= CURRENT_TIMESTAMP - (%s * INTERVAL '1 day')"]
        parameters: list[object] = [VISUALIZATION_RETENTION_DAYS]
        if workspace_id is not None:
            clauses.append("workspace_id=%s")
            parameters.append(workspace_id)
        if environment is not None:
            clauses.append("environment=%s")
            parameters.append(environment)
        if source is not None:
            clauses.append("source=%s")
            parameters.append(source)
        if task_id is not None:
            clauses.append("task_id=%s")
            parameters.append(task_id)
        return clauses, parameters

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
            task_id=int(row[10]) if row[10] is not None else None,
            tool_call_id=int(row[11]) if row[11] is not None else None,
            idempotency_key=str(row[12]),
            execution_status=str(row[13]),  # type: ignore[arg-type]
            executed_at=row[14] if isinstance(row[14], datetime) else None,
            result_card_count=int(row[15]) if row[15] is not None else None,
            result_row_count=int(row[16]) if row[16] is not None else None,
            duration_ms=int(row[17]) if row[17] is not None else None,
            error_summary=str(row[18]) if row[18] is not None else None,
            updated_at=row[19] if isinstance(row[19], datetime) else None,
        )
