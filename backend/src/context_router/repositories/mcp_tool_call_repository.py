from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from threading import RLock
from typing import Literal, Protocol, cast

import psycopg
from psycopg.types.json import Jsonb

from context_router.mcp_contract import (
    CONTEXT_ROUTER_TRACE_SERVER_NAME,
    CONTEXT_ROUTER_TRACE_SOURCES,
    CONTEXT_ROUTER_TRACE_TOOL_NAMES,
)

McpToolCallSource = Literal["server", "gateway", "reported", "legacy"]
McpToolCallStatus = Literal["running", "ok", "error", "cancelled"]


class McpToolCallRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class McpToolCallWrite:
    task_id: int
    server_name: str
    tool_name: str
    source: McpToolCallSource
    status: McpToolCallStatus = "running"
    parent_tool_call_id: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    request_summary: dict[str, object] | None = None
    result_summary: dict[str, object] | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class McpToolCallRecord:
    id: int
    task_id: int
    parent_tool_call_id: int | None
    server_name: str
    tool_name: str
    source: McpToolCallSource
    status: McpToolCallStatus
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    request_summary: dict[str, object] | None
    result_summary: dict[str, object] | None
    error_code: str | None


@dataclass(frozen=True, slots=True)
class McpTraceTaskRecord:
    task_id: int
    project_id: str | None
    project_key: str
    project_name: str
    task: str
    cwd: str
    agent_name: str | None
    created_at: datetime
    call_count: int
    error_count: int
    server_names: list[str]
    last_activity_at: datetime
    prepare_call_count: int = 0
    running_call_count: int = 0
    legacy_call_count: int = 0
    interrupted_call_count: int = 0
    unlinked_document_read_count: int = 0
    unlinked_database_call_count: int = 0


class McpToolCallStore(Protocol):
    def create_call(self, call: McpToolCallWrite) -> int: ...

    def complete_call(
        self,
        tool_call_id: int,
        *,
        status: McpToolCallStatus,
        finished_at: datetime,
        duration_ms: int,
        result_summary: dict[str, object] | None = None,
        error_code: str | None = None,
    ) -> None: ...

    def list_calls(self, task_id: int) -> list[McpToolCallRecord]: ...

    def fail_running_calls(self, *, finished_at: datetime) -> int: ...

    def list_traces(
        self,
        *,
        project_id: str | None = None,
        project_key: str | None = None,
        agent_name: str | None = None,
        server_name: str | None = None,
        tool_name: str | None = None,
        status: McpToolCallStatus | None = None,
        keyword: str | None = None,
        limit: int = 30,
    ) -> list[McpTraceTaskRecord]: ...


