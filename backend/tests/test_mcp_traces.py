import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp.server.fastmcp.exceptions import ToolError

from context_router.api.mcp_traces import router as mcp_traces_router
from context_router.config import Settings
from context_router.database.errors import DatabaseAccessError
from context_router.mcp_server import create_context_router_mcp
from context_router.repositories.database_call_repository import DatabaseCallRecord
from context_router.repositories.document_read_repository import (
    DocumentReadCallRecord,
    DocumentReadItemRecord,
)
from context_router.repositories.mcp_tool_call_repository import (
    InMemoryMcpToolCallRepository,
    McpToolCallWrite,
    McpTraceTaskRecord,
)
from context_router.repositories.task_repository import TaskRecord
from context_router.services.mcp_trace import McpTraceService
from context_router.services.project_registry import ProjectRegistry


class DumpResult:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def model_dump(self, **_: object) -> dict[str, object]:
        return self.payload


class RecordingPreparation:
    def prepare(self, **_: object) -> DumpResult:
        return DumpResult(
            {
                "task_id": 77,
                "project": {"project_id": "project", "name": "测试项目", "node_count": 3},
                "documents": {
                    "document_id": "root",
                    "path": "AGENTS.md",
                    "children": [],
                },
                "databases": [],
            }
        )


class RecordingRead:
    def read(self, **_: object) -> DumpResult:
        return DumpResult(
            {
                "task_id": 77,
                "read_call_id": 4,
                "documents": [
                    {
                        "position": 1,
                        "document_id": "root",
                        "path": "AGENTS.md",
                        "content": "正文不能进入调用摘要",
                    }
                ],
            }
        )


class RecordingCatalog:
    def search(self, **_: object) -> dict[str, object]:
        return {
            "task_id": 77,
            "database": "analytics",
            "objects": [{"name": "orders"}],
            "returned_count": 1,
            "result_bytes": 64,
            "truncated": False,
        }


class RecordingQuery:
    def execute(self, **_: object) -> dict[str, object]:
        return {
            "task_id": 77,
            "database": "analytics",
            "rows": [["secret-result"]],
            "returned_rows": 1,
            "result_bytes": 48,
            "truncated": False,
        }


class FailingQuery:
    def execute(self, **_: object) -> dict[str, object]:
        raise DatabaseAccessError("connection_failed", "数据库当前无法连接")


class UnusedStore:
    def get_task(self, task_id: int) -> TaskRecord:
        raise AssertionError(task_id)

    def list_read_calls(self, task_id: int) -> list[DocumentReadCallRecord]:
        raise AssertionError(task_id)

    def list_calls(self, task_id: int) -> list[DatabaseCallRecord]:
        raise AssertionError(task_id)


def _tracking_service(
    repository: InMemoryMcpToolCallRepository,
) -> McpTraceService:
    unused = UnusedStore()
    return McpTraceService(
        tool_call_repository=repository,
        task_repository=unused,
        document_read_repository=unused,
        database_call_repository=unused,
        registry=object(),  # type: ignore[arg-type]
    )


def test_all_four_mcp_tools_are_traced_in_server_order_without_sensitive_payloads() -> None:
    repository = InMemoryMcpToolCallRepository()
    server = create_context_router_mcp(
        RecordingPreparation(),  # type: ignore[arg-type]
        RecordingRead(),  # type: ignore[arg-type]
        RecordingCatalog(),  # type: ignore[arg-type]
        RecordingQuery(),  # type: ignore[arg-type]
        _tracking_service(repository),
    )

    async def invoke_tools() -> None:
        await server.call_tool(
            "prepare_task_context",
            {"task": "排查问题", "cwd": "/workspace/project", "agent_name": "codex"},
        )
        await server.call_tool(
            "read_context_document",
            {"task_id": 77, "requests": [{"document_id": "root"}]},
        )
        await server.call_tool(
            "search_database_objects",
            {"task_id": 77, "database": "analytics", "object_type": "table"},
        )
        await server.call_tool(
            "execute_database_query",
            {
                "task_id": 77,
                "database": "analytics",
                "sql": "SELECT password FROM users",
            },
        )

    asyncio.run(invoke_tools())
    calls = repository.list_calls(77)

    assert [call.tool_name for call in calls] == [
        "prepare_task_context",
        "read_context_document",
        "search_database_objects",
        "execute_database_query",
    ]
    assert [call.status for call in calls] == ["ok", "ok", "ok", "ok"]
    assert calls[0].result_summary == {
        "document_count": 3,
        "database_count": 0,
        "warning_count": 0,
    }
    assert calls[1].result_summary == {
        "document_count": 1,
        "ok_count": 1,
        "error_count": 0,
        "content_characters": 10,
    }
    serialized = repr([(call.request_summary, call.result_summary) for call in calls])
    assert "SELECT password" not in serialized
    assert "secret-result" not in serialized
    assert "正文不能进入调用摘要" not in serialized
    assert calls[3].request_summary == {
        "database": "analytics",
        "sql_sha256": "70295e581aff4b4ae56d4cfae234338844965793adc6f178c5e5f44abf05c838",
    }


