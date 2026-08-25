import asyncio
import threading

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from context_router.mcp_server import (
    MCP_SERVER_INSTRUCTIONS,
    PREPARE_TOOL_DESCRIPTION,
    READ_MIDDLEWARE_CONTEXT_TOOL_DESCRIPTION,
    READ_TASK_CONTEXT_TOOL_DESCRIPTION,
    create_context_router_mcp,
)
from context_router.schemas.context import SearchContextDocumentsResult


class UnusedService:
    def prepare(self, **_: object) -> None:
        raise AssertionError("tools/list must not call prepare")

    def read(self, **_: object) -> None:
        raise AssertionError("tools/list must not call read")


class _PrepareResult:
    def model_dump(self, **_: object) -> dict[str, object]:
        return {"task_id": 55}


class RecordingPreparationService:
    def __init__(self) -> None:
        self.arguments: dict[str, object] = {}

    def prepare(self, **arguments: object) -> _PrepareResult:
        self.arguments = arguments
        return _PrepareResult()

    def read_task_context(self, **arguments: object) -> _PrepareResult:
        self.arguments = arguments
        return _PrepareResult()


class RecordingCatalogService:
    def __init__(self) -> None:
        self.arguments: dict[str, object] = {}

    def search(self, **arguments: object) -> dict[str, object]:
        self.arguments = arguments
        return {"objects": [], "returned_count": 0}


class RecordingDocumentSearchService:
    def __init__(self) -> None:
        self.arguments: dict[str, object] = {}

    def search(self, **arguments: object) -> SearchContextDocumentsResult:
        self.arguments = arguments
        return SearchContextDocumentsResult(
            task_id=int(arguments["task_id"]),
            query=str(arguments["query"]),
            returned_count=0,
            truncated=False,
            results=[],
        )


class RecordingQueryService:
    def __init__(self) -> None:
        self.arguments: dict[str, object] = {}

    def execute(self, **arguments: object) -> dict[str, object]:
        self.arguments = arguments
        return {"rows": [[1]], "returned_rows": 1}


class RecordingAiDataVisualizationService:
    def __init__(self) -> None:
        self.arguments: dict[str, object] = {}

    def create_for_task(self, **arguments: object) -> _PrepareResult:
        self.arguments = arguments
        return _PrepareResult()


class _TaskVisualizationResult:
    def model_dump(self, **_: object) -> dict[str, object]:
        return {"task_id": 9, "status": "resolved", "revision": 1}


class RecordingAiTaskVisualizationService:
    def __init__(self) -> None:
        self.task_id = 0
        self.payload: object | None = None

    def save_result(self, task_id: int, payload: object) -> _TaskVisualizationResult:
        self.task_id = task_id
        self.payload = payload
        return _TaskVisualizationResult()


class RecordingMiddlewareContextService:
    def __init__(self) -> None:
        self.arguments: dict[str, object] = {}

    def read(self, **arguments: object) -> _PrepareResult:
        self.arguments = arguments
        return _PrepareResult()


class RecordingValueMappingService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def search_for_task(self, **arguments: object) -> dict[str, object]:
        self.calls.append(("search", arguments))
        return {"mappings": [], "returned_count": 0, "truncated": False}

    def resolve_for_task(self, mapping_id: str, **arguments: object) -> dict[str, object]:
        self.calls.append(("resolve", {"mapping_id": mapping_id, **arguments}))
        return {"mapping_id": mapping_id, "candidates": [], "returned_count": 0}


class BlockingForwardingService:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def execute(self, **arguments: object) -> dict[str, object]:
        self.started.set()
        if not self.release.wait(timeout=2):
            raise AssertionError("forwarding execution was not released")
        return {"status": "completed", "arguments": arguments}


class _RuntimeResult:
    def __init__(self, operation_id: str, task_id: int = 9) -> None:
        self.operation_id = operation_id
        self.task_id = task_id

    def model_dump(self, **_: object) -> dict[str, object]:
        return {
            "id": self.operation_id,
            "task_id": self.task_id,
            "workspace_id": "workspace-1",
            "kind": "apply_changes",
            "status": "queued",
            "steps": [],
        }


class RecordingWorkspaceRuntimeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def apply_changes(self, **arguments: object) -> _RuntimeResult:
        self.calls.append(("apply", arguments))
        return _RuntimeResult("operation-1")

    def start_workspace(self, **arguments: object) -> _RuntimeResult:
        self.calls.append(("start", arguments))
        return _RuntimeResult("operation-2")

    def get_operation(self, operation_id: str, log_characters: int) -> _RuntimeResult:
        self.calls.append(("get", {"operation_id": operation_id, "log_characters": log_characters}))
        return _RuntimeResult(operation_id)

    def get_task_id(self, operation_id: str) -> int:
        assert operation_id
        return 9


def test_mcp_exposes_stable_context_and_runtime_tools() -> None:
    service = UnusedService()
    server = create_context_router_mcp(  # type: ignore[arg-type]
        service,
        service,
    )

    tools = asyncio.run(server.list_tools())

    assert [tool.name for tool in tools] == [
        "prepare_task_context",
        "read_task_context",
        "read_middleware_context",
        "search_context_documents",
        "read_context_document",
        "search_database_objects",
        "execute_database_query",
        "save_data_visualization_query",
        "save_task_visualization_result",
        "list_task_containers",
        "inspect_container_errors",
        "read_table_relations",
        "search_relation_tables",
        "search_value_mappings",
        "resolve_value_candidates",
        "search_forwarding_interfaces",
        "read_forwarding_request_history",
        "prepare_forwarding_request",
        "execute_forwarding_request",
        "apply_workspace_changes",
        "start_workspace",
        "get_workspace_operation",
    ]
    assert tools[0].annotations is not None
    assert tools[0].annotations.readOnlyHint is True
    assert tools[0].annotations.destructiveHint is False
    assert tools[0].annotations.idempotentHint is False
    assert tools[0].annotations.openWorldHint is False
    read_only_tools = (
        tools[1],
        tools[2],
        tools[3],
        tools[4],
        tools[5],
        tools[6],
        tools[9],
        *tools[11:17],
    )
    for tool in read_only_tools:
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.idempotentHint is True
        assert tool.annotations.openWorldHint is False
    for tool in (tools[7], tools[8], tools[10]):
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is False
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.idempotentHint is True
    assert tools[17].annotations is not None
    assert tools[17].annotations.readOnlyHint is True
    assert tools[17].annotations.idempotentHint is False
    assert tools[18].annotations is not None
    assert tools[18].annotations.readOnlyHint is False
    assert tools[18].annotations.destructiveHint is False
    assert tools[18].annotations.openWorldHint is True
    for tool in (tools[19], tools[20]):
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is False
        assert tool.annotations.destructiveHint is True
        assert tool.annotations.idempotentHint is False
    for tool in (tools[21],):
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.idempotentHint is True
    prepare_schema = tools[0].inputSchema
    assert prepare_schema["required"] == ["task", "cwd"]
    assert set(prepare_schema["properties"]) == {
        "task",
        "cwd",
        "agent_name",
        "environment",
        "intent_type",
        "error_signal",
        "intent_summary",
    }
    environment_schema = str(prepare_schema["properties"]["environment"])
    assert "^[a-z][a-z0-9_-]{0,31}$" in environment_schema
    assert "Omit to use local" in environment_schema
    assert "bug_investigate" in str(prepare_schema["properties"]["intent_type"])
    assert "execution_contract" in PREPARE_TOOL_DESCRIPTION
    assert "read_task_context" in PREPARE_TOOL_DESCRIPTION
    assert "sensitive" in READ_TASK_CONTEXT_TOOL_DESCRIPTION
    assert "not the authoritative or live source" in READ_TASK_CONTEXT_TOOL_DESCRIPTION
    assert "reveal_secrets" in READ_MIDDLEWARE_CONTEXT_TOOL_DESCRIPTION
    assert "returns plaintext fields by default" in READ_MIDDLEWARE_CONTEXT_TOOL_DESCRIPTION
    assert "Returning and using connection values" in READ_MIDDLEWARE_CONTEXT_TOOL_DESCRIPTION
    assert "never echo it into logs" in MCP_SERVER_INSTRUCTIONS
    task_context_schema = tools[1].inputSchema
    middleware_schema = tools[2].inputSchema
    document_search_schema = tools[3].inputSchema
    database_search_schema = tools[5].inputSchema
    query_schema = tools[6].inputSchema
    assert task_context_schema["required"] == ["task_id", "sections"]
    assert set(task_context_schema["properties"]) == {"task_id", "sections"}
    assert middleware_schema["required"] == ["task_id"]
    assert set(middleware_schema["properties"]) == {
        "task_id",
        "environment",
        "components",
        "reveal_secrets",
    }
    assert middleware_schema["properties"]["reveal_secrets"]["default"] is True
    assert document_search_schema["required"] == ["task_id", "query"]
    assert set(document_search_schema["properties"]) == {"task_id", "query", "limit"}
    assert database_search_schema["required"] == ["task_id", "database", "object_type"]
    assert set(database_search_schema["properties"]) == {
        "task_id",
        "database",
        "object_type",
        "pattern",
        "detail",
        "schema",
        "table",
        "limit",
    }
    assert query_schema["required"] == ["task_id", "database", "sql"]
    assert set(query_schema["properties"]) == {"task_id", "database", "sql"}
    data_visualization_schema = tools[7].inputSchema
    assert data_visualization_schema["required"] == [
        "task_id",
        "description",
        "database_key",
        "schema_name",
        "table_name",
        "keyword",
    ]
    task_visualization_schema = tools[8].inputSchema
    assert task_visualization_schema["required"] == ["task_id", "status", "summary"]
    assert set(task_visualization_schema["properties"]) == {
        "task_id",
        "status",
        "summary",
        "root_cause",
        "code_locations",
        "suggested_actions",
        "verification",
    }
    container_list_schema = tools[9].inputSchema
    assert container_list_schema["required"] == ["task_id"]
    assert set(container_list_schema["properties"]) == {"task_id", "query"}
    inspection_schema = tools[10].inputSchema
    assert inspection_schema["required"] == ["task_id", "container_id"]
    assert set(inspection_schema["properties"]) == {
        "task_id",
        "container_id",
        "since_minutes",
        "tail",
        "keywords",
    }
    relation_schema = tools[11].inputSchema
    assert relation_schema["required"] == ["task_id", "tables"]
    assert set(relation_schema["properties"]) == {
        "task_id",
        "tables",
        "sections",
        "database",
        "evidence",
    }
    assert relation_schema["properties"]["evidence"]["default"] == "none"
    relation_search_schema = tools[12].inputSchema
    assert relation_search_schema["required"] == ["task_id"]
    assert set(relation_search_schema["properties"]) == {
        "task_id",
        "query",
        "database",
        "only_related",
        "limit",
    }
    mapping_search_schema = tools[13].inputSchema
    assert mapping_search_schema["required"] == ["task_id"]
    assert set(mapping_search_schema["properties"]) == {
        "task_id",
        "query",
        "interface_id",
        "location",
        "parameter_path",
        "limit",
    }
    mapping_resolve_schema = tools[14].inputSchema
    assert mapping_resolve_schema["required"] == ["task_id", "mapping_id"]
    assert set(mapping_resolve_schema["properties"]) == {
        "task_id",
        "mapping_id",
        "environment",
        "keyword",
        "limit",
        "selection",
    }
    assert mapping_resolve_schema["properties"]["limit"]["maximum"] == 10
    assert mapping_resolve_schema["properties"]["selection"]["default"] == "default"
    forwarding_history_schema = tools[16].inputSchema
    assert forwarding_history_schema["required"] == ["task_id", "interface_id"]
    assert set(forwarding_history_schema["properties"]) == {
        "task_id",
        "interface_id",
        "limit",
        "success_only",
        "include_response",
    }
    forwarding_prepare_schema = tools[17].inputSchema
    assert forwarding_prepare_schema["required"] == ["task_id", "interface_id"]
    assert set(forwarding_prepare_schema["properties"]) == {
        "task_id",
        "interface_id",
        "environment",
        "address_id",
        "login_account",
        "role_name",
        "path",
        "query",
        "body",
        "value_strategy",
        "refresh_value_keys",
    }
    assert forwarding_prepare_schema["properties"]["value_strategy"]["default"] == (
        "reuse_successful"
    )


