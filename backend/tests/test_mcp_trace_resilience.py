from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Literal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from context_router.api.mcp_traces import router as mcp_traces_router
from context_router.config import Settings
from context_router.main import create_app
from context_router.mcp_server import ContextRouterMCP, create_context_router_mcp
from context_router.repositories.database_call_repository import DatabaseCallRecord
from context_router.repositories.document_read_repository import (
    DocumentReadCallRecord,
    DocumentReadItemRecord,
)
from context_router.repositories.mcp_tool_call_repository import (
    InMemoryMcpToolCallRepository,
    McpToolCallRepositoryError,
    McpToolCallStatus,
    McpToolCallWrite,
)
from context_router.repositories.project_repository import InMemoryProjectRepository
from context_router.repositories.task_repository import TaskRecord
from context_router.services.context_document_read import ContextDocumentReadError
from context_router.services.mcp_trace import McpTraceService, current_tool_call_id


class DumpResult:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def model_dump(self, **_: object) -> dict[str, object]:
        return self.payload


class StaticPreparation:
    def prepare(self, **_: object) -> DumpResult:
        return DumpResult(
            {
                "task_id": 77,
                "project": {
                    "project_id": "project-77",
                    "name": "测试项目",
                    "node_count": 1,
                },
                "documents": {
                    "document_id": "root",
                    "path": "AGENTS.md",
                    "children": [],
                },
                "databases": [],
            }
        )


class StaticRead:
    def read(self, *, task_id: int, **_: object) -> DumpResult:
        return DumpResult(
            {
                "task_id": task_id,
                "read_call_id": 9,
                "documents": [
                    {
                        "position": 1,
                        "document_id": "root",
                        "path": "AGENTS.md",
                        "content": "业务结果保持可用",
                    }
                ],
            }
        )


class EmptyDocumentReadStore:
    def list_read_calls(self, task_id: int) -> list[DocumentReadCallRecord]:
        return []


class EmptyDatabaseCallStore:
    def list_calls(self, task_id: int) -> list[DatabaseCallRecord]:
        return []


class StaticDatabaseContext:
    def alias_for_context(self, **_: object) -> str:
        return "private_db"


class UnusedTaskStore:
    def get_task(self, task_id: int) -> TaskRecord:
        raise AssertionError(f"unexpected task lookup: {task_id}")


class FailingTraceRepository(InMemoryMcpToolCallRepository):
    def __init__(self, failure: Literal["start", "finish", "prepare"]) -> None:
        super().__init__()
        self.failure = failure

    def create_call(self, call: McpToolCallWrite) -> int:
        if self.failure == "start" and call.status == "running":
            raise McpToolCallRepositoryError("start unavailable")
        if self.failure == "prepare" and call.tool_name == "prepare_task_context":
            raise McpToolCallRepositoryError("prepare trace unavailable")
        return super().create_call(call)

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
        if self.failure == "finish":
            raise McpToolCallRepositoryError("finish unavailable")
        super().complete_call(
            tool_call_id,
            status=status,
            finished_at=finished_at,
            duration_ms=duration_ms,
            result_summary=result_summary,
            error_code=error_code,
        )


class UnexpectedFailingTraceRepository(InMemoryMcpToolCallRepository):
    def create_call(self, call: McpToolCallWrite) -> int:
        raise RuntimeError(f"unexpected create failure: {call.tool_name}")

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
        raise RuntimeError(f"unexpected completion failure: {tool_call_id}")

    def fail_running_calls(self, *, finished_at: datetime) -> int:
        raise RuntimeError(f"unexpected recovery failure: {finished_at.isoformat()}")