class InMemoryMcpToolCallRepository:
    """Test/degraded-mode recorder.

    Task metadata lives in PostgreSQL, so trace list queries are intentionally empty in
    degraded mode. Individual tool calls are still recorded for isolated tests.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._next_id = 1
        self._calls: list[McpToolCallRecord] = []

    def create_call(self, call: McpToolCallWrite) -> int:
        _validate_call(call)
        with self._lock:
            tool_call_id = self._next_id
            self._next_id += 1
            self._calls.append(
                McpToolCallRecord(
                    id=tool_call_id,
                    task_id=call.task_id,
                    parent_tool_call_id=call.parent_tool_call_id,
                    server_name=call.server_name,
                    tool_name=call.tool_name,
                    source=call.source,
                    status=call.status,
                    started_at=call.started_at or datetime.now(UTC),
                    finished_at=call.finished_at,
                    duration_ms=call.duration_ms,
                    request_summary=call.request_summary,
                    result_summary=call.result_summary,
                    error_code=call.error_code,
                )
            )
            return tool_call_id

    def complete_call(
        self,
        tool_call_id: int,
        *,
        status: McpToolCallStatus,
        finished_at: datetime,
        duration_ms: int,
        result_summary: dict[str, object] | None = None,
        error_code: str | None = None,
    ) -> None:
        _validate_completion(
            tool_call_id=tool_call_id,
            status=status,
            duration_ms=duration_ms,
            error_code=error_code,
        )
        with self._lock:
            for index, call in enumerate(self._calls):
                if call.id != tool_call_id:
                    continue
                self._calls[index] = replace(
                    call,
                    status=status,
                    finished_at=finished_at,
                    duration_ms=duration_ms,
                    result_summary=result_summary,
                    error_code=error_code,
                )
                return
        raise McpToolCallRepositoryError("MCP 工具调用不存在")

    def list_calls(self, task_id: int) -> list[McpToolCallRecord]:
        if task_id < 1:
            raise McpToolCallRepositoryError("任务号必须大于 0")
        with self._lock:
            return [call for call in self._calls if call.task_id == task_id]

    def fail_running_calls(self, *, finished_at: datetime) -> int:
        updated = 0
        with self._lock:
            for index, call in enumerate(self._calls):
                if call.status != "running":
                    continue
                duration_ms = max(
                    0,
                    round((finished_at - call.started_at).total_seconds() * 1000),
                )
                self._calls[index] = replace(
                    call,
                    status="error",
                    finished_at=finished_at,
                    duration_ms=duration_ms,
                    error_code="server_restarted",
                )
                updated += 1
        return updated

    def list_traces(
        self,
        *,
        project_id: str | None = None,
        project_key: str | None = None,
        agent_name: str | None = None,
        server_name: str | None = None,
        tool_name: str | None = None,
        status: McpToolCallStatus | None = None,
        keyword: str | None = None,
        limit: int = 30,
    ) -> list[McpTraceTaskRecord]:
        return []


class PostgresMcpToolCallRepository:
    def __init__(self, database_url: str | None) -> None:
        self._database_url = database_url.strip() if database_url else None

    def create_call(self, call: McpToolCallWrite) -> int:
        _validate_call(call)
        database_url = self._require_database_url()
        try:
            with psycopg.connect(database_url) as connection:
                row = connection.execute(
                    """
                    INSERT INTO mcp_tool_calls (
                        task_id,
                        parent_tool_call_id,
                        server_name,
                        tool_name,
                        source,
                        status,
                        started_at,
                        finished_at,
                        duration_ms,
                        request_summary,
                        result_summary,
                        error_code
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, COALESCE(%s, CURRENT_TIMESTAMP),
                        %s, %s, %s, %s, %s
                    )
                    RETURNING id
                    """,
                    (
                        call.task_id,
                        call.parent_tool_call_id,
                        call.server_name,
                        call.tool_name,
                        call.source,
                        call.status,
                        call.started_at,
                        call.finished_at,
                        call.duration_ms,
                        Jsonb(call.request_summary) if call.request_summary is not None else None,
                        Jsonb(call.result_summary) if call.result_summary is not None else None,
                        call.error_code,
                    ),
                ).fetchone()
        except psycopg.errors.ForeignKeyViolation as exc:
            raise McpToolCallRepositoryError("任务或父调用不存在") from exc
        except psycopg.Error as exc:
            raise McpToolCallRepositoryError("MCP 工具调用写入失败") from exc

        if row is None:
            raise McpToolCallRepositoryError("MCP 工具调用写入后没有返回调用号")
        return int(row[0])

    def complete_call(
        self,
        tool_call_id: int,
        *,
        status: McpToolCallStatus,
        finished_at: datetime,
        duration_ms: int,
        result_summary: dict[str, object] | None = None,
        error_code: str | None = None,
    ) -> None:
        _validate_completion(
            tool_call_id=tool_call_id,
            status=status,
            duration_ms=duration_ms,
            error_code=error_code,
        )
        database_url = self._require_database_url()
        try:
            with psycopg.connect(database_url) as connection:
                row = connection.execute(
                    """
                    UPDATE mcp_tool_calls
                    SET
                        status = %s,
                        finished_at = %s,
                        duration_ms = %s,
                        result_summary = %s,
                        error_code = %s
                    WHERE id = %s
                    RETURNING id
                    """,
                    (
                        status,
                        finished_at,
                        duration_ms,
                        Jsonb(result_summary) if result_summary is not None else None,
                        error_code,
                        tool_call_id,
                    ),
                ).fetchone()
        except psycopg.Error as exc:
            raise McpToolCallRepositoryError("MCP 工具调用完成状态写入失败") from exc
        if row is None:
            raise McpToolCallRepositoryError("MCP 工具调用不存在")

    def list_calls(self, task_id: int) -> list[McpToolCallRecord]:
        if task_id < 1:
            raise McpToolCallRepositoryError("任务号必须大于 0")
        database_url = self._require_database_url()
        try:
            with psycopg.connect(database_url) as connection:
                rows = connection.execute(
                    """
                    SELECT
                        id,
                        task_id,
                        parent_tool_call_id,
                        server_name,
                        tool_name,
                        source,
                        status,
                        started_at,
                        finished_at,
                        duration_ms,
                        request_summary,
                        result_summary,
                        error_code
                    FROM mcp_tool_calls
                    WHERE task_id = %s
                      AND server_name = 'context-router'
                      AND tool_name IN (
                            'prepare_task_context',
                            'read_task_context',
                            'read_middleware_context',
                            'search_context_documents',
                            'read_context_document',
                            'search_database_objects',
                            'execute_database_query',
                            'list_task_containers',
                            'inspect_container_errors',
                            'read_table_relations',
                            'search_relation_tables',
                            'search_value_mappings',
                            'resolve_value_candidates',
                            'search_forwarding_interfaces',
                            'read_forwarding_request_history',
                            'prepare_forwarding_request',
                            'execute_forwarding_request',
                            'prepare_table_relation_context',
                            'apply_workspace_changes',
                            'start_workspace',
                            'get_workspace_operation',
                            'apply_project_changes',
                            'get_project_operation'
                      )
                      AND source IN ('server', 'legacy')
                    ORDER BY id
                    """,
                    (task_id,),
                ).fetchall()
        except psycopg.Error as exc:
            raise McpToolCallRepositoryError("MCP 工具调用读取失败") from exc
        return [_call_from_row(row) for row in rows]

    def fail_running_calls(self, *, finished_at: datetime) -> int:
        database_url = self._require_database_url()
        try:
            with psycopg.connect(database_url) as connection:
                cursor = connection.execute(
                    """
                    UPDATE mcp_tool_calls
                    SET
                        status = 'error',
                        finished_at = %s,
                        duration_ms = LEAST(
                            2147483647,
                            GREATEST(
                                0,
                                FLOOR(EXTRACT(EPOCH FROM (%s - started_at)) * 1000)
                            )
                        )::integer,
                        error_code = 'server_restarted'
                    WHERE status = 'running'
                      AND server_name = 'context-router'
                      AND tool_name IN (
                            'prepare_task_context',
                            'read_task_context',
                            'read_middleware_context',
                            'search_context_documents',
                            'read_context_document',
                            'search_database_objects',
                            'execute_database_query',
                            'list_task_containers',
                            'inspect_container_errors',
                            'read_table_relations',
                            'search_relation_tables',
                            'search_value_mappings',
                            'resolve_value_candidates',
                            'search_forwarding_interfaces',
                            'read_forwarding_request_history',
                            'prepare_forwarding_request',
                            'execute_forwarding_request',
                            'prepare_table_relation_context',
                            'apply_workspace_changes',
                            'start_workspace',
                            'get_workspace_operation',
                            'apply_project_changes',
                            'get_project_operation'
                      )
                      AND source = 'server'
                    """,
                    (finished_at, finished_at),
                )
                return max(cursor.rowcount, 0)
        except psycopg.Error as exc:
            raise McpToolCallRepositoryError("遗留 MCP 工具调用恢复失败") from exc

    def list_traces(
        self,
        *,
        project_id: str | None = None,
        project_key: str | None = None,
        agent_name: str | None = None,
        server_name: str | None = None,
        tool_name: str | None = None,
        status: McpToolCallStatus | None = None,
        keyword: str | None = None,
        limit: int = 30,
    ) -> list[McpTraceTaskRecord]:
        if status is not None and status not in {"running", "ok", "error", "cancelled"}:
            raise McpToolCallRepositoryError("MCP 工具调用状态不受支持")
        if server_name is not None and (server_name.casefold() != CONTEXT_ROUTER_TRACE_SERVER_NAME):
            return []
        if tool_name is not None and tool_name not in CONTEXT_ROUTER_TRACE_TOOL_NAMES:
            return []
        safe_limit = min(max(limit, 1), 100)
        normalized_keyword = keyword.strip() if keyword else None
        keyword_pattern = f"%{normalized_keyword}%" if normalized_keyword else None
        database_url = self._require_database_url()
        try:
            with psycopg.connect(database_url) as connection:
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
                        COUNT(tool_call.id) AS call_count,
                        COUNT(tool_call.id) FILTER (
                            WHERE tool_call.tool_name = 'prepare_task_context'
                        ) AS prepare_call_count,
                        COUNT(tool_call.id) FILTER (
                            WHERE tool_call.status = 'error'
                        ) AS error_count,
                        COUNT(tool_call.id) FILTER (
                            WHERE tool_call.status = 'running'
                        ) AS running_call_count,
                        COUNT(tool_call.id) FILTER (
                            WHERE tool_call.source = 'legacy'
                        ) AS legacy_call_count,
                        COUNT(tool_call.id) FILTER (
                            WHERE tool_call.error_code = 'server_restarted'
                        ) AS interrupted_call_count,
                        COALESCE(
                            ARRAY_AGG(DISTINCT tool_call.server_name)
                                FILTER (WHERE tool_call.server_name IS NOT NULL),
                            ARRAY[]::varchar[]
                        ) AS server_names,
                        MAX(
                            COALESCE(
                                tool_call.finished_at,
                                tool_call.started_at,
                                task.created_at
                            )
                        ) AS last_activity_at,
                        (
                            SELECT COUNT(*)
                            FROM mcp_document_read_calls AS unlinked_read
                            WHERE unlinked_read.task_id = task.id
                              AND (
                                    unlinked_read.tool_call_id IS NULL
                                    OR NOT EXISTS (
                                        SELECT 1
                                        FROM mcp_tool_calls AS linked_read_call
                                        WHERE linked_read_call.id = unlinked_read.tool_call_id
                                          AND linked_read_call.task_id = unlinked_read.task_id
                                          AND linked_read_call.server_name = 'context-router'
                                          AND linked_read_call.source IN ('server', 'legacy')
                                          AND linked_read_call.tool_name =
                                                'read_context_document'
                                    )
                              )
                        ) AS unlinked_document_read_count,
                        (
                            SELECT COUNT(*)
                            FROM mcp_database_calls AS unlinked_database
                            WHERE unlinked_database.task_id = task.id
                              AND (
                                    unlinked_database.tool_call_id IS NULL
                                    OR NOT EXISTS (
                                        SELECT 1
                                        FROM mcp_tool_calls AS linked_database_call
                                        WHERE linked_database_call.id =
                                              unlinked_database.tool_call_id
                                          AND linked_database_call.task_id =
                                                unlinked_database.task_id
                                          AND linked_database_call.server_name = 'context-router'
                                          AND linked_database_call.source IN ('server', 'legacy')
                                          AND (
                                                (
                                                    unlinked_database.operation =
                                                        'search_objects'
                                                    AND linked_database_call.tool_name =
                                                        'search_database_objects'
                                                )
                                                OR (
                                                    unlinked_database.operation =
                                                        'execute_query'
                                                    AND linked_database_call.tool_name =
                                                        'execute_database_query'
                                                )
                                          )
                                    )
                              )
                        ) AS unlinked_database_call_count
                    FROM mcp_tasks AS task
                    LEFT JOIN mcp_tool_calls AS tool_call
                      ON tool_call.task_id = task.id
                     AND tool_call.server_name = 'context-router'
                     AND tool_call.tool_name IN (
                            'prepare_task_context',
                            'read_task_context',
                            'read_middleware_context',
                            'search_context_documents',
                            'read_context_document',
                            'search_database_objects',
                            'execute_database_query',
                            'list_task_containers',
                            'inspect_container_errors',
                            'read_table_relations',
                            'search_relation_tables',
                            'search_value_mappings',
                            'resolve_value_candidates',
                            'search_forwarding_interfaces',
                            'read_forwarding_request_history',
                            'prepare_forwarding_request',
                            'execute_forwarding_request',
                            'prepare_table_relation_context',
                            'apply_workspace_changes',
                            'start_workspace',
                            'get_workspace_operation',
                            'apply_project_changes',
                            'get_project_operation'
                     )
                     AND tool_call.source IN ('server', 'legacy')
                    WHERE (
                            %s::text IS NULL
                            OR task.project_id = %s
                            OR (task.project_id IS NULL AND task.project_key = %s)
                      )
                      AND (%s::text IS NULL OR lower(task.agent_name) = lower(%s))
                      AND task.agent_name IS DISTINCT FROM 'connection-test'
                      AND task.agent_name IS DISTINCT FROM 'web-preview'
                      AND (
                            %s::text IS NULL
                            OR EXISTS (
                                SELECT 1
                                FROM mcp_tool_calls AS filtered_server
                                WHERE filtered_server.task_id = task.id
                                  AND filtered_server.source IN ('server', 'legacy')
                                  AND filtered_server.tool_name IN (
                                        'prepare_task_context',
                                        'read_task_context',
                                        'read_middleware_context',
                                        'search_context_documents',
                                        'read_context_document',
                                        'search_database_objects',
                                        'execute_database_query',
                                        'list_task_containers',
                                        'inspect_container_errors',
                                        'read_table_relations',
                                        'search_relation_tables',
                                        'search_value_mappings',
                                        'resolve_value_candidates',
                                        'search_forwarding_interfaces',
                                        'read_forwarding_request_history',
                                        'prepare_forwarding_request',
                                        'execute_forwarding_request',
                                        'prepare_table_relation_context',
                                        'apply_workspace_changes',
                                        'start_workspace',
                                        'get_workspace_operation',
                                        'apply_project_changes',
                                        'get_project_operation'
                                  )
                                  AND lower(filtered_server.server_name) = lower(%s)
                            )
                      )
                      AND (
                            %s::text IS NULL
                            OR EXISTS (
                                SELECT 1
                                FROM mcp_tool_calls AS filtered_tool
                                WHERE filtered_tool.task_id = task.id
                                  AND filtered_tool.server_name = 'context-router'
                                  AND filtered_tool.source IN ('server', 'legacy')
                                  AND filtered_tool.tool_name = %s
                            )
                      )
                      AND (
                            %s::text IS NULL
                            OR EXISTS (
                                SELECT 1
                                FROM mcp_tool_calls AS filtered_status
                                WHERE filtered_status.task_id = task.id
                                  AND filtered_status.server_name = 'context-router'
                                  AND filtered_status.source IN ('server', 'legacy')
                                  AND filtered_status.tool_name IN (
                                        'prepare_task_context',
                                        'read_task_context',
                                        'read_middleware_context',
                                        'search_context_documents',
                                        'read_context_document',
                                        'search_database_objects',
                                        'execute_database_query',
                                        'list_task_containers',
                                        'inspect_container_errors',
                                        'read_table_relations',
                                        'search_relation_tables',
                                        'search_value_mappings',
                                        'resolve_value_candidates',
                                        'search_forwarding_interfaces',
                                        'read_forwarding_request_history',
                                        'prepare_forwarding_request',
                                        'execute_forwarding_request',
                                        'prepare_table_relation_context',
                                        'apply_workspace_changes',
                                        'start_workspace',
                                        'get_workspace_operation',
                                        'apply_project_changes',
                                        'get_project_operation'
                                  )
                                  AND filtered_status.status = %s
                            )
                      )
                      AND (
                            %s::text IS NULL
                            OR task.task ILIKE %s
                            OR task.project_name ILIKE %s
                            OR task.cwd ILIKE %s
                      )
                    GROUP BY task.id
                    ORDER BY last_activity_at DESC, task.id DESC
                    LIMIT %s
                    """,
                    (
                        project_id,
                        project_id,
                        project_key,
                        agent_name,
                        agent_name,
                        server_name,
                        server_name,
                        tool_name,
                        tool_name,
                        status,
                        status,
                        keyword_pattern,
                        keyword_pattern,
                        keyword_pattern,
                        keyword_pattern,
                        safe_limit,
                    ),
                ).fetchall()
        except psycopg.Error as exc:
            raise McpToolCallRepositoryError("MCP 任务链路列表读取失败") from exc
        return [_trace_from_row(row) for row in rows]

    def _require_database_url(self) -> str:
        if not self._database_url:
            raise McpToolCallRepositoryError("任务数据库尚未配置")
        return self._database_url


