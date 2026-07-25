from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from threading import RLock
from typing import Literal, Protocol, cast

import psycopg
from psycopg.types.json import Jsonb

DatabaseToolPayloadStatus = Literal[
    "pending",
    "ok",
    "error",
    "cancelled",
    "interrupted",
    "capture_failed",
    "expired",
]


class DatabaseToolPayloadRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DatabaseToolPayloadWrite:
    tool_call_id: int
    tool_name: str
    request_payload: dict[str, object]
    request_bytes: int
    request_truncated: bool
    expires_at: datetime
    capture_version: int = 1


@dataclass(frozen=True, slots=True)
class DatabaseToolPayloadRecord:
    tool_call_id: int
    tool_name: str
    request_payload: dict[str, object] | None
    response_payload: dict[str, object] | None
    response_status: DatabaseToolPayloadStatus
    request_bytes: int | None
    response_bytes: int | None
    request_truncated: bool
    response_truncated: bool
    capture_version: int
    capture_error_code: str | None
    expires_at: datetime
    created_at: datetime
    updated_at: datetime


class DatabaseToolPayloadStore(Protocol):
    def create_request(self, payload: DatabaseToolPayloadWrite) -> None: ...

    def complete_response(
        self,
        tool_call_id: int,
        *,
        status: DatabaseToolPayloadStatus,
        response_payload: dict[str, object] | None,
        response_bytes: int | None,
        response_truncated: bool,
        capture_error_code: str | None = None,
        updated_at: datetime | None = None,
    ) -> None: ...

    def get_payload(self, tool_call_id: int) -> DatabaseToolPayloadRecord | None: ...

    def list_metadata(
        self,
        tool_call_ids: list[int],
    ) -> dict[int, DatabaseToolPayloadRecord]: ...

    def expire_payloads(self, *, expired_at: datetime) -> int: ...

    def interrupt_pending(self, *, interrupted_at: datetime) -> int: ...


