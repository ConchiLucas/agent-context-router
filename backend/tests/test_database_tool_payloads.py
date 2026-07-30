from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp.server.fastmcp.exceptions import ToolError

from context_router.api.mcp_traces import router as mcp_traces_router
from context_router.database.errors import DatabaseAccessError
from context_router.mcp_server import create_context_router_mcp
from context_router.repositories.database_call_repository import DatabaseCallRecord
from context_router.repositories.database_tool_payload_repository import (
    DatabaseToolPayloadWrite,
    InMemoryDatabaseToolPayloadRepository,
)
from context_router.repositories.document_read_repository import DocumentReadCallRecord
from context_router.repositories.mcp_tool_call_repository import (
    InMemoryMcpToolCallRepository,
    McpToolCallWrite,
)
from context_router.repositories.task_repository import TaskRecord, TaskRepositoryError
from context_router.services.database_tool_payload import DatabaseToolPayloadService
from context_router.services.mcp_trace import McpTraceService


class StaticTaskStore:
    def __init__(self, task: TaskRecord) -> None:
        self.task = task

    def get_task(self, task_id: int) -> TaskRecord:
        if task_id != self.task.id:
            raise TaskRepositoryError("任务不存在")
        return self.task


class EmptyDocumentReadStore:
    def list_read_calls(self, task_id: int) -> list[DocumentReadCallRecord]:
        return []


class EmptyDatabaseCallStore:
    def list_calls(self, task_id: int) -> list[DatabaseCallRecord]:
        return []


class UnusedPreparation:
    def prepare(self, **_: object) -> object:
        raise AssertionError("prepare should not be called")


class UnusedRead:
    def read(self, **_: object) -> object:
        raise AssertionError("read should not be called")


class StaticQuery:
    def execute(self, **_: object) -> dict[str, object]:
        return {"rows": [[1]], "returned_rows": 1}


class LeakyFailingQuery:
    def execute(self, **_: object) -> dict[str, object]:
        raise DatabaseAccessError(
            "connection_failed",
            "password=should-never-be-persisted host=10.0.0.1",
        )


class FailingPayloadRepository(InMemoryDatabaseToolPayloadRepository):
    def create_request(self, payload: DatabaseToolPayloadWrite) -> None:
        raise RuntimeError(f"payload store unavailable: {payload.tool_call_id}")


def _task() -> TaskRecord:
    return TaskRecord(
        id=77,
        project_id="project-77",
        project_key="project-key",
        project_name="测试项目",
        task="查询数据库",
        cwd="/workspace/project",
        agent_name="codex",
        created_at=datetime.now(UTC),
    )


def _trace_service(
    tool_calls: InMemoryMcpToolCallRepository,
    payloads: DatabaseToolPayloadService,
) -> McpTraceService:
    return McpTraceService(
        tool_call_repository=tool_calls,
        task_repository=StaticTaskStore(_task()),
        document_read_repository=EmptyDocumentReadStore(),
        database_call_repository=EmptyDatabaseCallStore(),
        registry=object(),  # type: ignore[arg-type]
        database_payload_service=payloads,
    )


def _result_payload(result: object) -> dict[str, object]:
    if isinstance(result, dict):
        return result
    if isinstance(result, tuple) and len(result) >= 2 and isinstance(result[1], dict):
        return result[1]
    for attribute in ("structuredContent", "structured_content"):
        payload = getattr(result, attribute, None)
        if isinstance(payload, dict):
            return payload
    raise AssertionError("MCP result does not contain structured content")


def test_only_database_tools_create_full_payload_snapshots() -> None:
    repository = InMemoryDatabaseToolPayloadRepository()
    DatabaseToolPayloadService(repository)