def _validate_call(call: McpToolCallWrite) -> None:
    if call.task_id < 1:
        raise McpToolCallRepositoryError("任务号必须大于 0")
    _validate_text(call.server_name, "MCP Server 名称", 64, required=True)
    _validate_text(call.tool_name, "MCP 工具名称", 128, required=True)
    if call.server_name != CONTEXT_ROUTER_TRACE_SERVER_NAME:
        raise McpToolCallRepositoryError("只允许记录 Context Router MCP 调用")
    if call.tool_name not in CONTEXT_ROUTER_TRACE_TOOL_NAMES:
        raise McpToolCallRepositoryError("MCP 工具不在内部追踪白名单")
    if call.source not in CONTEXT_ROUTER_TRACE_SOURCES:
        raise McpToolCallRepositoryError("只允许记录内部或历史 MCP 调用")
    if call.status not in {"running", "ok", "error", "cancelled"}:
        raise McpToolCallRepositoryError("MCP 工具调用状态不受支持")
    if call.parent_tool_call_id is not None and call.parent_tool_call_id < 1:
        raise McpToolCallRepositoryError("父调用号必须大于 0")
    if call.duration_ms is not None and call.duration_ms < 0:
        raise McpToolCallRepositoryError("调用耗时不能小于 0")
    _validate_text(call.error_code, "错误码", 64)