def test_value_mapping_tools_forward_only_task_scoped_arguments() -> None:
    document_service = UnusedService()
    mappings = RecordingValueMappingService()
    server = create_context_router_mcp(  # type: ignore[arg-type]
        document_service,
        document_service,
        value_mapping_service=mappings,  # type: ignore[arg-type]
    )

    _, search_result = asyncio.run(
        server.call_tool(
            "search_value_mappings",
            {
                "task_id": 9,
                "query": "货主ID",
                "interface_id": "interface-1",
                "location": "body",
                "parameter_path": "shipperId",
                "limit": 5,
            },
        )
    )
    _, resolve_result = asyncio.run(
        server.call_tool(
            "resolve_value_candidates",
            {
                "task_id": 9,
                "mapping_id": "mapping-1",
                "keyword": "攀枝花",
                "limit": 3,
                "selection": "random",
            },
        )
    )

    assert search_result["returned_count"] == 0
    assert resolve_result["mapping_id"] == "mapping-1"
    assert mappings.calls == [
        (
            "search",
            {
                "task_id": 9,
                "query": "货主ID",
                "interface_id": "interface-1",
                "location": "body",
                "parameter_path": "shipperId",
                "limit": 5,
            },
        ),
        (
            "resolve",
            {
                "mapping_id": "mapping-1",
                "task_id": 9,
                "environment": None,
                "keyword": "攀枝花",
                "limit": 3,
                "selection": "random",
            },
        ),
    ]