def _trace_service(
    repository: InMemoryMcpToolCallRepository,
    *,
    task_store: object | None = None,
    document_store: object | None = None,
    database_store: object | None = None,
) -> McpTraceService:
    return McpTraceService(
        tool_call_repository=repository,
        task_repository=task_store or UnusedTaskStore(),  # type: ignore[arg-type]
        document_read_repository=document_store or EmptyDocumentReadStore(),  # type: ignore[arg-type]
        database_call_repository=database_store or EmptyDatabaseCallStore(),  # type: ignore[arg-type]
        registry=object(),  # type: ignore[arg-type]
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
    raise AssertionError(f"tool result did not contain structured content: {result!r}")


@pytest.mark.parametrize(
    ("failure", "tool_name", "arguments"),
    [
        (
            "start",
            "read_context_document",
            {"task_id": 77, "requests": [{"document_id": "root"}]},
        ),
        (
            "finish",
            "read_context_document",
            {"task_id": 77, "requests": [{"document_id": "root"}]},
        ),
        (
            "prepare",
            "prepare_task_context",
            {"task": "排查问题", "cwd": "/workspace/project", "agent_name": "codex"},
        ),
    ],
)
def test_trace_persistence_failure_does_not_change_business_result(
    failure: Literal["start", "finish", "prepare"],
    tool_name: str,
    arguments: dict[str, object],
) -> None:
    repository = FailingTraceRepository(failure)
    server = create_context_router_mcp(
        StaticPreparation(),  # type: ignore[arg-type]
        StaticRead(),  # type: ignore[arg-type]
        trace_service=_trace_service(repository),
    )

    result = asyncio.run(server.call_tool(tool_name, arguments))

    payload = _result_payload(result)
    assert payload["task_id"] == 77
    if tool_name == "read_context_document":
        assert payload["documents"][0]["content"] == "业务结果保持可用"  # type: ignore[index]


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        (
            "read_context_document",
            {"task_id": 77, "requests": [{"document_id": "root"}]},
        ),
        (
            "prepare_task_context",
            {"task": "排查问题", "cwd": "/workspace/project", "agent_name": "codex"},
        ),
    ],
)
def test_unexpected_trace_exception_does_not_change_business_result(
    tool_name: str,
    arguments: dict[str, object],
) -> None:
    repository = UnexpectedFailingTraceRepository()
    server = create_context_router_mcp(
        StaticPreparation(),  # type: ignore[arg-type]
        StaticRead(),  # type: ignore[arg-type]
        trace_service=_trace_service(repository),
    )

    result = asyncio.run(server.call_tool(tool_name, arguments))

    assert _result_payload(result)["task_id"] == 77


def test_all_best_effort_write_and_recovery_boundaries_catch_unexpected_exception() -> None:
    service = _trace_service(UnexpectedFailingTraceRepository())
    now = datetime.now(UTC)

    assert (
        service.start_call(
            task_id=77,
            server_name="context-router",
            tool_name="read_context_document",
        )
        is None
    )
    assert (
        service.record_completed_call(
            task_id=77,
            server_name="context-router",
            tool_name="prepare_task_context",
            started_at=now,
            finished_at=now,
            duration_ms=0,
        )
        is None
    )
    assert (
        service.record_failed_call(
            task_id=77,
            server_name="context-router",
            tool_name="prepare_task_context",
            started_at=now,
            finished_at=now,
            duration_ms=0,
            error_code="test_error",
        )
        is None
    )
    service.finish_call(
        1,
        status="ok",
        finished_at=now,
        duration_ms=0,
    )
    assert service.reconcile_interrupted_calls() == 0


class ContextProbeRead:
    def __init__(self, *, fail: bool) -> None:
        self.fail = fail
        self.observed_call_ids: list[int | None] = []

    def read(self, *, task_id: int, **_: object) -> DumpResult:
        self.observed_call_ids.append(current_tool_call_id())
        if self.fail:
            raise ContextDocumentReadError("expected_read_failure")
        return DumpResult(
            {
                "task_id": task_id,
                "read_call_id": 10,
                "documents": [
                    {
                        "position": 1,
                        "document_id": "root",
                        "path": "AGENTS.md",
                        "content": "正文",
                    }
                ],
            }
        )