def _validate_completion(
    *,
    tool_call_id: int,
    status: McpToolCallStatus,
    duration_ms: int,
    error_code: str | None,
) -> None:
    if tool_call_id < 1:
        raise McpToolCallRepositoryError("MCP 工具调用号必须大于 0")
    if status not in {"ok", "error", "cancelled"}:
        raise McpToolCallRepositoryError("完成状态不受支持")
    if duration_ms < 0:
        raise McpToolCallRepositoryError("调用耗时不能小于 0")
    _validate_text(error_code, "错误码", 64)


def _validate_text(
    value: str | None,
    label: str,
    max_length: int,
    *,
    required: bool = False,
) -> None:
    if required and not value:
        raise McpToolCallRepositoryError(f"{label}不能为空")
    if value is not None and len(value) > max_length:
        raise McpToolCallRepositoryError(f"{label}长度不能超过 {max_length}")


def _call_from_row(row: tuple[object, ...]) -> McpToolCallRecord:
    return McpToolCallRecord(
        id=int(row[0]),
        task_id=int(row[1]),
        parent_tool_call_id=int(row[2]) if row[2] is not None else None,
        server_name=str(row[3]),
        tool_name=str(row[4]),
        source=cast(McpToolCallSource, str(row[5])),
        status=cast(McpToolCallStatus, str(row[6])),
        started_at=cast(datetime, row[7]),
        finished_at=cast(datetime | None, row[8]),
        duration_ms=int(row[9]) if row[9] is not None else None,
        request_summary=cast(dict[str, object] | None, row[10]),
        result_summary=cast(dict[str, object] | None, row[11]),
        error_code=str(row[12]) if row[12] is not None else None,
    )


def _trace_from_row(row: tuple[object, ...]) -> McpTraceTaskRecord:
    return McpTraceTaskRecord(
        task_id=int(row[0]),
        project_id=str(row[1]) if row[1] is not None else None,
        project_key=str(row[2]),
        project_name=str(row[3]),
        task=str(row[4]),
        cwd=str(row[5]),
        agent_name=str(row[6]) if row[6] is not None else None,
        created_at=cast(datetime, row[7]),
        call_count=int(row[8]),
        prepare_call_count=int(row[9]),
        error_count=int(row[10]),
        running_call_count=int(row[11]),
        legacy_call_count=int(row[12]),
        interrupted_call_count=int(row[13]),
        server_names=[str(name) for name in cast(list[object], row[14])],
        last_activity_at=cast(datetime, row[15]),
        unlinked_document_read_count=int(row[16]),
        unlinked_database_call_count=int(row[17]),
    )