def test_forwarding_execution_keeps_mcp_event_loop_responsive() -> None:
    async def scenario() -> None:
        document_service = UnusedService()
        forwarding = BlockingForwardingService()
        server = create_context_router_mcp(  # type: ignore[arg-type]
            document_service,
            document_service,
            interface_forwarding_context_service=forwarding,  # type: ignore[arg-type]
        )

        call = asyncio.create_task(
            server.call_tool(
                "execute_forwarding_request",
                {
                    "task_id": 9,
                    "plan_id": "plan-1",
                    "request_sha256": "a" * 64,
                },
            )
        )
        await asyncio.sleep(0.05)

        assert forwarding.started.is_set()
        assert not call.done()

        forwarding.release.set()
        _, result = await call
        assert result == {
            "status": "completed",
            "arguments": {
                "task_id": 9,
                "plan_id": "plan-1",
                "request_sha256": "a" * 64,
            },
        }

    asyncio.run(scenario())


def test_workspace_runtime_tools_forward_only_task_scoped_arguments() -> None:
    service = UnusedService()
    runtime = RecordingWorkspaceRuntimeService()
    server = create_context_router_mcp(  # type: ignore[arg-type]
        service,
        service,
        workspace_runtime_service=runtime,  # type: ignore[arg-type]
    )

    _, applied = asyncio.run(
        server.call_tool(
            "apply_workspace_changes",
            {"task_id": 9, "changed_files": ["backend/app.py"]},
        )
    )
    _, started = asyncio.run(server.call_tool("start_workspace", {"task_id": 9}))
    _, read = asyncio.run(
        server.call_tool(
            "get_workspace_operation",
            {"operation_id": "operation-1", "log_characters": 2000},
        )
    )

    assert applied["id"] == "operation-1"
    assert started["id"] == "operation-2"
    assert read["id"] == "operation-1"
    assert runtime.calls == [
        ("apply", {"task_id": 9, "changed_files": ["backend/app.py"]}),
        ("start", {"task_id": 9}),
        ("get", {"operation_id": "operation-1", "log_characters": 2000}),
    ]