class InMemoryDatabaseToolPayloadRepository:
    def __init__(self) -> None:
        self._payloads: dict[int, DatabaseToolPayloadRecord] = {}
        self._lock = RLock()

    def create_request(self, payload: DatabaseToolPayloadWrite) -> None:
        _validate_write(payload)
        now = datetime.now(UTC)
        record = DatabaseToolPayloadRecord(
            tool_call_id=payload.tool_call_id,
            tool_name=payload.tool_name,
            request_payload=payload.request_payload,
            response_payload=None,
            response_status="pending",
            request_bytes=payload.request_bytes,
            response_bytes=None,
            request_truncated=payload.request_truncated,
            response_truncated=False,
            capture_version=payload.capture_version,
            capture_error_code=None,
            expires_at=payload.expires_at,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._payloads[payload.tool_call_id] = record

    def complete_response(
        self,
        tool_call_id: int,
        *,
        status: DatabaseToolPayloadStatus,
        response_payload: dict[str, object] | None,
        response_bytes: int | None,
        response_truncated: bool,
        capture_error_code: str | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        _validate_completion(
            tool_call_id=tool_call_id,
            status=status,
            response_bytes=response_bytes,
            capture_error_code=capture_error_code,
        )
        with self._lock:
            current = self._payloads.get(tool_call_id)
            if current is None:
                raise DatabaseToolPayloadRepositoryError("数据库 MCP 调用详情不存在")
            self._payloads[tool_call_id] = replace(
                current,
                response_payload=response_payload,
                response_status=status,
                response_bytes=response_bytes,
                response_truncated=response_truncated,
                capture_error_code=capture_error_code,
                updated_at=updated_at or datetime.now(UTC),
            )

    def get_payload(self, tool_call_id: int) -> DatabaseToolPayloadRecord | None:
        if tool_call_id < 1:
            raise DatabaseToolPayloadRepositoryError("MCP 工具调用号必须大于 0")
        with self._lock:
            return self._payloads.get(tool_call_id)

    def list_metadata(
        self,
        tool_call_ids: list[int],
    ) -> dict[int, DatabaseToolPayloadRecord]:
        safe_ids = _validate_tool_call_ids(tool_call_ids)
        with self._lock:
            return {
                tool_call_id: replace(
                    self._payloads[tool_call_id],
                    request_payload=None,
                    response_payload=None,
                )
                for tool_call_id in safe_ids
                if tool_call_id in self._payloads
            }

    def expire_payloads(self, *, expired_at: datetime) -> int:
        count = 0
        with self._lock:
            for tool_call_id, payload in list(self._payloads.items()):
                if payload.expires_at > expired_at or payload.response_status == "expired":
                    continue
                self._payloads[tool_call_id] = replace(
                    payload,
                    request_payload=None,
                    response_payload=None,
                    response_status="expired",
                    capture_error_code=None,
                    updated_at=expired_at,
                )
                count += 1
        return count

    def interrupt_pending(self, *, interrupted_at: datetime) -> int:
        count = 0
        with self._lock:
            for tool_call_id, payload in list(self._payloads.items()):
                if payload.response_status != "pending":
                    continue
                self._payloads[tool_call_id] = replace(
                    payload,
                    response_status="interrupted",
                    capture_error_code="server_restarted",
                    updated_at=interrupted_at,
                )
                count += 1
        return count


class PostgresDatabaseToolPayloadRepository:
    def __init__(self, database_url: str | None) -> None:
        self._database_url = database_url.strip() if database_url else None

    def create_request(self, payload: DatabaseToolPayloadWrite) -> None:
        _validate_write(payload)
        database_url = self._require_database_url()
        try:
            with psycopg.connect(database_url) as connection:
                connection.execute(
                    """
                    INSERT INTO mcp_database_tool_payloads (
                        tool_call_id,
                        tool_name,
                        request_payload,
                        response_status,
                        request_bytes,
                        request_truncated,
                        response_truncated,
                        capture_version,
                        expires_at
                    )
                    VALUES (%s, %s, %s, 'pending', %s, %s, false, %s, %s)
                    ON CONFLICT (tool_call_id) DO UPDATE
                    SET
                        tool_name = EXCLUDED.tool_name,
                        request_payload = EXCLUDED.request_payload,
                        response_payload = NULL,
                        response_status = 'pending',
                        request_bytes = EXCLUDED.request_bytes,
                        response_bytes = NULL,
                        request_truncated = EXCLUDED.request_truncated,
                        response_truncated = false,
                        capture_version = EXCLUDED.capture_version,
                        capture_error_code = NULL,
                        expires_at = EXCLUDED.expires_at,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        payload.tool_call_id,
                        payload.tool_name,
                        Jsonb(payload.request_payload),
                        payload.request_bytes,
                        payload.request_truncated,
                        payload.capture_version,
                        payload.expires_at,
                    ),
                )
        except psycopg.errors.ForeignKeyViolation as exc:
            raise DatabaseToolPayloadRepositoryError("MCP 工具调用不存在") from exc
        except psycopg.Error as exc:
            raise DatabaseToolPayloadRepositoryError("数据库 MCP 入参详情写入失败") from exc

    def complete_response(
        self,
        tool_call_id: int,
        *,
        status: DatabaseToolPayloadStatus,
        response_payload: dict[str, object] | None,
        response_bytes: int | None,
        response_truncated: bool,
        capture_error_code: str | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        _validate_completion(
            tool_call_id=tool_call_id,
            status=status,
            response_bytes=response_bytes,
            capture_error_code=capture_error_code,
        )
        database_url = self._require_database_url()
        try:
            with psycopg.connect(database_url) as connection:
                row = connection.execute(
                    """
                    UPDATE mcp_database_tool_payloads
                    SET
                        response_payload = %s,
                        response_status = %s,
                        response_bytes = %s,
                        response_truncated = %s,
                        capture_error_code = %s,
                        updated_at = %s
                    WHERE tool_call_id = %s
                    RETURNING tool_call_id
                    """,
                    (
                        Jsonb(response_payload) if response_payload is not None else None,
                        status,
                        response_bytes,
                        response_truncated,
                        capture_error_code,
                        updated_at or datetime.now(UTC),
                        tool_call_id,
                    ),
                ).fetchone()
        except psycopg.Error as exc:
            raise DatabaseToolPayloadRepositoryError("数据库 MCP 出参详情写入失败") from exc
        if row is None:
            raise DatabaseToolPayloadRepositoryError("数据库 MCP 调用详情不存在")

    def get_payload(self, tool_call_id: int) -> DatabaseToolPayloadRecord | None:
        if tool_call_id < 1:
            raise DatabaseToolPayloadRepositoryError("MCP 工具调用号必须大于 0")
        database_url = self._require_database_url()
        try:
            with psycopg.connect(database_url) as connection:
                row = connection.execute(
                    f"{_SELECT_PAYLOAD} WHERE tool_call_id = %s",
                    (tool_call_id,),
                ).fetchone()
        except psycopg.Error as exc:
            raise DatabaseToolPayloadRepositoryError("数据库 MCP 调用详情读取失败") from exc
        return _record_from_row(row) if row is not None else None

    def list_metadata(
        self,
        tool_call_ids: list[int],
    ) -> dict[int, DatabaseToolPayloadRecord]:
        safe_ids = _validate_tool_call_ids(tool_call_ids)
        if not safe_ids:
            return {}
        database_url = self._require_database_url()
        try:
            with psycopg.connect(database_url) as connection:
                rows = connection.execute(
                    f"{_SELECT_PAYLOAD_METADATA} WHERE tool_call_id = ANY(%s)",
                    (safe_ids,),
                ).fetchall()
        except psycopg.Error as exc:
            raise DatabaseToolPayloadRepositoryError("数据库 MCP 调用详情读取失败") from exc
        return {record.tool_call_id: record for record in map(_record_from_row, rows)}

    def expire_payloads(self, *, expired_at: datetime) -> int:
        database_url = self._require_database_url()
        try:
            with psycopg.connect(database_url) as connection:
                cursor = connection.execute(
                    """
                    UPDATE mcp_database_tool_payloads
                    SET
                        request_payload = NULL,
                        response_payload = NULL,
                        response_status = 'expired',
                        capture_error_code = NULL,
                        updated_at = %s
                    WHERE expires_at <= %s
                      AND response_status <> 'expired'
                    """,
                    (expired_at, expired_at),
                )
                return max(cursor.rowcount, 0)
        except psycopg.Error as exc:
            raise DatabaseToolPayloadRepositoryError("过期数据库 MCP 调用详情清理失败") from exc

    def interrupt_pending(self, *, interrupted_at: datetime) -> int:
        database_url = self._require_database_url()
        try:
            with psycopg.connect(database_url) as connection:
                cursor = connection.execute(
                    """
                    UPDATE mcp_database_tool_payloads
                    SET
                        response_status = 'interrupted',
                        capture_error_code = 'server_restarted',
                        updated_at = %s
                    WHERE response_status = 'pending'
                    """,
                    (interrupted_at,),
                )
                return max(cursor.rowcount, 0)
        except psycopg.Error as exc:
            raise DatabaseToolPayloadRepositoryError("数据库 MCP 调用详情恢复失败") from exc

    def _require_database_url(self) -> str:
        if not self._database_url:
            raise DatabaseToolPayloadRepositoryError("任务数据库尚未配置")
        return self._database_url


_SELECT_PAYLOAD = """
SELECT
    tool_call_id,
    tool_name,
    request_payload,
    response_payload,
    response_status,
    request_bytes,
    response_bytes,
    request_truncated,
    response_truncated,
    capture_version,
    capture_error_code,
    expires_at,
    created_at,
    updated_at
FROM mcp_database_tool_payloads
"""

_SELECT_PAYLOAD_METADATA = """
SELECT
    tool_call_id,
    tool_name,
    NULL::jsonb AS request_payload,
    NULL::jsonb AS response_payload,
    response_status,
    request_bytes,
    response_bytes,
    request_truncated,
    response_truncated,
    capture_version,
    capture_error_code,
    expires_at,
    created_at,
    updated_at
FROM mcp_database_tool_payloads
"""

_DATABASE_TOOL_NAMES = {
    "search_database_objects",
    "execute_database_query",
}
_PAYLOAD_STATUSES = {
    "pending",
    "ok",
    "error",
    "cancelled",
    "interrupted",
    "capture_failed",
    "expired",
}


def _validate_write(payload: DatabaseToolPayloadWrite) -> None:
    if payload.tool_call_id < 1:
        raise DatabaseToolPayloadRepositoryError("MCP 工具调用号必须大于 0")
    if payload.tool_name not in _DATABASE_TOOL_NAMES:
        raise DatabaseToolPayloadRepositoryError("只允许保存数据库 MCP 工具详情")
    if payload.request_bytes < 0:
        raise DatabaseToolPayloadRepositoryError("入参详情字节数不能小于 0")
    if payload.capture_version < 1:
        raise DatabaseToolPayloadRepositoryError("采集版本必须大于 0")


def _validate_completion(
    *,
    tool_call_id: int,
    status: DatabaseToolPayloadStatus,
    response_bytes: int | None,
    capture_error_code: str | None,
) -> None:
    if tool_call_id < 1:
        raise DatabaseToolPayloadRepositoryError("MCP 工具调用号必须大于 0")
    if status not in _PAYLOAD_STATUSES:
        raise DatabaseToolPayloadRepositoryError("数据库 MCP 详情状态不受支持")
    if response_bytes is not None and response_bytes < 0:
        raise DatabaseToolPayloadRepositoryError("出参详情字节数不能小于 0")
    if capture_error_code is not None and len(capture_error_code) > 64:
        raise DatabaseToolPayloadRepositoryError("采集错误码长度不能超过 64")


def _validate_tool_call_ids(tool_call_ids: list[int]) -> list[int]:
    if any(tool_call_id < 1 for tool_call_id in tool_call_ids):
        raise DatabaseToolPayloadRepositoryError("MCP 工具调用号必须大于 0")
    return list(dict.fromkeys(tool_call_ids))


def _record_from_row(row: tuple[object, ...]) -> DatabaseToolPayloadRecord:
    return DatabaseToolPayloadRecord(
        tool_call_id=int(row[0]),
        tool_name=str(row[1]),
        request_payload=cast(dict[str, object] | None, row[2]),
        response_payload=cast(dict[str, object] | None, row[3]),
        response_status=cast(DatabaseToolPayloadStatus, str(row[4])),
        request_bytes=int(row[5]) if row[5] is not None else None,
        response_bytes=int(row[6]) if row[6] is not None else None,
        request_truncated=bool(row[7]),
        response_truncated=bool(row[8]),
        capture_version=int(row[9]),
        capture_error_code=str(row[10]) if row[10] is not None else None,
        expires_at=cast(datetime, row[11]),
        created_at=cast(datetime, row[12]),
        updated_at=cast(datetime, row[13]),
    )