def test_disabled_capture_still_expires_previous_payloads() -> None:
    repository = InMemoryDatabaseToolPayloadRepository()
    repository.create_request(
        DatabaseToolPayloadWrite(
            tool_call_id=2,
            tool_name="execute_database_query",
            request_payload={"sql": "SELECT secret FROM private_table"},
            request_bytes=42,
            request_truncated=False,
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    service = DatabaseToolPayloadService(repository)

    service.capture_request(
        3,
        tool_name="execute_database_query",
        arguments={"sql": "SELECT 1"},
    )

    record = repository.get_payload(2)
    assert record is not None
    assert record.response_status == "expired"
    assert record.request_payload is None


def test_payload_capture_truncates_sql_and_database_rows_as_valid_json() -> None:
    repository = InMemoryDatabaseToolPayloadRepository()
    service = DatabaseToolPayloadService(
        repository,
        request_max_bytes=1_024,
        response_max_bytes=1_024,
        hard_max_bytes=4_000_000,
    )
    service.capture_request(
        3,
        tool_name="execute_database_query",
        arguments={
            "task_id": 77,
            "database": "analytics",
            "sql": "SELECT '" + ("汉" * 2_000) + "'",
        },
    )
    service.capture_response(
        3,
        tool_name="execute_database_query",
        status="ok",
        payload={
            "columns": [{"name": "value", "type": "text"}],
            "rows": [[f"row-{index}-" + ("x" * 300)] for index in range(20)],
            "returned_rows": 20,
            "truncated": False,
        },
    )

    record = repository.get_payload(3)
    assert record is not None
    assert record.request_truncated is True
    assert record.response_truncated is True
    assert record.request_bytes is not None and record.request_bytes <= 1_024
    assert record.response_bytes is not None and record.response_bytes <= 1_024
    assert record.request_payload is not None
    assert record.request_payload["_capture"]["reason"] == "capture_bytes"  # type: ignore[index]
    assert record.response_payload is not None
    capture = record.response_payload["_capture"]
    assert capture["collection"] == "rows"  # type: ignore[index]
    assert capture["stored_count"] < capture["original_count"]  # type: ignore[index,operator]


def test_expired_payload_clears_snapshots_but_keeps_status_metadata() -> None:
    repository = InMemoryDatabaseToolPayloadRepository()
    repository.create_request(
        DatabaseToolPayloadWrite(
            tool_call_id=4,
            tool_name="search_database_objects",
            request_payload={"task_id": 77, "database": "analytics"},
            request_bytes=42,
            request_truncated=False,
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    repository.complete_response(
        4,
        status="ok",
        response_payload={"objects": [{"name": "orders"}]},
        response_bytes=32,
        response_truncated=False,
    )

    service = DatabaseToolPayloadService(repository)
    assert service.cleanup_expired(force=True) == 1

    record = repository.get_payload(4)
    assert record is not None
    assert record.response_status == "expired"
    assert record.request_payload is None
    assert record.response_payload is None


def test_trace_api_exposes_only_payload_availability_then_loads_no_store_detail() -> None:
    tool_calls = InMemoryMcpToolCallRepository()
    tool_call_id = tool_calls.create_call(
        McpToolCallWrite(
            task_id=77,
            server_name="context-router",
            tool_name="execute_database_query",
            source="server",
            status="ok",
            finished_at=datetime.now(UTC),
            duration_ms=3,
            request_summary={"database": "analytics", "sql_sha256": "hash"},
        )
    )
    payload_repository = InMemoryDatabaseToolPayloadRepository()
    payload_service = DatabaseToolPayloadService(payload_repository)
    payload_service.capture_request(
        tool_call_id,
        tool_name="execute_database_query",
        arguments={
            "task_id": 77,
            "database": "analytics",
            "sql": "SELECT secret FROM private_table",
        },
    )
    payload_service.capture_response(
        tool_call_id,
        tool_name="execute_database_query",
        status="ok",
        payload={"rows": [["private-result"]], "returned_rows": 1},
    )
    service = _trace_service(tool_calls, payload_service)
    app = FastAPI()
    app.state.mcp_trace_service = service
    app.include_router(mcp_traces_router, prefix="/api")

    with TestClient(app) as client:
        trace_response = client.get("/api/mcp-traces/77")
        payload_response = client.get(f"/api/mcp-traces/77/calls/{tool_call_id}/database-payload")

    assert trace_response.status_code == 200
    trace_body = trace_response.json()
    assert trace_body["calls"][0]["database_payload_available"] is True
    assert trace_body["calls"][0]["database_payload_status"] == "ok"
    assert "SELECT secret" not in repr(trace_body)
    assert "private-result" not in repr(trace_body)

    assert payload_response.status_code == 200
    assert payload_response.headers["cache-control"] == "no-store"
    payload_body = payload_response.json()
    assert payload_body["available"] is True
    assert payload_body["request_payload"]["sql"] == "SELECT secret FROM private_table"
    assert payload_body["response_payload"]["rows"] == [["private-result"]]


def test_payload_detail_rejects_cross_task_and_non_database_calls() -> None:
    tool_calls = InMemoryMcpToolCallRepository()
    read_call_id = tool_calls.create_call(
        McpToolCallWrite(
            task_id=77,
            server_name="context-router",
            tool_name="read_context_document",
            source="server",
            status="ok",
            finished_at=datetime.now(UTC),
            duration_ms=1,
        )
    )
    payload_service = DatabaseToolPayloadService(
        InMemoryDatabaseToolPayloadRepository(),
    )
    service = _trace_service(tool_calls, payload_service)
    app = FastAPI()
    app.state.mcp_trace_service = service
    app.include_router(mcp_traces_router, prefix="/api")

    with TestClient(app) as client:
        non_database = client.get(f"/api/mcp-traces/77/calls/{read_call_id}/database-payload")
        cross_task = client.get(f"/api/mcp-traces/999/calls/{read_call_id}/database-payload")

    assert non_database.status_code == 400
    assert "数据库 MCP" in non_database.json()["detail"]
    assert cross_task.status_code == 400


def test_historical_database_call_without_snapshot_returns_available_false() -> None:
    tool_calls = InMemoryMcpToolCallRepository()
    tool_call_id = tool_calls.create_call(
        McpToolCallWrite(
            task_id=77,
            server_name="context-router",
            tool_name="search_database_objects",
            source="legacy",
            status="ok",
            finished_at=datetime.now(UTC),
            duration_ms=1,
        )
    )
    payload_service = DatabaseToolPayloadService(
        InMemoryDatabaseToolPayloadRepository(),
    )
    detail = _trace_service(tool_calls, payload_service).get_database_payload(
        task_id=77,
        tool_call_id=tool_call_id,
    )

    assert detail.available is False
    assert detail.reason == "not_captured"
    assert detail.request_payload is None
    assert detail.response_payload is None


def test_payload_persistence_failure_does_not_change_database_tool_result() -> None:
    tool_calls = InMemoryMcpToolCallRepository()
    payload_service = DatabaseToolPayloadService(
        FailingPayloadRepository(),
    )
    server = create_context_router_mcp(
        UnusedPreparation(),  # type: ignore[arg-type]
        UnusedRead(),  # type: ignore[arg-type]
        database_query_service=StaticQuery(),  # type: ignore[arg-type]
        trace_service=_trace_service(tool_calls, payload_service),
        database_payload_service=payload_service,
    )

    result = asyncio.run(
        server.call_tool(
            "execute_database_query",
            {"task_id": 77, "database": "analytics", "sql": "SELECT 1"},
        )
    )
    payload = _result_payload(result)

    assert payload["rows"] == [[1]]
    assert tool_calls.list_calls(77)[0].status == "ok"


def test_database_error_payload_uses_stable_public_message_without_exception_text() -> None:
    tool_calls = InMemoryMcpToolCallRepository()
    payload_repository = InMemoryDatabaseToolPayloadRepository()
    payload_service = DatabaseToolPayloadService(payload_repository)
    server = create_context_router_mcp(
        UnusedPreparation(),  # type: ignore[arg-type]
        UnusedRead(),  # type: ignore[arg-type]
        database_query_service=LeakyFailingQuery(),  # type: ignore[arg-type]
        trace_service=_trace_service(tool_calls, payload_service),
        database_payload_service=payload_service,
    )

    with pytest.raises(ToolError, match="connection_failed"):
        asyncio.run(
            server.call_tool(
                "execute_database_query",
                {"task_id": 77, "database": "analytics", "sql": "SELECT 1"},
            )
        )

    call = tool_calls.list_calls(77)[0]
    payload_record = payload_repository.get_payload(call.id)
    assert payload_record is not None
    assert payload_record.response_payload == {
        "error": {
            "code": "connection_failed",
            "message": "数据库当前无法连接",
        }
    }
    assert "password" not in repr(payload_record)
    assert "10.0.0.1" not in repr(payload_record)