@pytest.mark.parametrize("fail", [False, True])
def test_context_var_is_reset_after_success_or_error_and_direct_service_is_clean(
    fail: bool,
) -> None:
    repository = InMemoryMcpToolCallRepository()
    read_service = ContextProbeRead(fail=fail)
    server = create_context_router_mcp(
        StaticPreparation(),  # type: ignore[arg-type]
        read_service,  # type: ignore[arg-type]
        trace_service=_trace_service(repository),
    )

    async def scenario() -> None:
        if fail:
            with pytest.raises(ToolError, match="expected_read_failure"):
                await server.call_tool(
                    "read_context_document",
                    {"task_id": 77, "requests": [{"document_id": "root"}]},
                )
        else:
            await server.call_tool(
                "read_context_document",
                {"task_id": 77, "requests": [{"document_id": "root"}]},
            )

        assert current_tool_call_id() is None
        read_service.fail = False
        read_service.read(task_id=77)

    asyncio.run(scenario())

    trace_call = repository.list_calls(77)[0]
    assert read_service.observed_call_ids == [trace_call.id, None]
    assert trace_call.status == ("error" if fail else "ok")


def test_context_var_is_reset_after_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryMcpToolCallRepository()
    trace_service = _trace_service(repository)
    server = ContextRouterMCP(name="test", trace_service=trace_service)
    entered = asyncio.Event()
    observed_call_ids: list[int | None] = []

    async def blocked_call(
        _server: FastMCP,
        _name: str,
        _arguments: dict[str, object],
    ) -> dict[str, object]:
        observed_call_ids.append(current_tool_call_id())
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(FastMCP, "call_tool", blocked_call)

    async def scenario() -> None:
        current_task = asyncio.current_task()
        assert current_task is not None

        async def cancel_after_entry() -> None:
            await entered.wait()
            current_task.cancel()

        canceller = asyncio.create_task(cancel_after_entry())
        with pytest.raises(asyncio.CancelledError):
            await server.call_tool("read_context_document", {"task_id": 77})
        await canceller

        assert current_tool_call_id() is None
        observed_call_ids.append(current_tool_call_id())

    asyncio.run(scenario())

    trace_call = repository.list_calls(77)[0]
    assert observed_call_ids == [trace_call.id, None]
    assert trace_call.status == "cancelled"


class TaskMapStore:
    def __init__(self, task_ids: list[int]) -> None:
        now = datetime.now(UTC)
        self.tasks = {
            task_id: TaskRecord(
                id=task_id,
                project_id=f"project-{task_id}",
                project_key=f"project-key-{task_id}",
                project_name=f"项目 {task_id}",
                task=f"任务 {task_id}",
                cwd=f"/workspace/project-{task_id}",
                agent_name="codex",
                created_at=now,
            )
            for task_id in task_ids
        }

    def get_task(self, task_id: int) -> TaskRecord:
        return self.tasks[task_id]


class RecordingDocumentStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._next_id = 1
        self._calls: list[DocumentReadCallRecord] = []

    def record(
        self,
        *,
        task_id: int,
        tool_call_id: int | None,
        document_id: str,
        path: str,
    ) -> int:
        with self._lock:
            read_call_id = self._next_id
            self._next_id += 1
            self._calls.append(
                DocumentReadCallRecord(
                    id=read_call_id,
                    task_id=task_id,
                    created_at=datetime.now(UTC),
                    tool_call_id=tool_call_id,
                    items=[
                        DocumentReadItemRecord(
                            id=read_call_id * 100,
                            position=1,
                            document_id=document_id,
                            document_path=path,
                            requested_section=None,
                            status="ok",
                        )
                    ],
                )
            )
            return read_call_id

    def list_read_calls(self, task_id: int) -> list[DocumentReadCallRecord]:
        with self._lock:
            return [call for call in self._calls if call.task_id == task_id]