def test_prepare_forwards_environment_and_declared_intent() -> None:
    preparation = RecordingPreparationService()
    document_service = UnusedService()
    server = create_context_router_mcp(  # type: ignore[arg-type]
        preparation,
        document_service,
    )

    _, result = asyncio.run(
        server.call_tool(
            "prepare_task_context",
            {
                "task": "检查 TEST 环境",
                "cwd": "/workspace/project",
                "agent_name": "codex",
                "environment": "test",
                "intent_type": "bug_investigate",
                "error_signal": True,
                "intent_summary": "只查询报错，不修改代码",
            },
        )
    )

    assert result == {"task_id": 55}
    assert preparation.arguments == {
        "task": "检查 TEST 环境",
        "cwd": "/workspace/project",
        "agent_name": "codex",
        "environment": "test",
        "intent_type": "bug_investigate",
        "error_signal": True,
        "intent_summary": "只查询报错，不修改代码",
    }


def test_read_task_context_forwards_only_requested_sections() -> None:
    preparation = RecordingPreparationService()
    document_service = UnusedService()
    server = create_context_router_mcp(  # type: ignore[arg-type]
        preparation,
        document_service,
    )

    _, result = asyncio.run(
        server.call_tool(
            "read_task_context",
            {"task_id": 9, "sections": ["databases", "environment"]},
        )
    )

    assert result == {"task_id": 55}
    assert preparation.arguments == {
        "task_id": 9,
        "sections": ["databases", "environment"],
    }


def test_read_middleware_context_forwards_only_task_scoped_arguments() -> None:
    document_service = UnusedService()
    middleware = RecordingMiddlewareContextService()
    server = create_context_router_mcp(  # type: ignore[arg-type]
        document_service,
        document_service,
        middleware_context_service=middleware,  # type: ignore[arg-type]
    )

    _, result = asyncio.run(
        server.call_tool(
            "read_middleware_context",
            {
                "task_id": 9,
                "components": ["redis-main", "rocketmq"],
            },
        )
    )

    assert result == {"task_id": 55}
    assert middleware.arguments == {
        "task_id": 9,
        "environment": None,
        "components": ["redis-main", "rocketmq"],
        "reveal_secrets": True,
    }


def test_document_search_forwards_only_fixed_public_arguments() -> None:
    document_service = UnusedService()
    search = RecordingDocumentSearchService()
    server = create_context_router_mcp(  # type: ignore[arg-type]
        document_service,
        document_service,
        document_search_service=search,
    )

    _, result = asyncio.run(
        server.call_tool(
            "search_context_documents",
            {
                "task_id": 9,
                "query": "数据库迁移",
                "limit": 7,
            },
        )
    )

    assert result == {
        "task_id": 9,
        "query": "数据库迁移",
        "returned_count": 0,
        "truncated": False,
        "results": [],
    }
    assert search.arguments == {
        "task_id": 9,
        "query": "数据库迁移",
        "limit": 7,
    }


def test_database_tools_forward_only_fixed_public_arguments() -> None:
    document_service = UnusedService()
    catalog = RecordingCatalogService()
    query = RecordingQueryService()
    server = create_context_router_mcp(  # type: ignore[arg-type]
        document_service,
        document_service,
        catalog,  # type: ignore[arg-type]
        query,  # type: ignore[arg-type]
    )

    _, search_result = asyncio.run(
        server.call_tool(
            "search_database_objects",
            {
                "task_id": 9,
                "database": "analytics",
                "object_type": "table",
                "pattern": "event*",
            },
        )
    )
    _, query_result = asyncio.run(
        server.call_tool(
            "execute_database_query",
            {
                "task_id": 9,
                "database": "analytics",
                "sql": "SELECT 1",
            },
        )
    )

    assert search_result == {"objects": [], "returned_count": 0}
    assert catalog.arguments == {
        "task_id": 9,
        "database": "analytics",
        "object_type": "table",
        "pattern": "event*",
        "detail": "names",
        "schema": None,
        "table": None,
        "limit": 100,
    }
    assert query_result == {"rows": [[1]], "returned_rows": 1}
    assert query.arguments == {
        "task_id": 9,
        "database": "analytics",
        "sql": "SELECT 1",
    }