def test_failed_mcp_tool_finishes_error_without_hiding_original_tool_error() -> None:
    repository = InMemoryMcpToolCallRepository()
    server = create_context_router_mcp(
        RecordingPreparation(),  # type: ignore[arg-type]
        RecordingRead(),  # type: ignore[arg-type]
        RecordingCatalog(),  # type: ignore[arg-type]
        FailingQuery(),  # type: ignore[arg-type]
        _tracking_service(repository),
    )

    with pytest.raises(ToolError, match="connection_failed"):
        asyncio.run(
            server.call_tool(
                "execute_database_query",
                {"task_id": 77, "database": "analytics", "sql": "SELECT 1"},
            )
        )

    call = repository.list_calls(77)[0]
    assert call.status == "error"
    assert call.error_code == "connection_failed"


class TraceRepository(InMemoryMcpToolCallRepository):
    def __init__(self, task: TaskRecord) -> None:
        super().__init__()
        self.task = task

    def list_traces(self, **_: object) -> list[McpTraceTaskRecord]:
        calls = self.list_calls(self.task.id)
        return [
            McpTraceTaskRecord(
                task_id=self.task.id,
                project_key=self.task.project_key,
                project_name=self.task.project_name,
                task=self.task.task,
                cwd=self.task.cwd,
                agent_name=self.task.agent_name,
                created_at=self.task.created_at,
                call_count=len(calls),
                error_count=sum(1 for call in calls if call.status == "error"),
                server_names=sorted({call.server_name for call in calls}),
                last_activity_at=max(
                    (call.finished_at or call.started_at for call in calls),
                    default=self.task.created_at,
                ),
            )
        ]


class TraceTaskStore:
    def __init__(self, task: TaskRecord) -> None:
        self.task = task

    def get_task(self, task_id: int) -> TaskRecord:
        assert task_id == self.task.id
        return self.task


class TraceReadStore:
    def __init__(self, tool_call_id: int, created_at: datetime) -> None:
        self.tool_call_id = tool_call_id
        self.created_at = created_at

    def list_read_calls(self, task_id: int) -> list[DocumentReadCallRecord]:
        return [
            DocumentReadCallRecord(
                id=9,
                task_id=task_id,
                created_at=self.created_at,
                tool_call_id=self.tool_call_id,
                items=[
                    DocumentReadItemRecord(
                        id=10,
                        position=1,
                        document_id="root",
                        document_path="AGENTS.md",
                        requested_section=None,
                        status="ok",
                    )
                ],
            )
        ]


class EmptyDatabaseCallStore:
    def list_calls(self, task_id: int) -> list[DatabaseCallRecord]:
        return []


def test_trace_list_and_detail_api_return_stable_sequence_and_read_artifact(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project" / "AGENTS.md"
    root.parent.mkdir(parents=True)
    root.write_text("# 入口", encoding="utf-8")
    registry = ProjectRegistry(
        Settings(
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
            default_project_name=None,
            default_agents_path=None,
        )
    )
    project = registry.add_project(name="测试项目", agents_path=str(root))
    project_key = registry.get_project_key(project.id)
    created_at = datetime.now(UTC)
    task = TaskRecord(
        id=77,
        project_key=project_key,
        project_name="测试项目",
        task="排查登录问题",
        cwd=str(root.parent),
        agent_name="codex",
        created_at=created_at,
    )
    tool_calls = TraceRepository(task)
    prepare_call_id = tool_calls.create_call(
        McpToolCallWrite(
            task_id=77,
            server_name="context-router",
            tool_name="prepare_task_context",
            source="server",
            status="ok",
            started_at=created_at,
            finished_at=created_at,
            duration_ms=2,
        )
    )
    read_call_id = tool_calls.create_call(
        McpToolCallWrite(
            task_id=77,
            server_name="context-router",
            tool_name="read_context_document",
            source="server",
            status="ok",
            started_at=created_at,
            finished_at=created_at,
            duration_ms=3,
        )
    )
    service = McpTraceService(
        tool_call_repository=tool_calls,
        task_repository=TraceTaskStore(task),
        document_read_repository=TraceReadStore(read_call_id, created_at),
        database_call_repository=EmptyDatabaseCallStore(),
        registry=registry,
    )
    app = FastAPI()
    app.state.mcp_trace_service = service
    app.include_router(mcp_traces_router, prefix="/api")

    with TestClient(app) as client:
        trace_list = client.get("/api/mcp-traces")
        detail = client.get("/api/mcp-traces/77")

    assert trace_list.status_code == 200
    assert trace_list.json()[0]["project_id"] == project.id
    assert trace_list.json()[0]["call_count"] == 2
    assert detail.status_code == 200
    calls = detail.json()["calls"]
    assert [(call["tool_call_id"], call["sequence"]) for call in calls] == [
        (prepare_call_id, 1),
        (read_call_id, 2),
    ]
    assert calls[1]["artifacts"] == [
        {
            "kind": "document_read",
            "read_call_id": 9,
            "documents": [
                {
                    "position": 1,
                    "document_id": "root",
                    "path": "AGENTS.md",
                    "status": "ok",
                }
            ],
        }
    ]