def test_concurrent_tasks_keep_calls_and_artifacts_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_ids = [101, 202]
    task_store = TaskMapStore(task_ids)
    document_store = RecordingDocumentStore()
    repository = InMemoryMcpToolCallRepository()
    trace_service = _trace_service(
        repository,
        task_store=task_store,
        document_store=document_store,
    )
    server = ContextRouterMCP(name="test", trace_service=trace_service)
    both_entered = asyncio.Event()
    entered_count = 0

    async def overlapping_call(
        _server: FastMCP,
        _name: str,
        arguments: dict[str, object],
    ) -> dict[str, object]:
        nonlocal entered_count
        task_id = int(arguments["task_id"])
        tool_call_id = current_tool_call_id()
        entered_count += 1
        if entered_count == len(task_ids):
            both_entered.set()
        await both_entered.wait()
        document_id = f"doc-{task_id}"
        path = f"docs/{task_id}.md"
        read_call_id = document_store.record(
            task_id=task_id,
            tool_call_id=tool_call_id,
            document_id=document_id,
            path=path,
        )
        return {
            "task_id": task_id,
            "read_call_id": read_call_id,
            "documents": [
                {
                    "position": 1,
                    "document_id": document_id,
                    "path": path,
                    "content": f"task-{task_id}",
                }
            ],
        }

    monkeypatch.setattr(FastMCP, "call_tool", overlapping_call)

    async def scenario() -> None:
        await asyncio.gather(
            *(
                server.call_tool(
                    "read_context_document",
                    {"task_id": task_id, "requests": [{"document_id": f"doc-{task_id}"}]},
                )
                for task_id in task_ids
            )
        )

    asyncio.run(scenario())

    for task_id in task_ids:
        trace = trace_service.get_trace(task_id)
        assert trace.call_count == 1
        assert trace.calls[0].tool_name == "read_context_document"
        assert trace.calls[0].status == "ok"
        assert len(trace.calls[0].artifacts) == 1
        artifact = trace.calls[0].artifacts[0]
        assert artifact.kind == "document_read"
        assert artifact.documents[0].document_id == f"doc-{task_id}"
        assert artifact.documents[0].path == f"docs/{task_id}.md"
        assert all(call.task_id == task_id for call in repository.list_calls(task_id))


class PreviewTaskStore:
    def create_workspace_task(self, **_: object) -> int:
        return 501

    def get_task(self, task_id: int) -> TaskRecord:
        raise AssertionError(f"unexpected task lookup: {task_id}")

    def list_tasks(self, *_: object, **__: object) -> list[object]:
        return []


def test_prepare_preview_does_not_create_mcp_tool_calls(tmp_path: Path) -> None:
    root = tmp_path / "project" / "AGENTS.md"
    root.parent.mkdir(parents=True)
    root.write_text("# 项目入口", encoding="utf-8")
    tool_calls = InMemoryMcpToolCallRepository()
    app = create_app(
        Settings(
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
            default_project_name=None,
            default_agents_path=None,
        ),
        task_repository=PreviewTaskStore(),  # type: ignore[arg-type]
        project_repository=InMemoryProjectRepository(),
        mcp_tool_call_repository=tool_calls,
    )

    with TestClient(app) as client:
        project = client.post(
            "/api/projects",
            json={"name": "测试项目", "agents_path": str(root)},
        )
        assert project.status_code == 201
        preview = client.post(
            f"/api/workspaces/{project.json()['workspace_id']}/prepare-preview",
        )
        removed_project_preview = client.post(
            f"/api/projects/{project.json()['id']}/prepare-preview",
        )

    assert preview.status_code == 200
    assert preview.json()["task_id"] == 501
    assert removed_project_preview.status_code == 404
    assert tool_calls.list_calls(501) == []