def test_data_visualization_tool_derives_scope_from_task() -> None:
    document_service = UnusedService()
    visualization = RecordingAiDataVisualizationService()
    server = create_context_router_mcp(  # type: ignore[arg-type]
        document_service,
        document_service,
        ai_data_visualization_service=visualization,  # type: ignore[arg-type]
    )

    _, result = asyncio.run(
        server.call_tool(
            "save_data_visualization_query",
            {
                "task_id": 9,
                "description": "查询合同关联数据",
                "database_key": "c12_mtp_db",
                "schema_name": "public",
                "table_name": "contract",
                "keyword": "HT-001",
            },
        )
    )

    assert result == {"task_id": 55}
    assert visualization.arguments == {
        "task_id": 9,
        "description": "查询合同关联数据",
        "database_key": "c12_mtp_db",
        "schema_name": "public",
        "table_name": "contract",
        "keyword": "HT-001",
    }


def test_task_visualization_tool_saves_structured_conclusion() -> None:
    document_service = UnusedService()
    visualization = RecordingAiTaskVisualizationService()
    server = create_context_router_mcp(  # type: ignore[arg-type]
        document_service,
        document_service,
        ai_task_visualization_service=visualization,  # type: ignore[arg-type]
    )

    _, result = asyncio.run(
        server.call_tool(
            "save_task_visualization_result",
            {
                "task_id": 9,
                "status": "resolved",
                "summary": "定位并修复环境解析问题",
                "root_cause": "环境键未传递",
                "code_locations": [{"path": "backend/src/context_router/main.py", "line": 10}],
                "suggested_actions": ["补充回归测试"],
                "verification": [{"type": "test", "description": "后端测试", "result": "通过"}],
            },
        )
    )

    assert result == {"task_id": 9, "status": "resolved", "revision": 1}
    assert visualization.task_id == 9
    assert visualization.payload is not None
    assert visualization.payload.summary == "定位并修复环境解析问题"  # type: ignore[attr-defined]


def test_task_visualization_tool_rejects_unverified_resolution() -> None:
    document_service = UnusedService()
    server = create_context_router_mcp(  # type: ignore[arg-type]
        document_service,
        document_service,
        ai_task_visualization_service=RecordingAiTaskVisualizationService(),  # type: ignore[arg-type]
    )

    with pytest.raises(ToolError, match="resolved 任务必须至少包含一项验证结果"):
        asyncio.run(
            server.call_tool(
                "save_task_visualization_result",
                {
                    "task_id": 9,
                    "status": "resolved",
                    "summary": "没有验证证据的结论",
                },
            )
        )


@pytest.mark.parametrize("invalid_task_id", ["9", True])
@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        (
            "read_middleware_context",
            {"components": ["redis-main"], "reveal_secrets": True},
        ),
        (
            "search_context_documents",
            {"query": "数据库迁移"},
        ),
        (
            "read_context_document",
            {"requests": [{"document_id": "root"}]},
        ),
        (
            "search_database_objects",
            {"database": "analytics", "object_type": "table"},
        ),
        (
            "execute_database_query",
            {"database": "analytics", "sql": "SELECT 1"},
        ),
    ],
)
def test_followup_tools_reject_coercible_task_ids_before_business_execution(
    invalid_task_id: object,
    tool_name: str,
    arguments: dict[str, object],
) -> None:
    document_service = UnusedService()
    catalog = RecordingCatalogService()
    query = RecordingQueryService()
    server = create_context_router_mcp(  # type: ignore[arg-type]
        document_service,
        document_service,
        catalog,  # type: ignore[arg-type]
        query,  # type: ignore[arg-type]
    )

    with pytest.raises(ToolError):
        asyncio.run(
            server.call_tool(
                tool_name,
                {"task_id": invalid_task_id, **arguments},
            )
        )

    assert catalog.arguments == {}
    assert query.arguments == {}
