from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol, cast

import psycopg

DatabaseOperation = Literal["search_objects", "execute_query"]
DatabaseCallStatus = Literal["ok", "error"]


class DatabaseCallRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DatabaseCallWrite:
    task_id: int
    operation: DatabaseOperation
    database_alias: str
    engine: str
    status: DatabaseCallStatus
    object_type: str | None = None
    statement_type: str | None = None
    sql_sha256: str | None = None
    duration_ms: int | None = None
    returned_count: int | None = None
    result_bytes: int | None = None
    truncated: bool | None = None
    error_code: str | None = None
    tool_call_id: int | None = None


@dataclass(frozen=True, slots=True)
class DatabaseCallRecord:
    id: int
    task_id: int
    operation: DatabaseOperation
    database_alias: str
    engine: str
    status: DatabaseCallStatus
    object_type: str | None
    statement_type: str | None
    sql_sha256: str | None
    duration_ms: int | None
    returned_count: int | None
    result_bytes: int | None
    truncated: bool | None
    error_code: str | None
    created_at: datetime
    tool_call_id: int | None = None


class DatabaseCallStore(Protocol):
    def create_call(self, call: DatabaseCallWrite) -> int: ...

    def list_calls(self, task_id: int) -> list[DatabaseCallRecord]: ...


class InMemoryDatabaseCallRepository:
    def __init__(self) -> None:
        self._next_id = 1
        self._calls: list[DatabaseCallRecord] = []

    def create_call(self, call: DatabaseCallWrite) -> int:
        _validate_call(call)
        call_id = self._next_id
        self._next_id += 1
        self._calls.append(_record_from_write(call_id, call, datetime.now(UTC)))
        return call_id

    def list_calls(self, task_id: int) -> list[DatabaseCallRecord]:
        return [call for call in self._calls if call.task_id == task_id]


class PostgresDatabaseCallRepository:
    def __init__(self, database_url: str | None) -> None:
        self._database_url = database_url.strip() if database_url else None

    def create_call(self, call: DatabaseCallWrite) -> int:
        _validate_call(call)
        if not self._database_url:
            raise DatabaseCallRepositoryError("任务数据库尚未配置")

        try:
            with psycopg.connect(self._database_url) as connection:
                row = connection.execute(
                    """
                    INSERT INTO mcp_database_calls (
                        task_id,
                        operation,
                        database_alias,
                        engine,
                        object_type,
                        statement_type,
                        sql_sha256,
                        status,
                        duration_ms,
                        returned_count,
                        result_bytes,
                        truncated,
                        error_code,
                        tool_call_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        call.task_id,
                        call.operation,
                        call.database_alias,
                        call.engine,
                        call.object_type,
                        call.statement_type,
                        call.sql_sha256,
                        call.status,
                        call.duration_ms,
                        call.returned_count,
                        call.result_bytes,
                        call.truncated,
                        call.error_code,
                        call.tool_call_id,
                    ),
                ).fetchone()
        except psycopg.errors.ForeignKeyViolation as exc:
            raise DatabaseCallRepositoryError("任务不存在") from exc
        except psycopg.Error as exc:
            raise DatabaseCallRepositoryError("数据库调用记录写入失败") from exc

        if row is None:
            raise DatabaseCallRepositoryError("数据库调用记录写入后没有返回调用号")
        return int(row[0])

    def list_calls(self, task_id: int) -> list[DatabaseCallRecord]:
        if not self._database_url:
            raise DatabaseCallRepositoryError("任务数据库尚未配置")

        try:
            with psycopg.connect(self._database_url) as connection:
                rows = connection.execute(
                    """
                    SELECT
                        id,
                        task_id,
                        operation,
                        database_alias,
                        engine,
                        status,
                        object_type,
                        statement_type,
                        sql_sha256,
                        duration_ms,
                        returned_count,
                        result_bytes,
                        truncated,
                        error_code,
                        created_at,
                        tool_call_id
                    FROM mcp_database_calls
                    WHERE task_id = %s
                    ORDER BY id
                    """,
                    (task_id,),
                ).fetchall()
        except psycopg.Error as exc:
            raise DatabaseCallRepositoryError("数据库调用记录读取失败") from exc

        return [_record_from_row(row) for row in rows]


def _validate_call(call: DatabaseCallWrite) -> None:
    if call.task_id <= 0:
        raise DatabaseCallRepositoryError("任务号必须大于 0")
    if call.operation not in {"search_objects", "execute_query"}:
        raise DatabaseCallRepositoryError("数据库调用类型不受支持")
    if call.status not in {"ok", "error"}:
        raise DatabaseCallRepositoryError("数据库调用状态不受支持")
    _validate_text(call.database_alias, "数据库别名", 64, required=True)
    _validate_text(call.engine, "数据库类型", 32, required=True)
    _validate_text(call.object_type, "对象类型", 32)
    _validate_text(call.statement_type, "语句类型", 32)
    _validate_text(call.error_code, "错误码", 64)
    if call.tool_call_id is not None and call.tool_call_id < 1:
        raise DatabaseCallRepositoryError("MCP 工具调用号必须大于 0")
    if call.sql_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", call.sql_sha256):
        raise DatabaseCallRepositoryError("SQL 摘要格式不正确")
    for value, label in (
        (call.duration_ms, "调用耗时"),
        (call.returned_count, "返回数量"),
        (call.result_bytes, "结果字节数"),
    ):
        if value is not None and value < 0:
            raise DatabaseCallRepositoryError(f"{label}不能小于 0")


def _validate_text(
    value: str | None,
    label: str,
    max_length: int,
    *,
    required: bool = False,
) -> None:
    if required and not value:
        raise DatabaseCallRepositoryError(f"{label}不能为空")
    if value is not None and len(value) > max_length:
        raise DatabaseCallRepositoryError(f"{label}长度不能超过 {max_length}")


def _record_from_write(
    call_id: int,
    call: DatabaseCallWrite,
    created_at: datetime,
) -> DatabaseCallRecord:
    return DatabaseCallRecord(
        id=call_id,
        task_id=call.task_id,
        operation=call.operation,
        database_alias=call.database_alias,
        engine=call.engine,
        status=call.status,
        object_type=call.object_type,
        statement_type=call.statement_type,
        sql_sha256=call.sql_sha256,
        duration_ms=call.duration_ms,
        returned_count=call.returned_count,
        result_bytes=call.result_bytes,
        truncated=call.truncated,
        error_code=call.error_code,
        created_at=created_at,
        tool_call_id=call.tool_call_id,
    )


def _record_from_row(row: tuple[object, ...]) -> DatabaseCallRecord:
    return DatabaseCallRecord(
        id=int(row[0]),
        task_id=int(row[1]),
        operation=cast(DatabaseOperation, str(row[2])),
        database_alias=str(row[3]),
        engine=str(row[4]),
        status=cast(DatabaseCallStatus, str(row[5])),
        object_type=str(row[6]) if row[6] is not None else None,
        statement_type=str(row[7]) if row[7] is not None else None,
        sql_sha256=str(row[8]) if row[8] is not None else None,
        duration_ms=int(row[9]) if row[9] is not None else None,
        returned_count=int(row[10]) if row[10] is not None else None,
        result_bytes=int(row[11]) if row[11] is not None else None,
        truncated=bool(row[12]) if row[12] is not None else None,
        error_code=str(row[13]) if row[13] is not None else None,
        created_at=cast(datetime, row[14]),
        tool_call_id=int(row[15]) if row[15] is not None else None,
    )