class SensitiveReadAndStore(RecordingDocumentStore):
    markdown_body = "# 私密文档\n\nmarkdown-secret-body"

    def read(self, *, task_id: int, **_: object) -> DumpResult:
        path = "docs/private.md"
        read_call_id = self.record(
            task_id=task_id,
            tool_call_id=current_tool_call_id(),
            document_id="private-doc",
            path=path,
        )
        return DumpResult(
            {
                "task_id": task_id,
                "read_call_id": read_call_id,
                "documents": [
                    {
                        "position": 1,
                        "document_id": "private-doc",
                        "path": path,
                        "content": self.markdown_body,
                    }
                ],
            }
        )


class SensitiveQueryAndStore:
    raw_sql = "SELECT password FROM users WHERE token = 'sql-secret-token'"
    result_secret = "database-result-secret"
    connection_secret = "postgresql://trace_user:connection-secret@db.internal/private"

    def __init__(self) -> None:
        self.calls: list[DatabaseCallRecord] = []

    def execute(self, *, task_id: int, database: str, sql: str) -> dict[str, object]:
        assert sql == self.raw_sql
        self.calls.append(
            DatabaseCallRecord(
                id=1,
                task_id=task_id,
                operation="execute_query",
                database_alias=database,
                engine="postgresql",
                status="ok",
                object_type=None,
                statement_type="select",
                sql_sha256=hashlib.sha256(sql.encode()).hexdigest(),
                duration_ms=2,
                returned_count=1,
                result_bytes=64,
                truncated=False,
                error_code=None,
                created_at=datetime.now(UTC),
                tool_call_id=current_tool_call_id(),
            )
        )
        return {
            "task_id": task_id,
            "database": database,
            "rows": [[self.result_secret]],
            "returned_rows": 1,
            "result_bytes": 64,
            "truncated": False,
            "connection_url": self.connection_secret,
        }

    def list_calls(self, task_id: int) -> list[DatabaseCallRecord]:
        return [call for call in self.calls if call.task_id == task_id]


def test_trace_api_does_not_return_document_sql_results_or_connection_secrets() -> None:
    task_store = TaskMapStore([77])
    document_store = SensitiveReadAndStore()
    database_store = SensitiveQueryAndStore()
    repository = InMemoryMcpToolCallRepository()
    trace_service = _trace_service(
        repository,
        task_store=task_store,
        document_store=document_store,
        database_store=database_store,
    )
    server = create_context_router_mcp(
        StaticPreparation(),  # type: ignore[arg-type]
        document_store,  # type: ignore[arg-type]
        database_query_service=database_store,  # type: ignore[arg-type]
        trace_service=trace_service,
        database_context_service=StaticDatabaseContext(),  # type: ignore[arg-type]
    )

    async def invoke() -> None:
        await server.call_tool(
            "prepare_task_context",
            {"task": "安全检查", "cwd": "/workspace/project", "agent_name": "codex"},
        )
        await server.call_tool(
            "read_context_document",
            {"task_id": 77, "requests": [{"document_id": "private-doc"}]},
        )
        await server.call_tool(
            "execute_database_query",
            {
                "task_id": 77,
                "database_context_id": "00000000-0000-0000-0000-000000000077",
                "sql": database_store.raw_sql,
            },
        )

    asyncio.run(invoke())

    app = FastAPI()
    app.state.mcp_trace_service = trace_service
    app.include_router(mcp_traces_router, prefix="/api")
    with TestClient(app) as client:
        response = client.get("/api/mcp-traces/77")

    assert response.status_code == 200
    assert response.json()["call_count"] == 3
    assert len(response.json()["calls"][1]["artifacts"]) == 1
    assert len(response.json()["calls"][2]["artifacts"]) == 1
    for secret in (
        document_store.markdown_body,
        "markdown-secret-body",
        database_store.raw_sql,
        "sql-secret-token",
        database_store.result_secret,
        database_store.connection_secret,
        "connection-secret",
    ):
        assert secret not in response.text
