import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

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
    McpToolCallRepositoryError,
    McpToolCallWrite,
    McpTraceTaskRecord,
)
from context_router.repositories.task_repository import TaskRecord
from context_router.services.context_preparation import ContextPreparationError
from context_router.services.mcp_trace import McpTraceService, _trace_completeness
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
                "documents": {
                    "document_id": "root",
                    "summary": "入口",
                    "children": [
                        {"document_id": "one", "summary": "一", "children": []},
                        {"document_id": "two", "summary": "二", "children": []},
                    ],
                },
            }
        )

    def read_task_context(self, **_: object) -> DumpResult:
        return DumpResult(
            {
                "task_id": 77,
                "databases": [{"database": "analytics"}],
                "environment": {
                    "configured": True,
                    "config": {"password": "must-not-enter-trace"},
                },
            }
        )


class FailingPreparation:
    def prepare(self, **_: object) -> DumpResult:
        raise ContextPreparationError(
            "任务上下文准备失败",
            task_id=77,
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


class RecordingSearch:
    def search(self, **_: object) -> DumpResult:
        return DumpResult(
            {
                "task_id": 77,
                "query": "登录",
                "returned_count": 1,
                "truncated": False,
                "results": [
                    {
                        "document_id": "root",
                        "path": "AGENTS.md",
                        "title": "登录说明",
                        "summary": "结果正文不能进入调用摘要",
                        "relevance": 0.75,
                        "matched_sections": [],
                        "match_reasons": ["title_exact"],
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


class RecordingDatabaseContext:
    def alias_for_context(self, **_: object) -> str:
        return "analytics"


class RecordingMiddleware:
    def read(self, **_: object) -> DumpResult:
        return DumpResult(
            {
                "task_id": 77,
                "profile_key": "test",
                "environment": "test",
                "provider": "nacos",
                "fetched_at": "2026-08-11T10:00:00Z",
                "secrets_revealed": True,
                "components": [
                    {
                        "id": "redis-main",
                        "type": "redis",
                        "properties": {
                            "host": "redis.test.local",
                            "password": "middleware-secret-must-not-enter-trace",
                        },
                        "sources": [
                            {
                                "data_id": "c12-common.yaml",
                                "group": "DEFAULT_GROUP",
                                "md5": "abc123",
                            }
                        ],
                    }
                ],
                "warnings": [],
            }
        )


class RecordingValueMappings:
    def search_for_task(self, **_: object) -> dict[str, object]:
        return {
            "task_id": 77,
            "environment": "local",
            "mappings": [{"mapping_id": "mapping-1"}],
            "returned_count": 1,
            "truncated": False,
        }

    def resolve_for_task(self, mapping_id: str, **arguments: object) -> dict[str, object]:
        return {
            "task_id": 77,
            "mapping_id": mapping_id,
            "environment": "local",
            "candidates": [{"value": "secret-id", "label": "secret-label"}],
            "returned_count": 1,
            "candidate_pool_count": 10,
            "selection": arguments.get("selection", "default"),
            "truncated": False,
        }

    def source_for_task(self, mapping_id: str, **_: object) -> dict[str, object]:
        return {
            "mapping_id": mapping_id,
            "database_alias": "analytics",
            "schema_name": "public",
            "table_name": "route_product",
            "value_column": "id",
        }


class _VisualizationRecord:
    def __init__(self, *, execution_status: str = "pending") -> None:
        self.id = "record-1"
        self.workspace_id = "workspace-1"
        self.environment = "local"
        self.execution_status = execution_status

    def model_dump(self, **_: object) -> dict[str, object]:
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "environment": self.environment,
            "execution_status": self.execution_status,
            "task_id": 77,
            "result_row_count": 1 if self.execution_status == "succeeded" else None,
        }


class _LatestVisualization:
    def __init__(self, record: _VisualizationRecord) -> None:
        self.record = record


class RecordingDataVisualization:
    def __init__(self) -> None:
        self.create_arguments: dict[str, object] = {}
        self.execution_arguments: dict[str, object] = {}
        self.record = _VisualizationRecord()

    def create_for_task(self, **arguments: object) -> _VisualizationRecord:
        self.create_arguments = arguments
        return self.record

    def record_execution(self, **arguments: object) -> None:
        self.execution_arguments = arguments
        self.record = _VisualizationRecord(execution_status="succeeded")

    def latest(self, **_: object) -> _LatestVisualization:
        return _LatestVisualization(self.record)


class RecordingTaskVisualization:
    def __init__(self) -> None:
        self.payload: object | None = None

    def save_result(self, _task_id: int, payload: object) -> DumpResult:
        self.payload = payload
        return DumpResult(
            {
                "task_id": 77,
                "status": "resolved",
                "revision": 1,
                "verification": [
                    item.model_dump(exclude_none=True)
                    for item in getattr(payload, "verification", [])
                ],
            }
        )


class FailingQuery:
    def execute(self, **_: object) -> dict[str, object]:
        raise DatabaseAccessError("connection_failed", "数据库当前无法连接")


class RecordingWorkspaceRuntime:
    def apply_changes(self, **_: object) -> DumpResult:
        return self._result("operation-1", "apply_changes")

    def start_workspace(self, **_: object) -> DumpResult:
        return self._result("operation-2", "start_workspace")

    def get_operation(self, operation_id: str, _log_characters: int) -> DumpResult:
        return self._result(operation_id, "apply_changes")

    def get_task_id(self, operation_id: str) -> int:
        assert operation_id
        return 77

    @staticmethod
    def _result(operation_id: str, kind: str) -> DumpResult:
        return DumpResult(
            {
                "id": operation_id,
                "task_id": 77,
                "workspace_id": "workspace-1",
                "kind": kind,
                "status": "queued",
                "steps": [{"owner_id": "project-1", "mode": "fast"}],
            }
        )


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


class VerifiableTraceService(McpTraceService):
    def __init__(self, repository: InMemoryMcpToolCallRepository) -> None:
        self.repository = repository
        unused = UnusedStore()
        super().__init__(
            tool_call_repository=repository,
            task_repository=unused,
            document_read_repository=unused,
            database_call_repository=unused,
            registry=object(),  # type: ignore[arg-type]
        )

    def get_trace(self, task_id: int) -> SimpleNamespace:
        return SimpleNamespace(
            calls=[
                SimpleNamespace(
                    tool_call_id=call.id,
                    status=call.status,
                    tool_name=call.tool_name,
                    result_summary=call.result_summary,
                    duration_ms=call.duration_ms,
                )
                for call in self.repository.list_calls(task_id)
            ]
        )


def test_all_seven_context_and_database_tools_are_traced_without_sensitive_payloads() -> None:
    repository = InMemoryMcpToolCallRepository()
    server = create_context_router_mcp(
        RecordingPreparation(),  # type: ignore[arg-type]
        RecordingRead(),  # type: ignore[arg-type]
        RecordingCatalog(),  # type: ignore[arg-type]
        RecordingQuery(),  # type: ignore[arg-type]
        _tracking_service(repository),
        document_search_service=RecordingSearch(),
        middleware_context_service=RecordingMiddleware(),  # type: ignore[arg-type]
        database_context_service=RecordingDatabaseContext(),  # type: ignore[arg-type]
    )

    async def invoke_tools() -> None:
        await server.call_tool(
            "prepare_task_context",
            {"task": "排查问题", "cwd": "/workspace/project", "agent_name": "codex"},
        )
        await server.call_tool(
            "read_task_context",
            {"task_id": 77, "sections": ["databases", "environment"]},
        )
        await server.call_tool(
            "read_middleware_context",
            {
                "task_id": 77,
                "components": ["redis-main"],
            },
        )
        await server.call_tool(
            "search_context_documents",
            {"task_id": 77, "query": "登录", "limit": 10},
        )
        await server.call_tool(
            "read_context_document",
            {"task_id": 77, "requests": [{"document_id": "root"}]},
        )
        await server.call_tool(
            "search_database_objects",
            {"task_id": 77, "database_context_id": "1" * 36, "object_type": "table"},
        )
        await server.call_tool(
            "execute_database_query",
            {
                "task_id": 77,
                "database_context_id": "1" * 36,
                "sql": "SELECT password FROM users",
            },
        )

    asyncio.run(invoke_tools())
    calls = repository.list_calls(77)

    assert [call.tool_name for call in calls] == [
        "prepare_task_context",
        "read_task_context",
        "read_middleware_context",
        "search_context_documents",
        "read_context_document",
        "search_database_objects",
        "execute_database_query",
    ]
    assert [call.status for call in calls] == ["ok", "ok", "ok", "ok", "ok", "ok", "ok"]
    assert calls[0].result_summary == {
        "document_count": 3,
        "warning_count": 0,
    }
    assert calls[1].request_summary == {"sections": ["databases", "environment"]}
    assert calls[1].result_summary == {
        "database_count": 1,
        "environment_requested": True,
        "environment_configured": True,
    }
    assert calls[2].request_summary == {
        "environment": None,
        "component_count": 1,
        "all_components": False,
        "reveal_secrets": True,
    }
    assert calls[2].result_summary == {
        "component_count": 1,
        "source_count": 1,
        "warning_count": 0,
        "secrets_revealed": True,
    }
    assert calls[3].result_summary == {
        "returned_count": 1,
        "truncated": False,
        "max_relevance": 0.75,
    }
    assert calls[4].result_summary == {
        "document_count": 1,
        "ok_count": 1,
        "error_count": 0,
        "content_characters": 10,
    }
    serialized = repr([(call.request_summary, call.result_summary) for call in calls])
    assert "SELECT password" not in serialized
    assert "secret-result" not in serialized
    assert "正文不能进入调用摘要" not in serialized
    assert "结果正文不能进入调用摘要" not in serialized
    assert "must-not-enter-trace" not in serialized
    assert "middleware-secret-must-not-enter-trace" not in serialized
    assert "登录" not in serialized
    assert calls[6].request_summary == {
        "database_context_id": "1" * 36,
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
        database_context_service=RecordingDatabaseContext(),  # type: ignore[arg-type]
    )

    with pytest.raises(ToolError, match="connection_failed"):
        asyncio.run(
            server.call_tool(
                "execute_database_query",
                {"task_id": 77, "database_context_id": "1" * 36, "sql": "SELECT 1"},
            )
        )

    call = repository.list_calls(77)[0]
    assert call.status == "error"
    assert call.error_code == "connection_failed"
    assert call.result_summary == {"reason": "connection_failed"}


def test_invalid_tool_arguments_are_explained_in_trace_without_guessing() -> None:
    repository = InMemoryMcpToolCallRepository()
    server = create_context_router_mcp(
        RecordingPreparation(),  # type: ignore[arg-type]
        RecordingRead(),  # type: ignore[arg-type]
        trace_service=_tracking_service(repository),
    )

    with pytest.raises(ToolError, match="status=investigating,resolved,failed"):
        asyncio.run(
            server.call_tool(
                "save_task_visualization_result",
                {"task_id": 77, "status": "success", "summary": "完成"},
            )
        )

    call = repository.list_calls(77)[0]
    assert call.status == "error"
    assert call.error_code == "invalid_tool_arguments"
    assert call.result_summary == {
        "reason": "invalid_tool_arguments",
        "message": "字段值不合法：status；允许值：status=investigating,resolved,failed",
        "missing_fields": [],
        "invalid_fields": ["status"],
        "allowed_values": {"status": ["investigating", "resolved", "failed"]},
    }


@pytest.mark.parametrize(
    ("arguments", "missing_fields"),
    [
        ({"task_id": 77, "sql": "SELECT 1"}, ["database_context_id"]),
        ({"task_id": 77, "database_context_id": "1" * 36}, ["sql"]),
        ({"task_id": 77}, ["database_context_id", "sql"]),
    ],
)
def test_execute_database_query_reports_missing_required_arguments(
    arguments: dict[str, object],
    missing_fields: list[str],
) -> None:
    repository = InMemoryMcpToolCallRepository()
    server = create_context_router_mcp(
        RecordingPreparation(),  # type: ignore[arg-type]
        RecordingRead(),  # type: ignore[arg-type]
        trace_service=_tracking_service(repository),
    )

    with pytest.raises(ToolError, match="缺少必填字段"):
        asyncio.run(server.call_tool("execute_database_query", arguments))

    call = repository.list_calls(77)[0]
    assert call.status == "error"
    assert call.error_code == "invalid_tool_arguments"
    assert call.result_summary == {
        "reason": "invalid_tool_arguments",
        "message": "缺少必填字段：" + "、".join(missing_fields),
        "missing_fields": missing_fields,
        "invalid_fields": [],
        "allowed_values": {},
    }


def test_value_mapping_tools_trace_only_hashed_keywords_and_bounded_metadata() -> None:
    repository = InMemoryMcpToolCallRepository()
    server = create_context_router_mcp(
        RecordingPreparation(),  # type: ignore[arg-type]
        RecordingRead(),  # type: ignore[arg-type]
        trace_service=_tracking_service(repository),
        value_mapping_service=RecordingValueMappings(),  # type: ignore[arg-type]
    )

    async def invoke_tools() -> None:
        await server.call_tool(
            "search_value_mappings",
            {"task_id": 77, "query": "货主ID", "limit": 5},
        )
        await server.call_tool(
            "resolve_value_candidates",
            {
                "task_id": 77,
                "mapping_id": "mapping-1",
                "keyword": "攀枝花公司",
                "limit": 3,
                "selection": "random",
            },
        )

    asyncio.run(invoke_tools())
    calls = repository.list_calls(77)

    assert [call.tool_name for call in calls] == [
        "search_value_mappings",
        "resolve_value_candidates",
    ]
    serialized = repr([(call.request_summary, call.result_summary) for call in calls])
    assert "货主ID" not in serialized
    assert "攀枝花公司" not in serialized
    assert "secret-id" not in serialized
    assert "secret-label" not in serialized
    assert calls[0].request_summary == {
        "query_sha256": "35ebb1becfdd94b5eb5773f09ac0fa0072c9e098790c20f072cc59cff41b4b5a",
        "interface_id": None,
        "location": None,
        "parameter_path": None,
        "limit": 5,
    }
    assert calls[0].result_summary == {
        "returned_count": 1,
        "environment": "local",
        "truncated": False,
    }
    assert calls[1].result_summary == {
        "mapping_id": "mapping-1",
        "returned_count": 1,
        "environment": "local",
        "selection": "random",
        "candidate_pool_count": 10,
        "truncated": False,
    }
    assert calls[1].request_summary == {
        "mapping_id": "mapping-1",
        "environment": None,
        "keyword_sha256": "13113fa47460d96027f65b27df151977c6de423da93727785707b3356ce7a506",
        "limit": 3,
        "selection": "random",
    }


def test_mapping_short_path_marks_visualization_succeeded_and_verifies_real_call() -> None:
    repository = InMemoryMcpToolCallRepository()
    trace_service = VerifiableTraceService(repository)
    data_visualization = RecordingDataVisualization()
    task_visualization = RecordingTaskVisualization()
    server = create_context_router_mcp(
        RecordingPreparation(),  # type: ignore[arg-type]
        RecordingRead(),  # type: ignore[arg-type]
        trace_service=trace_service,
        value_mapping_service=RecordingValueMappings(),  # type: ignore[arg-type]
        ai_data_visualization_service=data_visualization,  # type: ignore[arg-type]
        ai_task_visualization_service=task_visualization,  # type: ignore[arg-type]
    )

    async def invoke_tools() -> None:
        _, resolution = await server.call_tool(
            "resolve_value_candidates",
            {
                "task_id": 77,
                "mapping_id": "mapping-1",
                "limit": 1,
                "selection": "random",
            },
        )
        resolution_call_id = resolution["tool_call_id"]
        assert resolution_call_id == repository.list_calls(77)[0].id
        assert resolution["next_action"] == {
            "tool": "save_data_visualization_query",
            "arguments": {
                "task_id": 77,
                "description": "业务数据查询",
                "keyword": "secret-id",
                "mapping_id": "mapping-1",
                "execution_tool_call_id": resolution_call_id,
            },
            "ready": True,
        }
        _, saved_query = await server.call_tool(
            "save_data_visualization_query",
            resolution["next_action"]["arguments"],
        )
        assert saved_query["tool_call_id"] == repository.list_calls(77)[1].id
        _, task_result = await server.call_tool(
            "save_task_visualization_result",
            {
                "task_id": 77,
                "status": "resolved",
                "summary": "已随机查询线路产品",
                "verification_call_ids": [resolution_call_id],
            },
        )
        assert task_result["tool_call_id"] == repository.list_calls(77)[2].id

    asyncio.run(invoke_tools())

    assert data_visualization.create_arguments["database_key"] == "analytics"
    assert data_visualization.create_arguments["table_name"] == "route_product"
    assert data_visualization.execution_arguments["result_row_count"] == 1
    assert task_visualization.payload is not None
    verification = task_visualization.payload.verification  # type: ignore[union-attr]
    assert verification[0].tool_call_id == repository.list_calls(77)[0].id
    calls = repository.list_calls(77)
    assert [call.status for call in calls] == ["ok", "ok", "ok"]
    assert calls[1].result_summary == {
        "execution_status": "succeeded",
        "result_row_count": 1,
        "task_linked": True,
    }


def test_workspace_runtime_tools_are_traced_and_operation_query_resolves_task() -> None:
    repository = InMemoryMcpToolCallRepository()
    runtime = RecordingWorkspaceRuntime()
    server = create_context_router_mcp(
        RecordingPreparation(),  # type: ignore[arg-type]
        RecordingRead(),  # type: ignore[arg-type]
        trace_service=_tracking_service(repository),
        workspace_runtime_service=runtime,  # type: ignore[arg-type]
    )

    async def invoke_tools() -> None:
        await server.call_tool(
            "apply_workspace_changes",
            {"task_id": 77, "changed_files": ["project/app.py"]},
        )
        await server.call_tool("start_workspace", {"task_id": 77})
        await server.call_tool(
            "get_workspace_operation",
            {"operation_id": "operation-1", "log_characters": 2000},
        )

    asyncio.run(invoke_tools())
    calls = repository.list_calls(77)

    assert [call.tool_name for call in calls] == [
        "apply_workspace_changes",
        "start_workspace",
        "get_workspace_operation",
    ]
    assert calls[0].request_summary == {"changed_file_count": 1}
    assert calls[2].result_summary == {
        "operation_id": "operation-1",
        "status": "queued",
        "step_count": 1,
    }


def test_prepare_failure_after_task_creation_records_error_call() -> None:
    repository = InMemoryMcpToolCallRepository()
    server = create_context_router_mcp(
        FailingPreparation(),  # type: ignore[arg-type]
        RecordingRead(),  # type: ignore[arg-type]
        trace_service=_tracking_service(repository),
    )

    with pytest.raises(ToolError, match="任务上下文准备失败"):
        asyncio.run(
            server.call_tool(
                "prepare_task_context",
                {"task": "排查问题", "cwd": "/workspace/project", "agent_name": "codex"},
            )
        )

    calls = repository.list_calls(77)
    assert len(calls) == 1
    assert calls[0].tool_name == "prepare_task_context"
    assert calls[0].status == "error"
    assert calls[0].error_code == "context_preparation_failed"


def test_internal_trace_repository_rejects_gateway_and_unknown_tools() -> None:
    repository = InMemoryMcpToolCallRepository()

    with pytest.raises(McpToolCallRepositoryError, match="Context Router"):
        repository.create_call(
            McpToolCallWrite(
                task_id=77,
                server_name="another-server",
                tool_name="read_context_document",
                source="server",
            )
        )
    with pytest.raises(McpToolCallRepositoryError, match="白名单"):
        repository.create_call(
            McpToolCallWrite(
                task_id=77,
                server_name="context-router",
                tool_name="external_search",
                source="server",
            )
        )
    with pytest.raises(McpToolCallRepositoryError, match="内部或历史"):
        repository.create_call(
            McpToolCallWrite(
                task_id=77,
                server_name="context-router",
                tool_name="read_context_document",
                source="gateway",
            )
        )


def test_reconcile_interrupted_calls_marks_only_running_call_as_restarted() -> None:
    repository = InMemoryMcpToolCallRepository()
    running_id = repository.create_call(
        McpToolCallWrite(
            task_id=77,
            server_name="context-router",
            tool_name="read_context_document",
            source="server",
            status="running",
        )
    )
    completed_id = repository.create_call(
        McpToolCallWrite(
            task_id=77,
            server_name="context-router",
            tool_name="prepare_task_context",
            source="server",
            status="ok",
            finished_at=datetime.now(UTC),
            duration_ms=1,
        )
    )

    assert _tracking_service(repository).reconcile_interrupted_calls() == 1

    calls = {call.id: call for call in repository.list_calls(77)}
    assert calls[running_id].status == "error"
    assert calls[running_id].error_code == "server_restarted"
    assert calls[running_id].finished_at is not None
    assert calls[completed_id].status == "ok"
    assert calls[completed_id].error_code is None


@pytest.mark.parametrize(
    (
        "counts",
        "expected_status",
        "expected_warnings",
    ),
    [
        (
            {
                "call_count": 1,
                "prepare_call_count": 1,
                "running_call_count": 0,
                "legacy_call_count": 0,
                "interrupted_call_count": 0,
                "unlinked_document_read_count": 0,
                "unlinked_database_call_count": 0,
            },
            "complete",
            [],
        ),
        (
            {
                "call_count": 1,
                "prepare_call_count": 1,
                "running_call_count": 1,
                "legacy_call_count": 0,
                "interrupted_call_count": 0,
                "unlinked_document_read_count": 0,
                "unlinked_database_call_count": 0,
            },
            "running",
            ["running_calls"],
        ),
        (
            {
                "call_count": 1,
                "prepare_call_count": 1,
                "running_call_count": 0,
                "legacy_call_count": 1,
                "interrupted_call_count": 1,
                "unlinked_document_read_count": 1,
                "unlinked_database_call_count": 1,
            },
            "partial",
            [
                "legacy_calls",
                "interrupted_calls",
                "unlinked_document_reads",
                "unlinked_database_calls",
            ],
        ),
        (
            {
                "call_count": 0,
                "prepare_call_count": 0,
                "running_call_count": 0,
                "legacy_call_count": 0,
                "interrupted_call_count": 0,
                "unlinked_document_read_count": 0,
                "unlinked_database_call_count": 0,
            },
            "partial",
            ["no_trace_calls", "missing_prepare_call"],
        ),
        (
            {
                "call_count": 1,
                "prepare_call_count": 0,
                "running_call_count": 0,
                "legacy_call_count": 0,
                "interrupted_call_count": 0,
                "unlinked_document_read_count": 0,
                "unlinked_database_call_count": 0,
            },
            "partial",
            ["missing_prepare_call"],
        ),
    ],
)
def test_trace_completeness_status_matrix(
    counts: dict[str, int],
    expected_status: str,
    expected_warnings: list[str],
) -> None:
    assert _trace_completeness(**counts) == (expected_status, expected_warnings)  # type: ignore[arg-type]


class TraceRepository(InMemoryMcpToolCallRepository):
    def __init__(self, task: TaskRecord) -> None:
        super().__init__()
        self.task = task

    def list_traces(self, **_: object) -> list[McpTraceTaskRecord]:
        calls = self.list_calls(self.task.id)
        return [
            McpTraceTaskRecord(
                task_id=self.task.id,
                project_id=self.task.project_id,
                project_key=self.task.project_key,
                project_name=self.task.project_name,
                task=self.task.task,
                cwd=self.task.cwd,
                agent_name=self.task.agent_name,
                created_at=self.task.created_at,
                call_count=len(calls),
                prepare_call_count=sum(
                    1 for call in calls if call.tool_name == "prepare_task_context"
                ),
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
        project_id=project.id,
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


def test_trace_list_and_detail_are_partial_when_prepare_call_is_missing(
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
    created_at = datetime.now(UTC)
    task = TaskRecord(
        id=78,
        project_id=project.id,
        project_key=registry.get_project_key(project.id),
        project_name="测试项目",
        task="prepare 记录缺失",
        cwd=str(root.parent),
        agent_name="codex",
        created_at=created_at,
    )
    tool_calls = TraceRepository(task)
    read_call_id = tool_calls.create_call(
        McpToolCallWrite(
            task_id=task.id,
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

    summary = service.list_traces()[0]
    detail = service.get_trace(task.id)

    assert summary.trace_status == "partial"
    assert summary.warnings == ["missing_prepare_call"]
    assert detail.trace_status == "partial"
    assert detail.warnings == ["missing_prepare_call"]
