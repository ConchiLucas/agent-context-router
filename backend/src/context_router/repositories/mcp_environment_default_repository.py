from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import psycopg

from context_router.mcp_environment import require_mcp_environment


class McpEnvironmentDefaultRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class McpEnvironmentDefaultRecord:
    workspace_id: str
    tool_name: str
    environment: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class McpEnvironmentDefaultStore(Protocol):
    def list_defaults(self, workspace_id: str) -> list[McpEnvironmentDefaultRecord]: ...

    def get_default(self, workspace_id: str, tool_name: str) -> str | None: ...

    def upsert_default(
        self,
        *,
        workspace_id: str,
        tool_name: str,
        environment: str,
    ) -> McpEnvironmentDefaultRecord: ...


class InMemoryMcpEnvironmentDefaultRepository:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], McpEnvironmentDefaultRecord] = {}

    def list_defaults(self, workspace_id: str) -> list[McpEnvironmentDefaultRecord]:
        return sorted(
            (record for record in self._records.values() if record.workspace_id == workspace_id),
            key=lambda record: record.tool_name,
        )

    def get_default(self, workspace_id: str, tool_name: str) -> str | None:
        record = self._records.get((workspace_id, tool_name))
        return record.environment if record is not None else None

    def upsert_default(
        self,
        *,
        workspace_id: str,
        tool_name: str,
        environment: str,
    ) -> McpEnvironmentDefaultRecord:
        _validate(workspace_id, tool_name, environment)
        previous = self._records.get((workspace_id, tool_name))
        now = datetime.now(UTC)
        record = McpEnvironmentDefaultRecord(
            workspace_id=workspace_id,
            tool_name=tool_name,
            environment=environment,
            created_at=previous.created_at if previous is not None else now,
            updated_at=now,
        )
        self._records[(workspace_id, tool_name)] = record
        return record


class PostgresMcpEnvironmentDefaultRepository:
    def __init__(self, database_url: str | None) -> None:
        self._database_url = database_url.strip() if database_url else None

    def list_defaults(self, workspace_id: str) -> list[McpEnvironmentDefaultRecord]:
        try:
            with psycopg.connect(self._require_database_url()) as connection:
                rows = connection.execute(
                    """
                    SELECT workspace_id, tool_name, default_environment, created_at, updated_at
                    FROM workspace_mcp_environment_defaults
                    WHERE workspace_id = %s
                    ORDER BY tool_name
                    """,
                    (workspace_id,),
                ).fetchall()
        except psycopg.Error as exc:
            raise McpEnvironmentDefaultRepositoryError("MCP 默认环境读取失败") from exc
        return [_record(row) for row in rows]

    def get_default(self, workspace_id: str, tool_name: str) -> str | None:
        try:
            with psycopg.connect(self._require_database_url()) as connection:
                row = connection.execute(
                    """
                    SELECT default_environment
                    FROM workspace_mcp_environment_defaults
                    WHERE workspace_id = %s AND tool_name = %s
                    """,
                    (workspace_id, tool_name),
                ).fetchone()
        except psycopg.Error as exc:
            raise McpEnvironmentDefaultRepositoryError("MCP 默认环境读取失败") from exc
        return str(row[0]) if row is not None else None

    def upsert_default(
        self,
        *,
        workspace_id: str,
        tool_name: str,
        environment: str,
    ) -> McpEnvironmentDefaultRecord:
        _validate(workspace_id, tool_name, environment)
        try:
            with psycopg.connect(self._require_database_url()) as connection:
                row = connection.execute(
                    """
                    INSERT INTO workspace_mcp_environment_defaults (
                        workspace_id, tool_name, default_environment
                    )
                    VALUES (%s, %s, %s)
                    ON CONFLICT (workspace_id, tool_name) DO UPDATE SET
                        default_environment = EXCLUDED.default_environment,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING workspace_id, tool_name, default_environment,
                              created_at, updated_at
                    """,
                    (workspace_id, tool_name, environment),
                ).fetchone()
        except psycopg.Error as exc:
            raise McpEnvironmentDefaultRepositoryError("MCP 默认环境保存失败") from exc
        if row is None:
            raise McpEnvironmentDefaultRepositoryError("MCP 默认环境保存后没有返回记录")
        return _record(row)

    def _require_database_url(self) -> str:
        if not self._database_url:
            raise McpEnvironmentDefaultRepositoryError("控制面数据库尚未配置")
        return self._database_url


def _validate(workspace_id: str, tool_name: str, environment: str) -> None:
    if not workspace_id:
        raise McpEnvironmentDefaultRepositoryError("Workspace ID 不能为空")
    try:
        require_mcp_environment(tool_name, environment)
    except ValueError as exc:
        raise McpEnvironmentDefaultRepositoryError(str(exc)) from exc


def _record(row: tuple[object, ...]) -> McpEnvironmentDefaultRecord:
    return McpEnvironmentDefaultRecord(
        workspace_id=str(row[0]),
        tool_name=str(row[1]),
        environment=str(row[2]),
        created_at=row[3],  # type: ignore[arg-type]
        updated_at=row[4],  # type: ignore[arg-type]
    )
